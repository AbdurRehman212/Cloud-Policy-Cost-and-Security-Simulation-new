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
    return [budget.to_dict() for budget in budgets]


def _require_admin(member):
    return bool(member) and member.role in ('admin', 'owner')


def _parse_budget_payload(data, existing=None):
    """Validate budget fields. Returns (fields, error_message)."""
    def value(key, current=None):
        return data[key] if key in data else current

    name = value('name', existing.name if existing else None)
    name = (name or '').strip() if isinstance(name, (str, type(None))) else ''
    if not name:
        return None, 'Budget name is required'

    try:
        amount = float(value('amount', existing.amount if existing else None))
    except (TypeError, ValueError):
        return None, 'Budget amount must be a number'
    if amount <= 0:
        return None, 'Budget amount must be greater than 0'

    period = value('period', existing.period if existing else 'monthly')
    if period not in ('monthly', 'quarterly', 'yearly'):
        return None, 'Period must be monthly, quarterly or yearly'

    raw_start = value('start_date', existing.start_date.isoformat() if existing else None)
    try:
        start_date = datetime.strptime(str(raw_start), '%Y-%m-%d').date()
    except ValueError:
        return None, 'start_date must be YYYY-MM-DD'

    try:
        thresholds = [
            float(value('alert_threshold_1', existing.alert_threshold_1 if existing else 50)),
            float(value('alert_threshold_2', existing.alert_threshold_2 if existing else 80)),
            float(value('alert_threshold_3', existing.alert_threshold_3 if existing else 100)),
        ]
    except (TypeError, ValueError):
        return None, 'Alert thresholds must be numbers'
    if not (0 < thresholds[0] <= thresholds[1] <= thresholds[2]):
        return None, 'Alert thresholds must be positive and in ascending order'

    return {
        'name': name,
        'amount': amount,
        'period': period,
        'start_date': start_date,
        'alert_threshold_1': thresholds[0],
        'alert_threshold_2': thresholds[1],
        'alert_threshold_3': thresholds[2],
        'auto_shutdown_at_threshold': bool(value(
            'auto_shutdown_at_threshold', existing.auto_shutdown_at_threshold if existing else False
        )),
    }, None


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
    """Cost forecast (linear trend). Always an estimate; `basis` states what it was fitted on."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    days = request.args.get('days', 30, type=int)
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    if days is None or not 1 <= days <= 90:
        return jsonify({'error': 'days must be between 1 and 90'}), 400

    history = CostRecord.query.filter_by(organization_id=org_id).all()
    df = pd.DataFrame([{
        'date': h.date,
        'total_cost': h.total_cost,
    } for h in history])

    basis = 'org_cost_records'
    if df.empty:
        reference = cost_forecaster.load_historical_frame() if cost_forecaster else pd.DataFrame()
        if reference is not None and not reference.empty:
            df, basis = reference, 'reference_dataset'
        else:
            basis = 'no_data'

    if cost_forecaster:
        forecast = cost_forecaster.forecast(df, days_ahead=days)
    else:
        forecast = fallback_forecast(df, days)
    history_days = int(pd.to_datetime(df['date']).dt.date.nunique()) if not df.empty else 0

    if basis == 'org_cost_records':
        # Replace (not accumulate) stored future forecast rows for this org.
        CostForecast.query.filter(
            CostForecast.organization_id == org_id,
            CostForecast.forecast_date >= datetime.utcnow().date(),
        ).delete(synchronize_session=False)
        for f in forecast:
            db.session.add(CostForecast(
                organization_id=org_id,
                forecast_date=datetime.strptime(f['date'], '%Y-%m-%d').date(),
                predicted_cost=f['predicted_cost'],
                confidence_lower=f['confidence_lower'],
                confidence_upper=f['confidence_upper'],
                model_version='linear-trend-v1',
            ))
        db.session.commit()

    notes = {
        'reference_dataset': 'No cost records for this organization yet; forecast is fitted on the bundled reference dataset, not on your simulated spend.',
        'no_data': 'No cost data available; forecast is zero.',
    }
    if basis == 'org_cost_records' and history_days < 7:
        notes[basis] = f'Only {history_days} day(s) of cost history; treat this forecast as low confidence.'
    return jsonify({
        'org_id': org_id,
        'organization_id': org_id,
        'forecast': forecast,
        'total_predicted': round(sum(f['predicted_cost'] for f in forecast), 2),
        'is_estimate': True,
        'basis': basis,
        'history_days': history_days,
        'method': 'Linear regression on daily total cost; band = +/-1.5 x residual std',
        'note': notes.get(basis),
    }), 200


@cost_bp.route('/summary', methods=['GET'])
@jwt_required()
def get_cost_summary():
    """Organization cost trend and per-resource totals from persisted simulator cost records."""
    user_id = get_jwt_identity()
    org_id = _resolve_org_id()
    days = request.args.get('days', 30, type=int)
    if not _require_org_membership(user_id, org_id):
        return jsonify({'error': 'Access denied'}), 403
    if days is None or not 1 <= days <= 365:
        return jsonify({'error': 'days must be between 1 and 365'}), 400

    today = datetime.utcnow().date()
    start = today - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    records = CostRecord.query.filter(
        CostRecord.organization_id == org_id,
        CostRecord.date >= prev_start,
        CostRecord.date <= today,
    ).all()

    current = [r for r in records if r.date >= start]
    previous_total = sum(r.total_cost or 0.0 for r in records if r.date < start)
    total = sum(r.total_cost or 0.0 for r in current)

    by_day = {(start + timedelta(days=i)).isoformat(): 0.0 for i in range(days)}
    per_resource = {}
    for r in current:
        by_day[r.date.isoformat()] += r.total_cost or 0.0
        entry = per_resource.setdefault((r.resource_id, r.resource_type), {
            'resource_id': r.resource_id, 'resource_type': r.resource_type,
            'compute_cost': 0.0, 'storage_cost': 0.0, 'network_cost': 0.0, 'total_cost': 0.0,
        })
        entry['compute_cost'] += r.compute_cost or 0.0
        entry['storage_cost'] += r.storage_cost or 0.0
        entry['network_cost'] += r.network_cost or 0.0
        entry['total_cost'] += r.total_cost or 0.0

    from app.models.resources import Database, VirtualMachine
    names = {vm.instance_id: vm.name for vm in VirtualMachine.query.filter_by(organization_id=org_id)}
    names.update({db_.instance_id: db_.name for db_ in Database.query.filter_by(organization_id=org_id)})
    resources = sorted(per_resource.values(), key=lambda e: e['total_cost'], reverse=True)
    for entry in resources:
        entry['name'] = names.get(entry['resource_id'])
        for key in ('compute_cost', 'storage_cost', 'network_cost', 'total_cost'):
            entry[key] = round(entry[key], 4)

    # total, trend and by_resource all derive from CostRecord and share 4-decimal precision.
    change_pct = round((total - previous_total) / previous_total * 100, 2) if previous_total > 0 else None
    return jsonify({
        'org_id': org_id,
        'organization_id': org_id,
        'source': 'simulated cost records',
        'days': days,
        'start_date': start.isoformat(),
        'end_date': today.isoformat(),
        'total': round(total, 4),
        'previous_period_total': round(previous_total, 4),
        'change_pct': change_pct,
        'trend': [{'date': d, 'total_cost': round(v, 4)} for d, v in by_day.items()],
        'by_resource': resources,
    }), 200


@cost_bp.route('/budgets', methods=['POST'])
@jwt_required()
def create_budget():
    """Create budget."""
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    org_id = data.get('organization_id') or data.get('org_id')
    if not _require_admin(_require_org_membership(user_id, org_id)):
        return jsonify({'error': 'Insufficient permissions'}), 403
    fields, error = _parse_budget_payload(data)
    if error:
        return jsonify({'error': error}), 400
    budget = Budget(organization_id=org_id, **fields)
    db.session.add(budget)
    db.session.commit()
    return jsonify({
        'message': 'Budget created',
        'org_id': org_id,
        'organization_id': org_id,
        'budget': budget.to_dict()
    }), 201


@cost_bp.route('/budgets/<int:budget_id>', methods=['PUT'])
@jwt_required()
def update_budget(budget_id):
    user_id = get_jwt_identity()
    budget = Budget.query.filter_by(id=budget_id, is_active=True).first_or_404()
    if not _require_admin(_require_org_membership(user_id, budget.organization_id)):
        return jsonify({'error': 'Insufficient permissions'}), 403
    fields, error = _parse_budget_payload(request.get_json(silent=True) or {}, existing=budget)
    if error:
        return jsonify({'error': error}), 400
    for key, val in fields.items():
        setattr(budget, key, val)
    db.session.commit()
    return jsonify({'message': 'Budget updated', 'budget': budget.to_dict()}), 200


@cost_bp.route('/budgets/<int:budget_id>', methods=['DELETE'])
@jwt_required()
def delete_budget(budget_id):
    user_id = get_jwt_identity()
    budget = Budget.query.filter_by(id=budget_id, is_active=True).first_or_404()
    if not _require_admin(_require_org_membership(user_id, budget.organization_id)):
        return jsonify({'error': 'Insufficient permissions'}), 403
    budget.is_active = False
    db.session.commit()
    return jsonify({'message': 'Budget deleted'}), 200


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
        'is_estimate': True,
        'rules': 'IDLE: CPU < 10% (saves 100% of monthly cost). UNDERUTILIZED: CPU < 30% and memory < 40% (saves 50%). Running resources only.',
        'total_potential_monthly_savings': round(total_potential_savings, 2),
        'recommendation_count': len(insights)
    }), 200
