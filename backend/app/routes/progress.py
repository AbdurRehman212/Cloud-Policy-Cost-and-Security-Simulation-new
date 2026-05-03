from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models.progress import UserProgress
from app.models.organization import OrganizationMember, ensure_default_organization_membership
from app.models.user import User

progress_bp = Blueprint('progress', __name__)


def _resolve_org_id_for_user(user_id, preferred_org_id=None):
    """Resolve the organization ID for a user."""
    memberships = (
        OrganizationMember.query
        .filter_by(user_id=user_id)
        .order_by(OrganizationMember.joined_at.asc(), OrganizationMember.id.asc())
        .all()
    )
    if memberships:
        allowed = {m.organization_id for m in memberships}
        if preferred_org_id is not None:
            try:
                preferred_org_id = int(preferred_org_id)
            except (TypeError, ValueError):
                preferred_org_id = None
            if preferred_org_id in allowed:
                return preferred_org_id
        return sorted(allowed)[0]
    
    # Ensure default organization if no memberships
    user = User.query.get(user_id)
    if not user:
        return None
    organization, _, _ = ensure_default_organization_membership(user)
    db.session.commit()
    return organization.id


def _get_or_create_progress(user_id, org_id):
    """Get or create user progress record."""
    progress = UserProgress.query.filter_by(user_id=user_id, org_id=org_id).first()
    if not progress:
        progress = UserProgress(
            user_id=user_id,
            org_id=org_id,
            total_points=0,
            level=1,
            badges=[],
            scenarios_completed=[],
            vms_created=0,
            attacks_simulated=0,
            policies_created=0,
            login_streak=0,
        )
        db.session.add(progress)
        db.session.commit()
    return progress


@progress_bp.route('', methods=['GET'])
@jwt_required()
def get_progress():
    """Get current user's progress."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    org_id = _resolve_org_id_for_user(user_id, org_id)
    
    if not org_id:
        return jsonify({'status': 'error', 'error': {'message': 'No organization found'}}), 400
    
    progress = _get_or_create_progress(user_id, org_id)
    return jsonify({
        'status': 'success',
        'data': progress.to_dict(),
    })


@progress_bp.route('/award', methods=['POST'])
@jwt_required()
def award_points():
    """Award points and check for new badges."""
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    action = data.get('action', '').strip()
    points = data.get('points', 0)
    badge = data.get('badge')
    org_id = data.get('org_id') or data.get('organization_id')
    
    if not action:
        return jsonify({'status': 'error', 'error': {'message': 'Action is required'}}), 400
    
    org_id = _resolve_org_id_for_user(user_id, org_id)
    if not org_id:
        return jsonify({'status': 'error', 'error': {'message': 'No organization found'}}), 400
    
    progress = _get_or_create_progress(user_id, org_id)
    
    # Update counters based on action
    if action == 'vm_created':
        progress.vms_created += 1
    elif action == 'db_created':
        progress.vms_created += 1  # Count DBs as VMs for simplicity
    elif action == 'attack_simulated':
        progress.attacks_simulated += 1
    elif action == 'scenario_completed':
        scenario_id = data.get('scenario_id')
        if scenario_id:
            scenarios = progress.scenarios_completed or []
            if scenario_id not in scenarios:
                scenarios.append(scenario_id)
                progress.scenarios_completed = scenarios
    elif action == 'policy_created':
        progress.policies_created += 1
    elif action == 'budget_created':
        progress.policies_created += 1  # Count as policy for now
    
    # Add points
    progress.total_points += points
    
    # Update level
    old_level = progress.level
    progress.update_level()
    new_level = progress.level
    
    # Check for new badges
    new_badges = progress.check_badge_conditions()
    for badge_name in new_badges:
        if badge_name not in (progress.badges or []):
            badges = progress.badges or []
            badges.append(badge_name)
            progress.badges = badges
    
    db.session.commit()
    
    response_data = {
        'points_awarded': points,
        'new_badge': new_badges[0] if new_badges else None,
        'new_level': new_level if new_level > old_level else None,
        'progress': progress.to_dict(),
    }
    
    return jsonify({
        'status': 'success',
        'data': response_data,
    })
