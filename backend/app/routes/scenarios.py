from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.data.scenarios import SCENARIOS
from app.models.organization import OrganizationMember, ensure_default_organization_membership
from app.models.scenarios import ScenarioProgress
from app.models.user import User
from app.services import control_plane
from app.models.settings import UserSettings
from app.services.learning_engine import (
    curriculum_limit,
    evaluate_scenario_decision,
    lab_validation_engine,
    learning_loop_for_scenario,
    next_unlocked_scenario,
    normalize_learning_level,
    scenario_unlock_state,
)

scenarios_bp = Blueprint('scenarios', __name__)

SCENARIO_MAP = {scenario['id']: scenario for scenario in SCENARIOS}


def _error(message, status_code=400, code='bad_request'):
    return jsonify({'status': 'error', 'error': {'message': message}}), status_code


def _resolve_org_id_for_user(user_id, preferred_org_id=None):
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
    learning_story = learning_loop_for_scenario(scenario)
    payload = {
        **scenario,
        'total_steps': total_steps,
        'progress': progress.to_dict() if progress else None,
        'completion_ratio': round(((progress.current_step or 0) / total_steps) * 100, 1) if progress and total_steps else 0,
        'learning_story': learning_story,
        'role_focus': scenario.get('recommended_for', 'student'),
    }
    return payload


def _get_progress(user_id, org_id, scenario_id):
    return ScenarioProgress.query.filter_by(
        user_id=user_id,
        org_id=org_id,
        scenario_id=scenario_id,
    ).first()

def _selected_learning_track(user_id, progress=None, preferred=None):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    layout = settings.dashboard_layout if settings and isinstance(settings.dashboard_layout, dict) else {}
    stored = layout.get('learning_level') if isinstance(layout, dict) else None
    return normalize_learning_level(preferred or stored or getattr(progress, 'learning_stage', None))


def _scenario_is_locked(user_id, org_id, progress, scenario_id, track):
    next_scenario = next_unlocked_scenario(progress=progress, level=track)
    next_scenario_id = next_scenario.get('id') if next_scenario else None
    lock_limit = curriculum_limit(track)
    member = None
    try:
        member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    except Exception:
        member = None
    if member and member.role in {'admin', 'owner'}:
        return False, None
    completed = set(str(item) for item in (getattr(progress, 'scenarios_completed', None) or []))
    if int(scenario_id) in completed:
        return False, None
    if int(scenario_id) > lock_limit:
        return True, 'Complete the current learning path first.'
    if next_scenario_id is None:
        return True, 'Complete the current learning path first.'
    if int(scenario_id) != int(next_scenario_id):
        return True, f'Unlock the next recommended scenario first: {next_scenario.get("title", "the next module")}'
    return False, None


def _scenario_access_payload(user_id, org_id, scenario, progress=None, preferred_track=None):
    track = _selected_learning_track(user_id, progress=progress, preferred=preferred_track)
    locked, reason = _scenario_is_locked(user_id, org_id, progress, scenario['id'], track)
    payload = _scenario_payload(scenario, progress)
    payload.update({
        'learning_track': track,
        'learning_limit': curriculum_limit(track),
        'learning_lock': {
            'locked': locked,
            'reason': reason,
            'next_scenario': next_unlocked_scenario(progress=progress, level=track),
        },
        'unlock_state': scenario_unlock_state(progress=progress, level=track),
    })
    return payload, locked, reason


def _record_lab3_progress(progress, step_id, evaluation):
    """Persist deterministic Lab 3 step progression and validation history."""
    history = list(progress.history or [])
    history.append({
        'timestamp': datetime.utcnow().isoformat(),
        'step_id': step_id,
        'validation_type': 'lab3_state_predicates',
        'valid': True,
        'score': evaluation.get('score'),
        'grade': evaluation.get('grade'),
        'state': evaluation.get('state', {}),
        'predicates': evaluation.get('predicates', []),
    })
    progress.history = history[-20:]
    progress.current_step = max(progress.current_step or 0, int(step_id))
    if progress.current_step >= 3:
        progress.completed = True
        if not progress.completed_at:
            progress.completed_at = datetime.utcnow()

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
    preferred_track = request.args.get('level')
    scenarios = []
    for scenario in SCENARIOS:
        scenario_payload, _, _ = _scenario_access_payload(
            user_id,
            org_id,
            scenario,
            progress_rows.get(scenario['id']),
            preferred_track=preferred_track,
        )
        scenarios.append(scenario_payload)
    return jsonify({'status': 'success', 'data': scenarios, 'organization_id': org_id}), 200


@scenarios_bp.route('/<scenario_id>', methods=['GET'])
@jwt_required()
def get_scenario_detail(scenario_id):
    user_id = int(get_jwt_identity())
    try:
        s_id_int = int(scenario_id)
    except (TypeError, ValueError):
        return _error('Invalid scenario ID', status_code=400)
    scenario = SCENARIO_MAP.get(s_id_int)
    scenario_id = str(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    org_id = request.args.get('organization_id', type=int)
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    progress = _get_progress(user_id, org_id, scenario_id)
    payload, locked, reason = _scenario_access_payload(user_id, org_id, scenario, progress)
    if locked:
        return _error(reason or 'Scenario locked', status_code=403, code='locked_scenario')
    return jsonify({
        'status': 'success',
        'data': payload,
        'organization_id': org_id,
    }), 200


@scenarios_bp.route('/<scenario_id>/progress', methods=['POST'])
@jwt_required()
def save_scenario_progress(scenario_id):
    user_id = int(get_jwt_identity())
    try:
        s_id_int = int(scenario_id)
    except (TypeError, ValueError):
        return _error('Invalid scenario ID', status_code=400)
    scenario = SCENARIO_MAP.get(s_id_int)
    scenario_id = str(scenario_id)
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
    try:
        s_id_int = int(scenario_id)
    except (TypeError, ValueError):
        return _error('Invalid scenario ID', status_code=400)
    scenario = SCENARIO_MAP.get(s_id_int)
    scenario_id = str(scenario_id)
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
    try:
        s_id_int = int(scenario_id)
    except (TypeError, ValueError):
        return _error('Invalid scenario ID', status_code=400)
    scenario = SCENARIO_MAP.get(s_id_int)
    scenario_id = str(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    data = request.get_json() or {}
    org_id = data.get('org_id')
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'viewer'):
        return _error('Access denied', status_code=403, code='forbidden')

    progress = _get_progress(user_id, org_id, scenario_id)
    _, locked, reason = _scenario_access_payload(user_id, org_id, scenario, progress)
    if locked:
        return _error(reason or 'Scenario locked', status_code=403, code='locked_scenario')

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
    snapshot = control_plane.get_org_snapshot(org_id, use_cache=True)
    try:
        step_id = int(step_id)
    except (TypeError, ValueError):
        return _error('Invalid step ID', status_code=400)

    from app.models.resources import VirtualMachine, ResourceStatus, SecurityGroup
    from app.models.security import ThreatDetection
    from app.models.cost import Budget

    if scenario['id'] == lab_validation_engine.LAB3_SCENARIO_ID:
        lab_result = lab_validation_engine.evaluate_lab3_step(org_id, scenario, step, snapshot)
        valid = lab_result['valid']
        message = lab_result['message']
        evaluation = lab_result['evaluation']
        if valid:
            if not progress:
                progress = ScenarioProgress(
                    user_id=user_id,
                    org_id=org_id,
                    scenario_id=scenario_id,
                    current_step=0,
                    completed=False,
                    started_at=datetime.utcnow(),
                    points_earned=0,
                    history=[],
                )
                db.session.add(progress)
            _record_lab3_progress(progress, step_id, evaluation)
            db.session.commit()
        include_ai = data.get('include_ai', False)
        return jsonify({
            'status': 'success',
            'data': {
                'valid': valid,
                'message': message,
                'learning_loop': scenario.get('learning_loop', {}),
                'cause_effect': scenario.get('cause_effect', {}),
                'snapshot': snapshot,
                'evaluation': evaluation,
                'state': lab_result.get('state', {}),
                'predicates': lab_result.get('predicates', []),
                'targets': lab_result.get('targets', {}),
            },
        }), 200

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

    elif validation_type == 'dashboard_metric_threshold':
        field = (validation_value or {}).get('field')
        operator = (validation_value or {}).get('operator')
        expected = (validation_value or {}).get('value')
        actual = snapshot.get(field)
        if field == 'current_month_spend':
            actual = snapshot.get('current_month_spend', snapshot.get('monthly_spend', 0))
        elif field == 'monthly_spend':
            actual = snapshot.get('monthly_spend', snapshot.get('current_month_spend', 0))
        elif field == 'health_score':
            actual = snapshot.get('health_score_calculated', snapshot.get('health_score', 0))
        elif field == 'security_score':
            actual = snapshot.get('security_score', 0)
        elif field == 'bpi':
            actual = snapshot.get('bpi', 0)
        elif field == 'capacity':
            actual = snapshot.get('capacity', 0)
        elif field == 'desired_capacity':
            actual = snapshot.get('desired_capacity', 0)

        comparisons = {
            'greater_than': lambda a, b: a > b,
            'greater_than_or_equal': lambda a, b: a >= b,
            'less_than': lambda a, b: a < b,
            'less_than_or_equal': lambda a, b: a <= b,
            'equal': lambda a, b: a == b,
        }
        comparator = comparisons.get(operator)
        valid = comparator(float(actual or 0), float(expected or 0)) if comparator else False
        message = f'{field} {operator} {expected}' if valid else f'{field} did not satisfy {operator} {expected}'

    elif validation_type == 'dashboard_action_contains':
        action = (validation_value or {}).get('action')
        actions = snapshot.get('actions', [])
        valid = any(action and action.lower() in str(item).lower() for item in actions)
        message = f'Action "{action}" found' if valid else f'Action "{action}" not found'

    elif validation_type == 'recovery_action_executed':
        action = (validation_value or {}).get('action')
        actions = snapshot.get('actions', [])
        valid = any(action and action.lower() in str(item).lower() for item in actions)
        message = f'Recovery action "{action}" executed' if valid else f'Recovery action "{action}" not executed'

    elif validation_type == 'security_rule_updated':
        valid = True
        message = 'Security rule updated'

    else:
        valid = False
        message = f'Unknown validation type: {validation_type}'

    include_ai = data.get('include_ai', False)
    evaluation = evaluate_scenario_decision(scenario, snapshot, include_ai=include_ai)
    return jsonify({
        'status': 'success',
        'data': {
            'valid': valid,
            'message': message,
            'learning_loop': scenario.get('learning_loop', {}),
            'cause_effect': scenario.get('cause_effect', {}),
            'snapshot': snapshot,
            'evaluation': evaluation,
        },
    }), 200


@scenarios_bp.route('/<scenario_id>/complete', methods=['POST'])
@jwt_required()
def complete_scenario(scenario_id):
    user_id = int(get_jwt_identity())
    try:
        s_id_int = int(scenario_id)
    except (TypeError, ValueError):
        return _error('Invalid scenario ID', status_code=400)
    scenario = SCENARIO_MAP.get(s_id_int)
    scenario_id = str(scenario_id)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    data = request.get_json() or {}
    org_id = data.get('org_id')
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    progress = _get_progress(user_id, org_id, scenario_id)
    _, locked, reason = _scenario_access_payload(user_id, org_id, scenario, progress)
    if locked:
        return _error(reason or 'Scenario locked', status_code=403, code='locked_scenario')

    points = data.get('points', scenario.get('points', 0))

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

    snapshot = control_plane.get_org_snapshot(org_id, use_cache=True)
    include_ai = data.get('include_ai', False)
    evaluation = evaluate_scenario_decision(scenario, snapshot, include_ai=include_ai)

    history = list(progress.history or [])
    history.append({
        'timestamp': datetime.utcnow().isoformat(),
        'action': 'complete',
        'score': evaluation.get('score'),
        'grade': evaluation.get('grade')
    })
    progress.history = history

    db.session.commit()
    return jsonify({
        'status': 'success',
        'data': {
            'progress': progress.to_dict(),
            'points_earned': points,
            'evaluation': evaluation,
        },
    }), 200


@scenarios_bp.route('/<scenario_id>/run', methods=['POST'])
@jwt_required()
def run_scenario(scenario_id):
    """Start a scenario simulation run via SimulationEngine.start_scenario().

    Returns 202 Accepted immediately.
    The engine manages its own background thread — no task spawning here.
    Returns 409 if already running.
    """
    user_id = int(get_jwt_identity())

    try:
        sid = int(scenario_id)
    except (TypeError, ValueError):
        return _error('Invalid scenario ID', status_code=400)

    scenario = SCENARIO_MAP.get(sid)
    if not scenario:
        return _error('Scenario not found', status_code=404, code='not_found')

    data = request.get_json() or {}
    org_id = data.get('org_id') or data.get('organization_id')
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    from app.services.scenario_runner import scenario_runner

    result = scenario_runner.start(scenario_id=sid, org_id=org_id)

    if not result.get('ok'):
        return jsonify({
            'status': 'error',
            'error': {
                'message': result.get('error', 'Failed to start scenario.'),
                'code': result.get('code', 'scenario_error'),
            },
        }), 409

    return jsonify({'status': 'success', 'data': result}), 202


@scenarios_bp.route('/<scenario_id>/run/status', methods=['GET'])
@jwt_required()
def run_scenario_status(scenario_id):
    """Check whether a scenario simulation run is active for an org."""
    user_id = int(get_jwt_identity())
    org_id = request.args.get('organization_id', type=int)
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')

    from app.services.scenario_runner import scenario_runner
    return jsonify({
        'status': 'success',
        'data': {
            **scenario_runner.get_state(org_id),
            'scenario_id': scenario_id,
        },
    }), 200


@scenarios_bp.route('/<scenario_id>/run/stop', methods=['POST'])
@jwt_required()
def stop_scenario_run(scenario_id):
    """Stop an active scenario simulation run."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    org_id = data.get('org_id') or data.get('organization_id')
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if org_id is None:
        return _error('Access denied', status_code=403, code='forbidden')
    if not _check_org_access(user_id, org_id, 'member'):
        return _error('Access denied', status_code=403, code='forbidden')

    from app.services.scenario_runner import scenario_runner
    scenario_runner.stop(org_id)
    return jsonify({'status': 'success', 'data': {'stopped': True, 'org_id': org_id}}), 200
