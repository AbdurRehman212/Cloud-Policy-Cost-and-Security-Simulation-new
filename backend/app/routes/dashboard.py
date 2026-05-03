from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.organization import OrganizationMember
from app.models.governance import Policy
from app.models.resources import VirtualMachine, Database, ResourceStatus
from app.models.security import ThreatDetection, ThreatSeverity
from app.models.cost import CostRecord, Budget
from datetime import datetime, timedelta
dashboard_bp = Blueprint('dashboard', __name__)
@dashboard_bp.route('/summary', methods=['GET'])
@jwt_required()
def get_dashboard_summary():
    """Get dashboard summary data."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    use_resource_metrics = (request.args.get('use_resource_metrics', '') or '').strip().lower() in {'1', 'true', 'yes'}
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    # Resource counts
    total_vms = VirtualMachine.query.filter_by(
        organization_id=org_id,
    ).filter(VirtualMachine.status != 'terminated').count()
    running_vms = VirtualMachine.query.filter_by(
        organization_id=org_id,
        status='running'
    ).count()
    total_dbs = Database.query.filter_by(organization_id=org_id).count()
    running_dbs = Database.query.filter_by(
        organization_id=org_id,
        status=ResourceStatus.RUNNING
    ).count()
    # Security status
    active_threats = ThreatDetection.query.filter_by(
        organization_id=org_id,
        status='active'
    ).count()
    # Cost status
    today = datetime.now()
    month_start = today.replace(day=1)
    month_costs = CostRecord.query.filter(
        CostRecord.organization_id == org_id,
        CostRecord.date >= month_start.date()
    ).all()
    current_spend = sum(c.total_cost for c in month_costs)
    # Budget status
    budgets = Budget.query.filter_by(organization_id=org_id, is_active=True).all()
    
    # Security score: 100 - (critical*20 + high*10 + medium*5)
    threats = ThreatDetection.query.filter_by(organization_id=org_id).all()
    critical_count = sum(1 for t in threats if t.severity == ThreatSeverity.CRITICAL)
    high_count = sum(1 for t in threats if t.severity == ThreatSeverity.HIGH)
    medium_count = sum(1 for t in threats if t.severity == ThreatSeverity.MEDIUM)
    security_score = max(0, min(100, 100 - (critical_count * 20 + high_count * 10 + medium_count * 5)))
    
    # Compliance score: (passed / total) * 100, or 100 if no records
    try:
        from app.models.governance import ComplianceCheck
        compliance_checks = ComplianceCheck.query.join(
            ComplianceCheck.policy
        ).filter(
            Policy.organization_id == org_id
        ).all()
        if compliance_checks:
            passed_count = sum(1 for c in compliance_checks if c.status == 'passed')
            compliance_score = int((passed_count / len(compliance_checks)) * 100)
        else:
            compliance_score = 100
    except (ImportError, AttributeError):
        compliance_score = 100
    
    # Utilization score: avg CPU of running VMs, 100 if no VMs
    running_vms_for_util = VirtualMachine.query.filter_by(
        organization_id=org_id, status=ResourceStatus.RUNNING
    ).all()
    if running_vms_for_util:
        avg_cpu_util = sum(float(vm.cpu_utilization or 0) for vm in running_vms_for_util) / len(running_vms_for_util)
        utilization_score = min(100, avg_cpu_util)
    else:
        utilization_score = 100
    
    # Health score: (security * 0.4) + (compliance * 0.4) + (utilization * 0.2)
    health_score_calculated = int((security_score * 0.4) + (compliance_score * 0.4) + (utilization_score * 0.2))
    
    # Monthly spend
    monthly_spend = current_spend
    
    budget_status = []
    for b in budgets:
        status = b.to_dict()
        status['alert_level'] = 'normal'
        if status['percentage_used'] > 100:
            status['alert_level'] = 'critical'
        elif status['percentage_used'] > 80:
            status['alert_level'] = 'warning'
        budget_status.append(status)
    # Recent activity (last 24 hours)
    yesterday = today - timedelta(days=1)
    simulator_snapshot = current_app.simulator.get_dashboard_snapshot(org_id)

    if use_resource_metrics:
        # Read live utilization directly from the DB models
        running_vms_objs = VirtualMachine.query.filter_by(
            organization_id=org_id, status=ResourceStatus.RUNNING
        ).all()
        running_dbs_objs = Database.query.filter_by(
            organization_id=org_id, status=ResourceStatus.RUNNING
        ).all()
        all_running = running_vms_objs + running_dbs_objs
        avg_cpu = (
            sum(float(r.cpu_utilization or 0) for r in all_running) / len(all_running)
            if all_running else 0.0
        )
        avg_memory = (
            sum(float(r.memory_utilization or 0) for r in running_vms_objs) / len(running_vms_objs)
            if running_vms_objs else 0.0
        )
        total_vms = VirtualMachine.query.filter(
            VirtualMachine.organization_id == org_id,
            VirtualMachine.status != ResourceStatus.TERMINATED,
        ).count()
        running_vms = len(running_vms_objs)
        total_dbs = Database.query.filter(
            Database.organization_id == org_id,
            Database.status != ResourceStatus.TERMINATED,
        ).count()
        running_dbs = len(running_dbs_objs)
        simulator_snapshot = {
            **simulator_snapshot,
            'utilization_trend': [{
                'timestamp': datetime.utcnow().isoformat(),
                'cpu_avg': round(avg_cpu, 2),
                'memory_avg': round(avg_memory, 2),
            }],
        }

    return jsonify({
        'resources': {
            'vms': {
                'total': total_vms,
                'running': simulator_snapshot.get('running_vm_count', running_vms)
            },
            'databases': {'total': total_dbs, 'running': running_dbs}
        },
        'security': {
            'active_threats': active_threats,
            'status': 'critical' if active_threats > 0 else 'healthy',
            'security_score': security_score
        },
        'costs': {
            'current_month_spend': round(current_spend, 2),
            'monthly_spend': round(monthly_spend, 2),
            'budgets': budget_status
        },
        'cost_trend': simulator_snapshot.get('cost_trend', []),
        'utilization_trend': simulator_snapshot.get('utilization_trend', []),
        'recent_activity': simulator_snapshot.get('recent_activity', []),
        'security_score': security_score,
        'compliance_score': compliance_score,
        'utilization_score': utilization_score,
        'total_vms': total_vms,
        'running_vms': running_vms,
        'health_score': calculate_health_score(
            active_threats, running_vms, total_vms, current_spend, budgets
        ),
        'health_score_calculated': health_score_calculated
    }), 200
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
    items.sort(key=lambda x: x['cost'], reverse=True)
    return jsonify({'status': 'success', 'data': items}), 200


def calculate_health_score(threats, running_vms, total_vms, spend, budgets):
    """Calculate overall infrastructure health score."""
    score = 100
    # Deduct for threats
    score -= threats * 20
    # Deduct for low utilization
    if total_vms > 0:
        utilization_rate = running_vms / total_vms
        if utilization_rate < 0.3:
            score -= 10
    # Deduct for budget overruns
    for b in budgets:
        if b.get_current_spend() > b.amount:
            score -= 15
    return max(0, min(100, score))
