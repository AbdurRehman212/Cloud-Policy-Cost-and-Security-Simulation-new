from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.models.governance import AuditLog, ComplianceCheck, Policy, PolicyStatus
from app.models.organization import OrganizationMember
from app.services.governance_engine import governance_engine

governance_bp = Blueprint('governance', __name__)


def _resolve_org_id():
    return request.args.get('organization_id', type=int) or request.args.get('org_id', type=int)


def _require_org_member(user_id: int, org_id: int):
    if org_id is None:
        return None
    return OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()


def _error(message: str, status_code: int = 400):
    return jsonify({'status': 'error', 'error': {'message': message}}), status_code


def _success(data: dict, status_code: int = 200):
    return jsonify({'status': 'success', 'data': data}), status_code


@governance_bp.route('/policies', methods=['POST'])
@jwt_required()
def create_policy():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    org_id = data.get('organization_id') or data.get('org_id')
    member = _require_org_member(user_id, org_id)
    if not member or member.role not in ['admin', 'owner']:
        return _error('Insufficient permissions', 403)

    name = (data.get('name') or '').strip()
    policy_rule = (data.get('policy_rule') or data.get('natural_language_rule') or '').strip()
    if not name:
        return _error('Policy name is required', 400)
    if not policy_rule:
        return _error('Policy rule is required', 400)

    parsed = governance_engine.compile_policy_text(policy_rule)
    if not parsed['success']:
        return _error(parsed['error'], 400)

    status_value = data.get('status', PolicyStatus.ACTIVE.value)
    if status_value not in {status.value for status in PolicyStatus}:
        return _error('Invalid policy status', 400)

    parsed_rule = parsed['parsed_rule']
    rule_fields = parsed_rule.get('fields', parsed_rule)
    policy = Policy(
        organization_id=org_id,
        name=name,
        description=data.get('description'),
        natural_language_rule=policy_rule,
        compiled_rule=parsed_rule,
        policy_type=rule_fields.get('type', 'custom'),
        auto_remediate=bool(data.get('auto_remediate', False)),
        severity=rule_fields.get('severity', 'medium'),
        status=PolicyStatus(status_value),
        created_by=user_id,
    )
    db.session.add(policy)
    db.session.flush()
    governance_engine._record_audit_event(
        org_id=org_id,
        user_id=user_id,
        action='policy_created',
        resource_type='policy',
        resource_id=str(policy.id),
        new_values=policy.to_dict(),
    )
    db.session.commit()

    return _success(
        {
            'message': 'Policy created',
            'policy': policy.to_dict(),
            'parsed_confidence': parsed['confidence'],
        },
        201,
    )


@governance_bp.route('/policies', methods=['GET'])
@jwt_required()
def list_policies():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    member = _require_org_member(user_id, org_id)
    if not member:
        return _error('Access denied', 403)

    policies = (
        Policy.query
        .filter_by(organization_id=org_id)
        .order_by(Policy.created_at.desc(), Policy.id.desc())
        .all()
    )
    return _success({'policies': [policy.to_dict() for policy in policies]})


@governance_bp.route('/policies/<int:policy_id>', methods=['PUT'])
@jwt_required()
def update_policy(policy_id):
    user_id = get_jwt_identity()
    policy = Policy.query.get_or_404(policy_id)
    member = _require_org_member(user_id, policy.organization_id)
    if not member or member.role not in ['admin', 'owner']:
        return _error('Insufficient permissions', 403)

    data = request.get_json() or {}
    old_values = policy.to_dict()

    policy.name = (data.get('name') or policy.name).strip()
    policy.description = data.get('description', policy.description)
    policy.auto_remediate = bool(data.get('auto_remediate', policy.auto_remediate))

    if data.get('policy_rule') or data.get('natural_language_rule'):
        policy_rule = (data.get('policy_rule') or data.get('natural_language_rule')).strip()
        parsed = governance_engine.compile_policy_text(policy_rule)
        if not parsed['success']:
            return _error(parsed['error'], 400)
        policy.natural_language_rule = policy_rule
        parsed_rule = parsed['parsed_rule']
        rule_fields = parsed_rule.get('fields', parsed_rule)
        policy.compiled_rule = parsed_rule
        policy.policy_type = rule_fields.get('type', policy.policy_type or 'custom')
        policy.severity = rule_fields.get('severity', policy.severity or 'medium')

    if data.get('status') in {status.value for status in PolicyStatus}:
        policy.status = PolicyStatus(data['status'])

    governance_engine._record_audit_event(
        org_id=policy.organization_id,
        user_id=user_id,
        action='policy_updated',
        resource_type='policy',
        resource_id=str(policy.id),
        old_values=old_values,
        new_values=policy.to_dict(),
    )
    db.session.commit()

    return _success({'message': 'Policy updated', 'policy': policy.to_dict()})


@governance_bp.route('/policies/<int:policy_id>', methods=['DELETE'])
@jwt_required()
def delete_policy(policy_id):
    user_id = get_jwt_identity()
    policy = Policy.query.get_or_404(policy_id)
    member = _require_org_member(user_id, policy.organization_id)
    if not member or member.role not in ['admin', 'owner']:
        return _error('Insufficient permissions', 403)

    snapshot = policy.to_dict()
    org_id = policy.organization_id
    ComplianceCheck.query.filter_by(policy_id=policy.id).delete(synchronize_session=False)
    db.session.delete(policy)
    governance_engine._record_audit_event(
        org_id=org_id,
        user_id=user_id,
        action='policy_deleted',
        resource_type='policy',
        resource_id=str(policy_id),
        old_values=snapshot,
        new_values={'deleted': True},
    )
    db.session.commit()
    return _success({'message': 'Policy deleted'})


@governance_bp.route('/compliance/check', methods=['POST'])
@jwt_required()
def check_compliance():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    org_id = data.get('organization_id') or data.get('org_id')
    member = _require_org_member(user_id, org_id)
    if not member:
        return _error('Access denied', 403)

    result = governance_engine.evaluate_org_policies(org_id, actor_user_id=user_id)
    return _success(result)


@governance_bp.route('/compliance/checks', methods=['GET'])
@jwt_required()
def get_compliance_checks():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    member = _require_org_member(user_id, org_id)
    if not member:
        return _error('Access denied', 403)

    limit = request.args.get('limit', default=100, type=int)
    checks = governance_engine.get_recent_checks(org_id, limit=max(1, min(limit, 500)))
    return _success({'checks': checks})


@governance_bp.route('/audit-logs', methods=['GET'])
@jwt_required()
def get_audit_logs():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    member = _require_org_member(user_id, org_id)
    if not member:
        return _error('Access denied', 403)

    logs = (
        AuditLog.query
        .filter_by(organization_id=org_id)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(1000)
        .all()
    )
    return _success({'logs': [log.to_dict() for log in logs], 'total': len(logs)})
