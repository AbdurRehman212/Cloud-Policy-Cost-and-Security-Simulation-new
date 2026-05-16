from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.organization import OrganizationMember
from app.models.resources import VirtualMachine, Database, ResourceStatus
from app.services import control_plane
from datetime import datetime
import time
dashboard_bp = Blueprint('dashboard', __name__)
@dashboard_bp.route('/summary', methods=['GET'])
@jwt_required()
def get_dashboard_summary():
    """Get dashboard summary data."""
    t0 = time.time()
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    sim_data = control_plane.get_org_snapshot(org_id, use_cache=True)
    snapshot_resources = sim_data.get('resources', {})
    snapshot_security = sim_data.get('security', {})
    snapshot_costs = sim_data.get('costs', {})
    snapshot_governance = sim_data.get('governance', {})
    workload = sim_data.get('workload', {})
    total_vms = sim_data.get('total_vms', snapshot_resources.get('vms', {}).get('total', 0))
    running_vms = sim_data.get('running_vms', snapshot_resources.get('vms', {}).get('running', 0))
    total_dbs = snapshot_resources.get('databases', {}).get('total', 0)
    running_dbs = snapshot_resources.get('databases', {}).get('running', 0)
    active_threats = snapshot_security.get('active_threats', 0)
    security_score = snapshot_security.get('security_score', 100)
    current_spend = snapshot_costs.get('current_month_spend', 0.0)
    monthly_spend = snapshot_costs.get('monthly_spend', 0.0)
    budgets = snapshot_costs.get('budgets', [])
    compliance_score = snapshot_governance.get('compliance_score', 100)
    utilization_score = sim_data.get('utilization_score', 100)
    health_score_calculated = sim_data.get('health_score_calculated')
    if health_score_calculated is None:
        health_score_calculated = int((security_score * 0.4) + (compliance_score * 0.4) + (utilization_score * 0.2))

    budget_status = []
    for b in budgets:
        status = dict(b)
        status['alert_level'] = 'normal'
        if status.get('percentage_used', 0) > 100:
            status['alert_level'] = 'critical'
        elif status.get('percentage_used', 0) > 80:
            status['alert_level'] = 'warning'
        budget_status.append(status)

    # TASK 6: Log API response time for performance monitoring.
    response_ms = round((time.time() - t0) * 1000, 1)
    current_app.logger.info(
        f"[DASHBOARD] API response_time={response_ms}ms org={org_id} "
        f"bpi={sim_data.get('bpi')} target_bpi={sim_data.get('target_bpi')} "
        f"capacity={sim_data.get('capacity')}"
    )
    print(f"[PERF] /api/dashboard/summary response time: {response_ms} ms")

    # Extract causal metrics for learning feedback
    q_ms = workload.get('queue_total_ms', 0)
    rps = workload.get('requests_per_second', 0)
    capacity = sim_data.get('capacity', 1)
    drops = workload.get('dropped_recent_total', 0)

    if q_ms > 1000:
        res_exp = f"Queue is high ({q_ms:.0f}ms) because load ({rps} RPS) exceeds drain capacity of {capacity} VMs."
        res_act = "Scale out VMs to increase capacity and drain the queue, preventing dropped requests."
    elif drops > 0:
        res_exp = f"System is overloaded! {drops} requests dropped because {capacity} VMs cannot handle {rps} RPS."
        res_act = "Immediately provision more VMs to restore availability."
    elif capacity > 0 and rps == 0:
        res_exp = f"{capacity} VMs are running idle with 0 RPS load."
        res_act = "Scale in to 0 or 1 VMs to stop wasting budget on idle resources."
    else:
        res_exp = f"System is stable. {capacity} VMs are comfortably processing {rps} RPS."
        res_act = "Monitor load trends to ensure you are not over-provisioned."

    return jsonify({
        'org_id': org_id,
        'organization_id': org_id,
        'resources': {
            'vms': {
                'total': total_vms,
                'running': running_vms
            },
            'databases': {'total': total_dbs, 'running': running_dbs},
            'explanation': res_exp,
            'actionable_suggestion': res_act
        },
        'security': {
            'active_threats': active_threats,
            'status': 'critical' if active_threats > 0 else 'healthy',
            'security_score': security_score,
            'explanation': f"Security score is {security_score}/100 with {active_threats} active threats.",
            'actionable_suggestion': 'Investigate and resolve active threats to improve score.' if active_threats > 0 else 'Keep security groups tight to maintain your perfect score.'
        },
        'costs': {
            'current_month_spend': round(current_spend, 2),
            'monthly_spend': round(monthly_spend, 2),
            'budgets': budget_status,
            'explanation': f"Current spend is ${round(current_spend, 2)}.",
            'actionable_suggestion': 'Create a budget to track spending against limits.' if not budgets else 'Check for unutilized resources.'
        },
        'cost_trend': sim_data.get('cost_trend', []),
        'utilization_trend': sim_data.get('utilization_trend', []),
        'recent_activity': sim_data.get('recent_activity', []),
        'security_score': security_score,
        'compliance_score': compliance_score,
        'utilization_score': utilization_score,
        'total_vms': total_vms,
        'running_vms': running_vms,
        'health_score': calculate_health_score(active_threats, running_vms, total_vms, current_spend, budget_status),
        'health_score_calculated': health_score_calculated,
        # Simulation data for E2E tests
        'cpu_avg': sim_data.get('cpu_avg', 0),
        'memory_avg': sim_data.get('memory_avg', 0),
        'bpi': sim_data.get('bpi', 0),
        'target_bpi': sim_data.get('target_bpi', 0),
        'capacity': sim_data.get('capacity', 1),
        'desired_capacity': sim_data.get('desired_capacity', 1),
        'running_capacity': sim_data.get('running_capacity', 0),
        'workload': sim_data.get('workload', {}),
        'alerts': sim_data.get('alerts', []),
        'actions': sim_data.get('actions', []),
        'alert_states': sim_data.get('alert_states', {}),
        'snapshot_timestamp': sim_data.get('snapshot_timestamp', sim_data.get('timestamp')),
        'snapshot_age_seconds': sim_data.get('snapshot_age_seconds', 0.0),
        'snapshot_fresh': sim_data.get('snapshot_fresh', True),
        'cost_performance': sim_data.get('cost_performance', {}),
        'timestamp': datetime.utcnow().timestamp()
    }), 200


def calculate_health_score(active_threats, running_vms, total_vms, current_spend, budgets):
    """Return a bounded dashboard health score from security, utilization, and cost signals."""
    score = 100
    score -= min(40, int(active_threats) * 20)

    if total_vms > 0:
        utilization_ratio = (running_vms / total_vms) * 100
        if utilization_ratio < 20:
            score -= 10
        elif utilization_ratio > 90:
            score -= 10

    if budgets:
        if any(budget.get('alert_level') == 'critical' for budget in budgets):
            score -= 15
        elif any(budget.get('alert_level') == 'warning' for budget in budgets):
            score -= 5

    if current_spend <= 0:
        score -= 0

    return max(0, min(100, score))


@dashboard_bp.route('/cost-by-resource', methods=['GET'])
@jwt_required()
def cost_by_resource():
    """Return per-resource cost breakdown sorted by cost descending."""
    user_id = get_jwt_identity()
    org_id = request.args.get('org_id', type=int) or request.args.get('organization_id', type=int)
    if not org_id:
        return jsonify({'status': 'error', 'error': {'message': 'org_id required'}}), 400
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return jsonify({'status': 'error', 'error': {'message': 'Access denied'}}), 403
    items = []
    vms = VirtualMachine.query.filter(
        VirtualMachine.organization_id == org_id,
        VirtualMachine.status != ResourceStatus.TERMINATED,
    ).all()
    for vm in vms:
        cost = round(vm.hourly_rate * (vm.total_runtime_hours or 0.0), 4)
        items.append({
            'name': vm.name,
            'type': 'vm',
            'cost': cost,
            'instance_type': vm.instance_type,
        })
    dbs = Database.query.filter(
        Database.organization_id == org_id,
        Database.status != ResourceStatus.TERMINATED,
    ).all()
    for db_obj in dbs:
        cost = round(db_obj.hourly_rate * (db_obj.total_runtime_hours or 0.0), 4)
        items.append({
            'name': db_obj.name,
            'type': 'database',
            'cost': cost,
            'instance_type': db_obj.instance_class,
        })
    items.sort(key=lambda item: item['cost'], reverse=True)
    return jsonify({'status': 'success', 'data': items}), 200
