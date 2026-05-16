import calendar
from datetime import datetime, timedelta

import pandas as pd
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.models.cost import CostRecord, Budget, CostForecast
from app.models.organization import OrganizationMember

try:
    from app.ai_models.cost_forecaster import cost_forecaster
except ImportError:
    cost_forecaster = None

cost_bp = Blueprint('cost', __name__)


def _days_in_month(day):
    return calendar.monthrange(day.year, day.month)[1]


def _projected_month_end(total, day):
    if day.day <= 0:
        return 0.0
    return round((float(total or 0.0) / day.day) * _days_in_month(day), 2)


def _resolve_org_id():
    return request.args.get('organization_id', type=int) or request.args.get('org_id', type=int)


def _require_org_membership(user_id, org_id):
    if org_id is None:
        return None
    return OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()


def _budget_status_for_org(org_id):
    budgets = Budget.query.filter_by(organization_id=org_id, is_active=True).all()
    budget_status = []
    for budget in budgets:
        status = budget.to_dict()
        status['alert_level'] = 'normal'
        if status['percentage_used'] > 100:
            status['alert_level'] = 'critical'
        elif status['percentage_used'] > 80:
            status['alert_level'] = 'warning'
        budget_status.append(status)
    return budget_status


def _serialize_current_costs(org_id, today, total, by_service, by_day):
    budget_status = _budget_status_for_org(org_id)
    projected_month_end = _projected_month_end(total, today)

    return {
        'org_id': org_id,
        'organization_id': org_id,
        'current_month': {
            'total': round(total, 2),
            'by_service': {k: round(v, 2) for k, v in by_service.items()},
            'by_day': {k: round(v, 2) for k, v in sorted(by_day.items())},
            'projected_month_end': projected_month_end,
        },
        'costs': {
            'current_month_spend': round(total, 2),
            'monthly_spend': round(total, 2),
            'by_service': {k: round(v, 2) for k, v in by_service.items()},
            'by_day': {k: round(v, 2) for k, v in sorted(by_day.items())},
            'projected_month_end': projected_month_end,
            'budgets': budget_status,
            'budget_count': len(budget_status),
            'over_budget_count': sum(1 for item in budget_status if item.get('alert_level') == 'critical'),
        },
    }


def fallback_forecast(df, days_ahead):
    """Simple moving-average forecast for the P1 mid structure."""
    if df is None or df.empty or 'total_cost' not in df.columns:
        recent_average = 0.0
    else:
        recent_average = float(df['total_cost'].tail(min(len(df), 7)).mean())
        if pd.isna(recent_average):
            recent_average = 0.0
    start_date = datetime.now().date()
    forecast = []
    for offset in range(1, days_ahead + 1):
        predicted = round(recent_average, 2)
        forecast.append({
            'date': (start_date + timedelta(days=offset)).isoformat(),
            'predicted_cost': predicted,
            'confidence_lower': round(predicted * 0.9, 2),
            'confidence_upper': round(predicted * 1.1, 2),
        })
    return forecast


def fallback_wastage(vm_data):
    """Simple rightsizing hints when AI modules are not present."""
    recommendations = []
    for _, vm in vm_data.iterrows():
        if vm['status'] == 'running' and (
            vm['cpu_utilization_avg'] < 20 or vm.get('memory_utilization_avg', 100) < 30
        ):
            monthly = round(vm['hourly_rate'] * 730 * 0.3, 2)
            recommendations.append({
                'instance_id': vm['instance_id'],
                'recommendation': 'Consider downsizing or scheduling shutdowns',
                'potential_monthly_savings': monthly,
            })
    return recommendations
@cost_bp.route('/current', methods=['GET'])
@jwt_required()
def get_current_costs():
    """Get current cost breakdown."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    # Get current month costs
    today = datetime.utcnow()
    month_start = today.replace(day=1, hour=0, minute=0, second=0)
    costs = CostRecord.query.filter(
        CostRecord.organization_id == org_id,
        CostRecord.date >= month_start.date()
    ).all()
    total = sum(c.total_cost for c in costs)
    by_service = {}
    by_day = {}
    for c in costs:
        by_service[c.resource_type] = by_service.get(c.resource_type, 0) + c.total_cost
        by_day[str(c.date)] = by_day.get(str(c.date), 0) + c.total_cost
    return jsonify(_serialize_current_costs(org_id, today, total, by_service, by_day)), 200


@cost_bp.route('/forecast', methods=['GET'])
@jwt_required()
def get_forecast():
    """Get AI-powered cost forecast."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    days = request.args.get('days', 30, type=int)
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    # Get historical data
    from app.models.cost import CostRecord
    history = CostRecord.query.filter_by(organization_id=org_id).all()
    # Convert to DataFrame using actual cost records only
    df = pd.DataFrame([{
        'date': h.date,
        'total_cost': h.total_cost,
        'cpu_utilization_avg': h.cpu_avg,
        'memory_utilization_avg': h.memory_avg,
        'provisioned_resources': 0,
        'idle_resources': 0,
    } for h in history])
    # Generate forecast
    if cost_forecaster:
        forecast = cost_forecaster.forecast(df, days_ahead=days)
    else:
        forecast = fallback_forecast(df, days)
    # Save to database
    for f in forecast:
        cf = CostForecast(
            organization_id=org_id,
            forecast_date=datetime.strptime(f['date'], '%Y-%m-%d').date(),
            predicted_cost=f['predicted_cost'],
            confidence_lower=f['confidence_lower'],
            confidence_upper=f['confidence_upper']
        )
        db.session.add(cf)
    db.session.commit()
    return jsonify({
        'org_id': org_id,
        'organization_id': org_id,
        'forecast': forecast,
        'total_predicted': round(sum(f['predicted_cost'] for f in forecast), 2)
    }), 200


@cost_bp.route('/budgets', methods=['POST'])
@jwt_required()
def create_budget():
    """Create budget."""
    user_id = get_jwt_identity()
    data = request.get_json()
    org_id = data.get('organization_id') or data.get('org_id')
    member = _require_org_membership(user_id, org_id)
    if not member or member.role not in ['admin', 'owner']:
        return jsonify({'error': 'Insufficient permissions'}), 403
    budget = Budget(
        organization_id=org_id,
        name=data.get('name'),
        amount=data.get('amount'),
        period=data.get('period', 'monthly'),
        start_date=datetime.strptime(data.get('start_date'), '%Y-%m-%d').date(),
        alert_threshold_1=data.get('alert_threshold_1', 50),
        alert_threshold_2=data.get('alert_threshold_2', 80),
        alert_threshold_3=data.get('alert_threshold_3', 100),
        auto_shutdown_at_threshold=data.get('auto_shutdown_at_threshold', False)
    )
    db.session.add(budget)
    db.session.commit()
    return jsonify({
        'message': 'Budget created',
        'org_id': org_id,
        'organization_id': org_id,
        'budget': budget.to_dict()
    }), 201


@cost_bp.route('/budgets', methods=['GET'])
@jwt_required()
def get_budgets():
    """List budgets."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    budgets = Budget.query.filter_by(organization_id=org_id, is_active=True).all()
    return jsonify({
        'org_id': org_id,
        'organization_id': org_id,
        'budgets': [b.to_dict() for b in budgets]
    }), 200


@cost_bp.route('/optimization', methods=['GET'])
@jwt_required()
def get_optimization_recommendations():
    """Get cost optimization recommendations."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    # Get resource utilization data
    from app.models.resources import VirtualMachine, Database
    vms = VirtualMachine.query.filter_by(organization_id=org_id).all()
    dbs = Database.query.filter_by(organization_id=org_id).all()
    resource_rows = [{
        'resource_kind': 'vm',
        'instance_id': vm.instance_id,
        'instance_type': vm.instance_type,
        'status': vm.status.value if vm.status else 'unknown',
        'cpu_utilization_avg': vm.cpu_utilization,
        'memory_utilization_avg': vm.memory_utilization,
        'network_in_mbps': vm.network_in_mbps,
        'network_out_mbps': vm.network_out_mbps,
        'hourly_rate': vm.hourly_rate,
        'tags': [{'key': t.key, 'value': t.value} for t in vm.tags]
    } for vm in vms]
    resource_rows.extend([{
        'resource_kind': 'database',
        'instance_id': database.instance_id,
        'instance_type': database.instance_class,
        'status': database.status.value if database.status else 'unknown',
        'cpu_utilization_avg': database.cpu_utilization,
        'memory_utilization_avg': min(100.0, max(0.0, round(database.cpu_utilization * 1.35 + database.database_connections * 0.65, 2))),
        'network_in_mbps': max(0.0, round(database.database_connections * 0.75 + database.read_iops / 45, 2)),
        'network_out_mbps': max(0.0, round(database.database_connections * 0.55 + database.write_iops / 55, 2)),
        'hourly_rate': database.hourly_rate,
        'tags': [],
    } for database in dbs])
    vm_data = pd.DataFrame(resource_rows)
    insights = cost_forecaster.detect_wastage(vm_data) if cost_forecaster else fallback_wastage(vm_data)
    total_potential_savings = sum(i['potential_monthly_savings'] for i in insights)
    return jsonify({
        'org_id': org_id,
        'organization_id': org_id,
        'recommendations': insights,
        'total_potential_monthly_savings': round(total_potential_savings, 2),
        'recommendation_count': len(insights)
    }), 200
