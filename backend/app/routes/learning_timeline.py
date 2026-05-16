"""Learning Timeline API - Persistent operational event timeline.

Uses actual AuditLog entries for real operational history instead of
reconstructed state.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from app.models.progress import UserProgress
from app.models.organization import OrganizationMember
from app.models.resources import VirtualMachine, Database, SecurityGroup
from app.models.cost import Budget
from app.models.security import ThreatDetection
from app.services.operational_event_service import operational_event_service, OPERATIONAL_EVENTS

timeline_bp = Blueprint('timeline', __name__)


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
    return None


def _get_or_create_progress(user_id, org_id):
    """Get or create user progress for an org."""
    progress = UserProgress.query.filter_by(
        user_id=user_id, org_id=org_id
    ).first()
    if not progress:
        progress = UserProgress(
            user_id=user_id,
            org_id=org_id,
            total_points=0,
            level=1,
        )
        db.session.add(progress)
        db.session.flush()
    return progress


@timeline_bp.route('/timeline', methods=['GET'])
@jwt_required()
def get_learning_timeline():
    """Get learning timeline with persistent operational events."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)

    if not org_id:
        org_id = _resolve_org_id_for_user(user_id)
    if not org_id:
        return jsonify({'status': 'error', 'error': {'message': 'No organization found'}}), 400

    progress = _get_or_create_progress(user_id, org_id)

    # Get PERSISTENT operational events from AuditLog
    timeline_events = operational_event_service.get_timeline(org_id, limit=50)

    # Get event counts by category
    event_counts = operational_event_service.get_event_counts(org_id)

    # Get current resource counts
    vm_count = VirtualMachine.query.filter_by(
        organization_id=org_id
    ).filter(VirtualMachine.status != 'terminated').count()

    db_count = Database.query.filter_by(
        organization_id=org_id
    ).filter(Database.status != 'terminated').count()

    sg_count = SecurityGroup.query.filter_by(org_id=org_id).count()
    budget_count = Budget.query.filter_by(organization_id=org_id, is_active=True).count()

    # Get active threats
    active_threats = ThreatDetection.query.filter_by(
        organization_id=org_id, status='active'
    ).count()

    # Get skill progression
    skill_progression = []

    if progress.vms_created > 0:
        skill_progression.append({
            'skill': 'Compute Provisioning',
            'level': min(progress.vms_created, 5),
            'xp': progress.vms_created * 10,
        })

    if progress.attacks_simulated > 0:
        skill_progression.append({
            'skill': 'Security Operations',
            'level': min(progress.attacks_simulated, 5),
            'xp': progress.attacks_simulated * 15,
        })

    if progress.policies_created > 0:
        skill_progression.append({
            'skill': 'Governance',
            'level': min(progress.policies_created, 5),
            'xp': progress.policies_created * 10,
        })

    # Milestones are also derived from audit-backed operational events.
    milestones = []

    # Build milestones from OPERATIONAL EVENTS
    milestones = []

    # First VM - check from persistent events
    if event_counts.get('compute', 0) > 0:
        milestones.append({
            'id': 'first_vm',
            'title': 'Compute Foundations',
            'description': f'{event_counts.get("compute", 0)} compute event(s)',
            'completed': True,
            'order': 1,
        })

    if event_counts.get('scaling', 0) > 0:
        milestones.append({
            'id': 'scaling',
            'title': 'Capacity Scaling',
            'description': f'{event_counts.get("scaling", 0)} scaling event(s)',
            'completed': True,
            'order': 2,
        })

    if event_counts.get('security', 0) > 0:
        milestones.append({
            'id': 'security_ops',
            'title': 'Security Operations',
            'description': f'{event_counts.get("security", 0)} security event(s)',
            'completed': True,
            'order': 3,
        })

    if event_counts.get('cost', 0) > 0:
        milestones.append({
            'id': 'cost_governance',
            'title': 'Cost Governance',
            'description': f'{event_counts.get("cost", 0)} cost event(s)',
            'completed': True,
            'order': 4,
        })

    if active_threats > 0:
        milestones.append({
            'id': 'security_response',
            'title': 'Security Response',
            'description': f'{active_threats} active threat(s)',
            'completed': True,
            'order': 5,
        })

    # Learning narrative
    level_title = progress.level_title

    if progress.level == 1:
        narrative = "You're starting your cloud journey! Create resources and observe their behavior."
    elif progress.level == 2:
        narrative = "You've mastered the basics. Try implementing autoscaling and cost budgets."
    elif progress.level == 3:
        narrative = "Intermediate cloud operator! Focus on security and cost optimization."
    elif progress.level == 4:
        narrative = "Advanced practitioner. Consider multi-tier architectures."
    elif progress.level >= 5:
        narrative = "Cloud architect level! You can design complex cloud systems."
    else:
        narrative = "Keep learning and building cloud skills!"

    # Sort milestones by order
    milestones.sort(key=lambda m: m.get('order', 99))

    return jsonify({
        'status': 'success',
        'data': {
            'milestones': milestones,
            'timeline_events': timeline_events[:20],  # Top 20 recent events
            'skill_progression': skill_progression,
            'narrative': narrative,
            'level': progress.level,
            'level_title': level_title,
            'total_points': progress.total_points,
            'xp_to_next': progress.xp_to_next_level,
            'resources_created': {
                'vms': vm_count,
                'databases': db_count,
                'security_groups': sg_count,
                'budgets': budget_count,
            },
            'security_status': {
                'active_threats': active_threats,
            },
            'event_counts': event_counts,
        },
    }), 200


@timeline_bp.route('/context', methods=['GET'])
@jwt_required()
def get_learning_context():
    """Get contextual learning feedback for current state."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)

    if not org_id:
        org_id = _resolve_org_id_for_user(user_id)
    if not org_id:
        return jsonify({'status': 'error', 'error': {'message': 'No organization found'}}), 400

    # Get current state
    vm_count = VirtualMachine.query.filter_by(
        organization_id=org_id
    ).filter(VirtualMachine.status == 'running').count()

    running_vms = VirtualMachine.query.filter_by(
        organization_id=org_id, status='running'
    ).all()

    # Calculate average utilization
    avg_cpu = 0.0
    if running_vms:
        total_cpu = sum(float(vm.cpu_utilization or 0) for vm in running_vms)
        avg_cpu = total_cpu / len(running_vms)

    # Get budget status
    budgets = Budget.query.filter_by(organization_id=org_id, is_active=True).all()

    budget_alerts = []
    for budget in budgets:
        budget_status = budget.to_dict()
        percentage_used = budget_status.get('percentage_used', 0)
        if percentage_used >= 100:
            budget_alerts.append({
                'budget_id': budget.id,
                'name': budget.name,
                'alert': 'critical',
            })
        elif percentage_used >= 80:
            budget_alerts.append({
                'budget_id': budget.id,
                'name': budget.name,
                'alert': 'warning',
            })

    # Generate contextual recommendations
    recommendations = []

    if vm_count == 0:
        recommendations.append({
            'type': 'action',
            'title': 'Create Your First VM',
            'description': 'Start by provisioning a compute instance to learn cloud basics.',
            'priority': 'high',
        })
    elif vm_count < 3:
        recommendations.append({
            'type': 'exploration',
            'title': 'Scale Out',
            'description': 'Try adding more instances to understand autoscaling concepts.',
            'priority': 'medium',
        })
    elif avg_cpu > 80:
        recommendations.append({
            'type': 'optimization',
            'title': 'High Utilization',
            'description': f'Average CPU is {avg_cpu:.0f}%. Consider scaling up or right-sizing.',
            'priority': 'high',
        })
    elif avg_cpu < 20:
        recommendations.append({
            'type': 'optimization',
            'title': 'Underutilized Resources',
            'description': f'Average CPU is {avg_cpu:.0f}%. These VMs might be oversized.',
            'priority': 'medium',
        })

    if budget_alerts:
        recommendations.append({
            'type': 'budget',
            'title': 'Budget Alert',
            'description': f'{len(budget_alerts)} budget(s) approaching limit',
            'priority': 'high',
        })

    return jsonify({
        'status': 'success',
        'data': {
            'current_state': {
                'vm_count': vm_count,
                'avg_cpu_percent': round(avg_cpu, 1),
            },
            'recommendations': recommendations,
            'budget_alerts': budget_alerts,
        },
    }), 200
