from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.data.scenarios import SCENARIOS
from app.models.organization import OrganizationMember, ensure_default_organization_membership
from app.models.scenarios import ScenarioProgress
from app.models.user import User

scenarios_bp = Blueprint('scenarios', __name__)

SCENARIO_MAP = {scenario['id']: scenario for scenario in SCENARIOS}


def _error(message, status_code=400, code='bad_request'):
    return jsonify({'status': 'error', 'error': {'message': message}}), status_code


def _resolve_org_id_for_user(user_id, preferred_org_id=None):
    memberships = OrganizationMember.query.filter_by(user_id=user_id).all()
    if not memberships:
        user = User.query.get(user_id)
        if user:
            ensure_default_organization_membership(user)
            db.session.commit()
            memberships = OrganizationMember.query.filter_by(user_id=user_id).all()

    if not memberships:
        return None

    org_ids = {membership.organization_id for membership in memberships}
    if preferred_org_id is not None:
        try:
            preferred_org_id = int(preferred_org_id)
        except (TypeError, ValueError):
            preferred_org_id = None
    if preferred_org_id in org_ids:
        return preferred_org_id
    return sorted(org_ids)[0]


def _check_org_access(user_id, org_id, min_role='viewer'):
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return None
    role_hierarchy = {'viewer': 1, 'member': 2, 'admin': 3, 'owner': 4}
    if role_hierarchy.get(member.role, 0) < role_hierarchy.get(min_role, 1):
        return None
    return member


def _scenario_payload(scenario, progress=None):
    total_steps = len(scenario.get('steps', []))
    payload = {
        **scenario,
        'total_steps': total_steps,
        'progress': progress.to_dict() if progress else None,
    }
    return payload


def _get_progress(user_id, org_id, scenario_id):
    return ScenarioProgress.query.filter_by(
        user_id=user_id,
        org_id=org_id,
        scenario_id=scenario_id,
    ).first()


@scenarios_bp.route('', methods=['GET'])
@jwt_required()
def list_scenarios():
    user_id = int(get_jwt_identity())
    org_id = request.args.get('organization_id', type=int)
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return jsonify({'status': 'success', 'data': [], 'organization_id': None}), 200
    if not _check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    progress_rows = {
        progress.scenario_id: progress
        for progress in ScenarioProgress.query.filter_by(user_id=user_id, org_id=org_id).all()
    }
    scenarios = [_scenario_payload(scenario, progress_rows.get(scenario['id'])) for scenario in SCENARIOS]
    return jsonify({'status': 'success', 'data': scenarios, 'organization_id': org_id}), 200


@scenarios_bp.route('/<scenario_id>', methods=['GET'])
@jwt_required()
def get_scenario_detail(scenario_id):
    user_id = int(get_jwt_identity())
    scenario = SCENARIO_MAP.get(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    org_id = request.args.get('organization_id', type=int)
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    progress = _get_progress(user_id, org_id, scenario_id)
    return jsonify({
        'status': 'success',
        'data': _scenario_payload(scenario, progress),
        'organization_id': org_id,
    }), 200


@scenarios_bp.route('/<scenario_id>/progress', methods=['POST'])
@jwt_required()
def save_scenario_progress(scenario_id):
    user_id = int(get_jwt_identity())
    scenario = SCENARIO_MAP.get(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    data = request.get_json() or {}
    body_user_id = data.get('user_id')
    if body_user_id is not None:
        try:
            if int(body_user_id) != user_id:
                return _error('User mismatch', status_code=403, code='forbidden')
        except (TypeError, ValueError):
            return _error('User mismatch', status_code=403, code='forbidden')

    org_id = data.get('org_id') or data.get('organization_id')
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    try:
        step = int(data.get('step'))
    except (TypeError, ValueError):
        return _error('step must be an integer', status_code=400)

    total_steps = len(scenario.get('steps', []))
    if step < 1 or step > total_steps:
        return _error('step out of range', status_code=400)

    progress = _get_progress(user_id, org_id, scenario_id)
    if not progress:
        progress = ScenarioProgress(
            user_id=user_id,
            org_id=org_id,
            scenario_id=scenario_id,
            current_step=0,
            completed=False,
            started_at=datetime.utcnow(),
            points_earned=0,
        )
        db.session.add(progress)

    progress.current_step = max(progress.current_step or 0, step)
    progress.points_earned = int(round((scenario.get('points', 0) * progress.current_step) / total_steps)) if total_steps else 0
    if progress.current_step >= total_steps:
        progress.completed = True
        if not progress.completed_at:
            progress.completed_at = datetime.utcnow()

    db.session.commit()
    return jsonify({
        'status': 'success',
        'data': {
            'progress': progress.to_dict(),
            'scenario': _scenario_payload(scenario, progress),
        },
    }), 200


@scenarios_bp.route('/<scenario_id>/progress', methods=['GET'])
@jwt_required()
def get_scenario_progress(scenario_id):
    user_id = int(get_jwt_identity())
    scenario = SCENARIO_MAP.get(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    org_id = request.args.get('organization_id', type=int)
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    progress = _get_progress(user_id, org_id, scenario_id)
    return jsonify({
        'status': 'success',
        'data': {
            'progress': progress.to_dict() if progress else None,
            'scenario': _scenario_payload(scenario, progress),
        },
    }), 200


@scenarios_bp.route('/<scenario_id>/validate-step', methods=['POST'])
@jwt_required()
def validate_step(scenario_id):
    user_id = int(get_jwt_identity())
    scenario = SCENARIO_MAP.get(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    data = request.get_json() or {}
    org_id = data.get('org_id')
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    step_id = data.get('step_id')
    if step_id is None:
        return _error('step_id is required', status_code=400)

    step = next((s for s in scenario.get('steps', []) if s.get('id') == step_id), None)
    if not step:
        return _error('Step not found', status_code=404, code='not_found')

    validation_type = step.get('validation_type')
    validation_value = step.get('validation_value')
    valid = False
    message = ''

    from app.models.resources import VirtualMachine, ResourceStatus
    from app.models.security import SecurityGroup, ThreatDetection
    from app.models.cost import Budget

    if validation_type == 'vm_exists':
        vm = VirtualMachine.query.filter_by(
            name=validation_value,
            organization_id=org_id,
        ).first()
        valid = vm is not None
        message = 'VM found' if valid else f'VM named "{validation_value}" not found'

    elif validation_type == 'vm_running':
        vm = VirtualMachine.query.filter_by(
            name=validation_value,
            organization_id=org_id,
        ).first()
        valid = vm is not None and vm.status == ResourceStatus.RUNNING
        message = 'VM is running' if valid else f'VM named "{validation_value}" is not running'

    elif validation_type == 'vm_has_security_group':
        vm = VirtualMachine.query.filter_by(
            name=validation_value,
            organization_id=org_id,
        ).first()
        if vm:
            sg = SecurityGroup.query.filter_by(name=validation_value, organization_id=org_id).first()
            valid = sg is not None
            message = 'Security group attached' if valid else f'Security group "{validation_value}" not found'
        else:
            valid = False
            message = f'VM named "{validation_value}" not found'

    elif validation_type == 'threat_exists':
        threat = ThreatDetection.query.filter_by(
            organization_id=org_id,
            threat_type=validation_value,
        ).first()
        valid = threat is not None
        message = 'Threat detected' if valid else f'Threat "{validation_value}" not found'

    elif validation_type == 'threat_resolved':
        threat = ThreatDetection.query.filter_by(
            organization_id=org_id,
            threat_type=validation_value,
        ).first()
        valid = threat is not None and threat.status == 'resolved'
        message = 'Threat resolved' if valid else f'Threat "{validation_value}" not resolved'

    elif validation_type == 'budget_created':
        budget = Budget.query.filter_by(organization_id=org_id).first()
        valid = budget is not None
        message = 'Budget created' if valid else 'No budget found'

    elif validation_type == 'page_visited':
        valid = True
        message = 'Page visited'

    elif validation_type == 'attack_simulated':
        valid = True
        message = 'Attack simulated'

    elif validation_type == 'security_group_modified':
        valid = True
        message = 'Security group modified'

    else:
        valid = False
        message = f'Unknown validation type: {validation_type}'

    return jsonify({
        'status': 'success',
        'data': {
            'valid': valid,
            'message': message,
        },
    }), 200


@scenarios_bp.route('/<scenario_id>/complete', methods=['POST'])
@jwt_required()
def complete_scenario(scenario_id):
    user_id = int(get_jwt_identity())
    scenario = SCENARIO_MAP.get(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    data = request.get_json() or {}
    org_id = data.get('org_id')
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    points = data.get('points', scenario.get('points', 0))

    progress = _get_progress(user_id, org_id, scenario_id)
    if not progress:
        progress = ScenarioProgress(
            user_id=user_id,
            org_id=org_id,
            scenario_id=scenario_id,
            current_step=len(scenario.get('steps', [])),
            completed=True,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            points_earned=points,
        )
        db.session.add(progress)
    else:
        progress.completed = True
        progress.completed_at = datetime.utcnow()
        progress.points_earned = points
        progress.current_step = len(scenario.get('steps', []))

    db.session.commit()
    return jsonify({
        'status': 'success',
        'data': {
            'progress': progress.to_dict(),
            'points_earned': points,
        },
    }), 200
