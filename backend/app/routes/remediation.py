"""Module 10 — Remediation Agent API.

Read endpoints (issues, plan, history) are open to every member of the organization,
including viewers, because they change nothing. Executing a remediation changes simulated
resources and is limited to admins and owners (UC10 actor: Administrator).
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.utils.identity import get_jwt_identity  # int identity; tokens carry it as a string

from app.services import remediation_service as svc
from app.services.audit_service import record_audit_safely
from app.utils.rbac import ROLE_HIERARCHY, active_membership

remediation_bp = Blueprint('remediation', __name__)


def _ok(data, status=200):
    return jsonify({'status': 'success', 'data': data}), status


def _err(message, status=400, code='bad_request'):
    return jsonify({'status': 'error', 'error': {'message': message, 'code': code}}), status


def _context(min_role='viewer'):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    raw = body.get('organization_id') or body.get('org_id') or request.args.get('organization_id') or request.args.get('org_id')
    try:
        org_id = int(raw)
    except (TypeError, ValueError):
        return None, None, None, _err('organization_id required')
    member = active_membership(user_id, org_id)
    if member is None:
        return None, None, None, _err('Access denied', 403, 'forbidden')
    if ROLE_HIERARCHY.get(member.role, -1) < ROLE_HIERARCHY[min_role]:
        return None, None, None, _err(f'Requires {min_role} role', 403, 'forbidden')
    return user_id, org_id, member, None


@remediation_bp.route('/issues', methods=['GET'])
@jwt_required()
def issues():
    user_id, org_id, member, error = _context()
    if error:
        return error
    items = svc.list_issues(org_id)
    return _ok({
        'issues': items,
        'total': len(items),
        'can_execute': ROLE_HIERARCHY.get(member.role, -1) >= ROLE_HIERARCHY['admin'],
    })


@remediation_bp.route('/plan', methods=['POST'])
@jwt_required()
def plan():
    user_id, org_id, member, error = _context()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    try:
        result = svc.build_plan(org_id, body.get('issue_key'), body.get('target_resource_id'))
    except svc.RemediationError as exc:
        return _err(exc.message, exc.status_code, exc.code)
    record_audit_safely(
        'remediation_recommended', org_id=org_id, user_id=user_id, resource_type=result['issue']['type'],
        resource_id=result['issue']['key'],
        new_values={'actions': [a['action'] for a in result['actions']], 'engine': result['engine']},
    )
    result['can_execute'] = ROLE_HIERARCHY.get(member.role, -1) >= ROLE_HIERARCHY['admin']
    return _ok(result)


@remediation_bp.route('/execute', methods=['POST'])
@jwt_required()
def execute():
    user_id, org_id, member, error = _context('admin')
    if error:
        if error[1] == 403:
            body = request.get_json(silent=True) or {}
            raw_org = body.get('organization_id')
            if active_membership(int(get_jwt_identity()), raw_org) is not None:
                record_audit_safely('remediation_denied', org_id=raw_org, user_id=int(get_jwt_identity()),
                                    resource_type='remediation', resource_id=body.get('issue_key'), outcome='denied')
        return error
    body = request.get_json(silent=True) or {}
    try:
        result = svc.execute(
            org_id, user_id, body.get('issue_key'), body.get('actions'),
            body.get('approved'), body.get('target_resource_id'),
        )
    except svc.RemediationError as exc:
        return _err(exc.message, exc.status_code, exc.code)
    return _ok(result)


@remediation_bp.route('/history', methods=['GET'])
@jwt_required()
def history():
    user_id, org_id, member, error = _context()
    if error:
        return error
    limit = max(1, min(request.args.get('limit', default=50, type=int), 200))
    offset = max(0, request.args.get('offset', default=0, type=int))
    return _ok({
        'actions': svc.history(org_id, issue_key=request.args.get('issue_key'), limit=limit, offset=offset),
        'total': svc.history_count(org_id),
        'limit': limit,
        'offset': offset,
    })
