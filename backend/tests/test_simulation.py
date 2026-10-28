import pytest

from app import db
from app.models.organization import Organization
from app.models.resources import ResourceStatus, VirtualMachine
from app.services import control_plane
from tests.conftest import make_vm


def test_autoscaler_respects_organization_quota(world):  # scaling safeguard
    org = Organization.query.get(world['org_a'])
    org.max_resources = 2
    db.session.commit()
    make_vm(org.id, 'a')
    control_plane._create_autoscale_vm(org.id, 't2.micro', 100, 'steady')  # 2nd resource: allowed
    with pytest.raises(Exception, match='maximum allowed limit of 2'):
        control_plane._create_autoscale_vm(org.id, 't2.micro', 100, 'steady')


def test_terminated_autoscale_vm_is_excluded_and_names_stay_unique(world):
    org = world['org_a']
    first = control_plane._create_autoscale_vm(org, 't2.micro', 100, 'steady')
    assert control_plane._terminate_autoscale_vm(org) is True
    assert VirtualMachine.query.get(first.id).status == ResourceStatus.TERMINATED
    second = control_plane._create_autoscale_vm(org, 't2.micro', 100, 'steady')
    assert second.instance_id != first.instance_id  # sequence counts terminated VMs too
    assert control_plane._terminate_autoscale_vm(world['org_b']) is False  # no cross-tenant termination


def test_zero_data_endpoints_report_zero_not_placeholders(client, world):
    org = world['org_a']
    cost = client.get(f'/api/cost/summary?organization_id={org}', headers=world['viewer']).get_json()
    assert cost['total'] == 0 and cost['by_resource'] == [] and all(p['total_cost'] == 0 for p in cost['trend'])
    assert client.get(f'/api/cost/optimization?organization_id={org}', headers=world['viewer']).get_json()['recommendations'] == []
    for kind in ('cost', 'security', 'governance'):
        csv = client.get(f'/api/reports/{kind}.csv?organization_id={org}', headers=world['viewer'])
        assert csv.status_code == 200 and len(csv.get_data(as_text=True).strip().splitlines()) == 1  # header only
    assert client.get(f'/api/reports/summary.pdf?organization_id={org}', headers=world['viewer']).data[:4] == b'%PDF'


def test_terminated_vms_are_ignored_by_compliance_and_optimization(client, world):
    org = world['org_a']
    make_vm(org, 'gone', status=ResourceStatus.TERMINATED, cpu_utilization=1.0, memory_utilization=1.0, hourly_rate=0.5)
    make_vm(org, 'live', cpu_utilization=50.0, memory_utilization=50.0)
    assert client.get(f'/api/cost/optimization?organization_id={org}', headers=world['viewer']).get_json()['recommendations'] == []
    client.post('/api/governance/policies', json={'organization_id': org, 'name': 'n', 'policy_rule': 'VM names must start with web-'}, headers=world['admin'])
    client.post('/api/governance/compliance/check', json={'organization_id': org}, headers=world['admin'])
    flagged = [v['resource_id'] for v in client.get(f'/api/governance/violations?organization_id={org}', headers=world['viewer']).get_json()['data']['violations']]
    assert 'i-gone' not in flagged and 'i-live' in flagged
