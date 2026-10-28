from datetime import date, timedelta

from app import db
from app.models.cost import CostForecast, CostRecord
from app.models.resources import ResourceStatus
from tests.conftest import make_vm

C = '/api/cost'


def add_cost(org_id, day, amount, resource_id='i-a', resource_type='vm'):
    db.session.add(CostRecord(
        organization_id=org_id, resource_id=resource_id, resource_type=resource_type, date=day, hour=0,
        compute_cost=amount, storage_cost=0.0, network_cost=0.0, total_cost=amount,
    ))
    db.session.commit()


def budget_body(world, **over):
    body = {'organization_id': world['org_a'], 'name': 'Monthly', 'amount': 100,
            'start_date': date.today().replace(day=1).isoformat()}
    body.update(over)
    return body


def test_budget_validation_and_crud(client, world):  # TC-M8-02..05
    r = client.post(f'{C}/budgets', json=budget_body(world), headers=world['admin'])
    assert r.status_code == 201
    bid = r.get_json()['budget']['id']

    for bad in ({'name': ''}, {'amount': -5}, {'amount': 'abc'}, {'start_date': 'nope'}, {'period': 'weekly'},
                {'alert_threshold_1': 90, 'alert_threshold_2': 80}):
        assert client.post(f'{C}/budgets', json=budget_body(world, **bad), headers=world['admin']).status_code == 400, bad

    r = client.put(f'{C}/budgets/{bid}', json={'amount': 250, 'name': 'Renamed'}, headers=world['admin'])
    assert r.status_code == 200 and r.get_json()['budget']['amount'] == 250.0
    assert client.put(f'{C}/budgets/{bid}', json={'amount': 0}, headers=world['admin']).status_code == 400

    assert client.delete(f'{C}/budgets/{bid}', headers=world['admin']).status_code == 200
    listing = client.get(f"{C}/budgets?organization_id={world['org_a']}", headers=world['viewer']).get_json()
    assert listing['budgets'] == []


def test_budget_rbac_and_isolation(client, world):
    assert client.post(f'{C}/budgets', json=budget_body(world), headers=world['viewer']).status_code == 403
    assert client.post(f'{C}/budgets', json=budget_body(world), headers=world['other']).status_code == 403
    bid = client.post(f'{C}/budgets', json=budget_body(world), headers=world['owner']).get_json()['budget']['id']
    assert client.put(f'{C}/budgets/{bid}', json={'amount': 1}, headers=world['other']).status_code == 403
    assert client.delete(f'{C}/budgets/{bid}', headers=world['viewer']).status_code == 403
    for path in ('current', 'forecast', 'budgets', 'optimization', 'summary'):
        assert client.get(f"{C}/{path}?organization_id={world['org_a']}", headers=world['other']).status_code == 403, path


def test_budget_alert_level_uses_own_thresholds(client, world):
    add_cost(world['org_a'], date.today(), 60.0)
    r = client.post(f'{C}/budgets', json=budget_body(world, amount=100, alert_threshold_2=55, alert_threshold_3=90),
                    headers=world['admin'])
    assert r.get_json()['budget']['alert_level'] == 'warning'  # 60% >= 55% but < 90%
    status = client.get(f"{C}/current?organization_id={world['org_a']}", headers=world['viewer']).get_json()
    assert status['costs']['budgets'][0]['alert_level'] == 'warning'


def test_summary_trend_and_per_resource(client, world):  # TC-M8-01, TC-M8-06
    today = date.today()
    add_cost(world['org_a'], today, 2.0, 'i-a')
    add_cost(world['org_a'], today - timedelta(days=1), 1.0, 'i-a')
    add_cost(world['org_a'], today, 5.0, 'i-b', 'database')
    add_cost(world['org_b'], today, 999.0, 'i-x')  # other tenant must not leak
    d = client.get(f"{C}/summary?organization_id={world['org_a']}&days=7", headers=world['viewer']).get_json()
    assert d['total'] == 8.0 and len(d['trend']) == 7
    assert d['trend'][-1]['total_cost'] == 7.0
    assert [r['resource_id'] for r in d['by_resource']] == ['i-b', 'i-a']
    assert client.get(f"{C}/summary?organization_id={world['org_a']}&days=0", headers=world['viewer']).status_code == 400


def test_wastage_rules_are_explainable(client, world):  # TC-M8-07..08
    make_vm(world['org_a'], 'idle', cpu_utilization=4.0, memory_utilization=80.0, hourly_rate=0.10)
    make_vm(world['org_a'], 'under', cpu_utilization=25.0, memory_utilization=30.0, hourly_rate=0.10)
    make_vm(world['org_a'], 'busy', cpu_utilization=60.0, memory_utilization=70.0, hourly_rate=0.10)
    make_vm(world['org_a'], 'stopped', cpu_utilization=1.0, memory_utilization=1.0, hourly_rate=0.10,
            status=ResourceStatus.STOPPED)
    d = client.get(f"{C}/optimization?organization_id={world['org_a']}", headers=world['viewer']).get_json()
    found = {r['instance_id']: r for r in d['recommendations']}
    assert set(found) == {'i-idle', 'i-under'}  # healthy and non-running resources are not flagged
    assert found['i-idle']['rule'] == 'IDLE' and found['i-idle']['potential_monthly_savings'] == 73.0
    assert found['i-under']['rule'] == 'UNDERUTILIZED' and found['i-under']['potential_monthly_savings'] == 36.5
    assert 'CPU' in found['i-idle']['reason'] and found['i-idle']['estimated'] is True
    assert d['is_estimate'] is True and d['total_potential_monthly_savings'] == 109.5


def test_no_waste_when_all_healthy(client, world):
    make_vm(world['org_a'], 'a', cpu_utilization=55.0, memory_utilization=60.0)
    make_vm(world['org_a'], 'b', cpu_utilization=65.0, memory_utilization=70.0)
    d = client.get(f"{C}/optimization?organization_id={world['org_a']}", headers=world['viewer']).get_json()
    assert d['recommendation_count'] == 0


def test_forecast_is_labelled_and_not_duplicated(client, world, app):  # TC-M8-09..10
    today = date.today()
    for i in range(10):
        add_cost(world['org_a'], today - timedelta(days=10 - i), 10.0 + i)
    url = f"{C}/forecast?organization_id={world['org_a']}&days=5"
    d = client.get(url, headers=world['viewer']).get_json()
    assert d['basis'] == 'org_cost_records' and d['is_estimate'] is True and d['history_days'] == 10
    assert len(d['forecast']) == 5 and d['forecast'][0]['predicted_cost'] > 19.0  # upward trend continues
    client.get(url, headers=world['viewer'])
    assert CostForecast.query.filter_by(organization_id=world['org_a']).count() == 5  # replaced, not appended
    assert client.get(f"{C}/forecast?organization_id={world['org_a']}&days=500", headers=world['viewer']).status_code == 400


def test_forecast_without_org_data_is_labelled_not_persisted(client, world):
    d = client.get(f"{C}/forecast?organization_id={world['org_a']}&days=3", headers=world['viewer']).get_json()
    assert d['basis'] in ('reference_dataset', 'no_data') and d['note']
    assert CostForecast.query.filter_by(organization_id=world['org_a']).count() == 0
