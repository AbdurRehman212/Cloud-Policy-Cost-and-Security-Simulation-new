"""Module 10 — Remediation Agent: Chapter 6 UT-50..UT-54 plus execution, approval,
authorization, tenant isolation, duplicate prevention, failure handling and audit."""

import pytest

from app import db
from app.ai_models.remediation_agent import APPROVAL_REQUIRED, remediation_agent
from app.models.governance import AuditLog, Policy, PolicyStatus
from app.models.resources import Database, ResourceStatus, SecurityGroup, VirtualMachine
from app.models.security import RemediationAction, ThreatDetection, ThreatSeverity, ThreatType
from app.services.governance_engine import governance_engine
from tests.conftest import make_vm


# ── Chapter 6, Table 6.10 (agent decisions) ────────────────────────────────────

def test_ut50_ddos_high_confidence_isolates_and_scales_up():
    actions = remediation_agent.choose_actions({'type': 'ddos', 'confidence': 0.95}, {'resource_kind': 'vm', 'cpu_utilization': 80})
    assert 'isolate_resource' in actions and 'scale_up' in actions
    assert 'request_review' not in actions


def test_ut51_brute_force_blocks_ip_and_isolates():
    actions = remediation_agent.choose_actions({'type': 'brute_force', 'confidence': 0.9}, {'resource_kind': 'vm', 'cpu_utilization': 60})
    assert 'block_ip' in actions and 'isolate_resource' in actions


def test_ut52_public_unencrypted_database_needs_approval():
    result = remediation_agent.remediate(None, {'resource_kind': 'database', 'publicly_accessible': True, 'storage_encrypted': False, 'cpu_utilization': 50})
    actions = [r['action'] for r in result['results']]
    assert 'disable_public_access' in actions and 'enable_encryption' in actions
    assert result['requires_approval'] is True
    assert all(r['status'] == 'proposed' for r in result['results'])  # a proposal is not an execution


def test_ut53_idle_vm_stop_and_downsize_need_approval():
    result = remediation_agent.remediate({'type': 'unknown', 'confidence': 0.4}, {'resource_kind': 'vm', 'cpu_utilization': 5, 'status': 'running'})
    actions = [r['action'] for r in result['results']]
    assert 'stop_idle_resource' in actions and 'downsize_resource' in actions
    assert result['requires_approval'] is True


def test_ut54_unknown_low_confidence_threat_only_requests_review():
    assert remediation_agent.choose_actions({'type': 'unknown', 'confidence': 0.4}, None) == ['request_review']


def test_low_confidence_ddos_is_not_contained_automatically():
    actions = remediation_agent.choose_actions({'type': 'ddos', 'confidence': 0.5}, None)
    assert actions == ['request_review']


def test_every_configuration_change_requires_approval():
    assert 'request_review' not in APPROVAL_REQUIRED
    assert {'isolate_resource', 'block_ip', 'scale_up', 'stop_idle_resource'} <= APPROVAL_REQUIRED


# ── Workflow (UC10) ────────────────────────────────────────────────────────────

def _threat(org_id, kind=ThreatType.DDoS, confidence=0.95, resources=None, status='active'):
    threat = ThreatDetection(
        organization_id=org_id, threat_type=kind, severity=ThreatSeverity.HIGH, confidence_score=confidence,
        affected_resources=resources or [], attack_vectors={'source_ip': '198.51.100.201', 'simulation': True},
        model_version='simulation', status=status,
    )
    db.session.add(threat)
    db.session.commit()
    return threat


def _plan(client, headers, org, key, **extra):
    return client.post('/api/remediation/plan', json={'organization_id': org, 'issue_key': key, **extra}, headers=headers)


def _execute(client, headers, org, key, actions, approved=True, **extra):
    return client.post('/api/remediation/execute', json={
        'organization_id': org, 'issue_key': key, 'actions': actions, 'approved': approved, **extra}, headers=headers)


def test_issues_list_threats_violations_and_idle_resources(client, world):
    org = world['org_a']
    vm = make_vm(org, 'idle1', cpu_utilization=3.0)
    _threat(org, resources=[vm.instance_id])
    _threat(org, status='resolved')  # closed threats are not listed
    resp = client.get(f'/api/remediation/issues?organization_id={org}', headers=world['viewer'])
    assert resp.status_code == 200
    data = resp.get_json()['data']
    types = sorted(i['type'] for i in data['issues'])
    assert types == ['idle', 'threat']
    assert data['can_execute'] is False


def test_ddos_plan_has_explanations_consequences_and_preview(client, world):
    org = world['org_a']
    vm = make_vm(org, 'web1', cpu_utilization=85.0)
    threat = _threat(org, resources=[vm.instance_id])
    resp = _plan(client, world['viewer'], org, f'threat:{threat.id}')
    assert resp.status_code == 200
    plan = resp.get_json()['data']
    by = {a['action']: a for a in plan['actions']}
    assert set(by) == {'isolate_resource', 'scale_up'}
    assert by['scale_up']['preview']['instance_type'] == {'before': 't2.micro', 'after': 't2.medium'}
    assert all(a['reason'] and a['consequence'] and a['recovery'] for a in plan['actions'])
    assert plan['requires_approval'] is True
    # Planning changes nothing.
    assert db.session.get(VirtualMachine, vm.id).instance_type == 't2.micro'
    assert db.session.get(ThreatDetection, threat.id).status == 'active'


def test_execute_ddos_changes_state_resolves_threat_and_audits(client, world):
    org = world['org_a']
    vm = make_vm(org, 'web2', cpu_utilization=90.0)
    threat = _threat(org, resources=[vm.instance_id])
    resp = _execute(client, world['admin'], org, f'threat:{threat.id}', ['isolate_resource', 'scale_up'])
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()['data']
    assert data['issue_status'] == 'resolved'
    vm = db.session.get(VirtualMachine, vm.id)
    assert vm.instance_type == 't2.medium' and vm.vcpu == 2
    assert vm.cpu_utilization == pytest.approx(45.0)  # same load over twice the vCPUs
    assert [g.name for g in vm.security_groups] == ['remediation-quarantine']
    assert db.session.get(ThreatDetection, threat.id).status == 'resolved'
    rows = RemediationAction.query.filter_by(issue_key=f'threat:{threat.id}').all()
    assert {r.status for r in rows} == {'succeeded'} and all(r.details['verified'] for r in rows)
    actions = {a.action for a in AuditLog.query.filter_by(organization_id=org).all()}
    assert {'remediation_approved', 'remediation_executed'} <= actions


def test_brute_force_blocks_source_ip_on_original_groups_before_isolation(client, world):
    org = world['org_a']
    vm = make_vm(org, 'ssh1')
    group = SecurityGroup(org_id=org, name='web')
    db.session.add(group)
    db.session.flush()
    vm.security_groups = [group]
    db.session.commit()
    threat = _threat(org, kind=ThreatType.BRUTE_FORCE, confidence=0.9, resources=[vm.instance_id])
    resp = _execute(client, world['owner'], org, f'threat:{threat.id}', ['isolate_resource', 'block_ip'])
    assert resp.status_code == 200, resp.get_json()
    rules = db.session.get(SecurityGroup, group.id).rules
    assert any(r.source_cidr == '198.51.100.201/32' and r.action == 'deny' for r in rules)
    assert [g.name for g in db.session.get(VirtualMachine, vm.id).security_groups] == ['remediation-quarantine']


def test_approval_is_required_for_configuration_changes(client, world):
    org = world['org_a']
    vm = make_vm(org, 'web3')
    threat = _threat(org, resources=[vm.instance_id])
    resp = _execute(client, world['admin'], org, f'threat:{threat.id}', ['isolate_resource'], approved=False)
    assert resp.status_code == 400
    assert resp.get_json()['error']['code'] == 'approval_required'
    assert db.session.get(ThreatDetection, threat.id).status == 'active'
    assert RemediationAction.query.count() == 0


@pytest.mark.parametrize('role', ['viewer', 'member'])
def test_only_admins_and_owners_execute(client, world, role):
    org = world['org_a']
    vm = make_vm(org, f'web-{role}')
    threat = _threat(org, resources=[vm.instance_id])
    resp = _execute(client, world[role], org, f'threat:{threat.id}', ['isolate_resource'])
    assert resp.status_code == 403
    assert db.session.get(ThreatDetection, threat.id).status == 'active'
    assert AuditLog.query.filter_by(action='remediation_denied').count() == 1


def test_cross_tenant_issue_and_target_are_rejected(client, world):
    vm_b = make_vm(world['org_b'], 'b-vm')
    threat_b = _threat(world['org_b'], resources=[vm_b.instance_id])
    # Issue of org B addressed through org A → not found; org B itself → not a member.
    assert _plan(client, world['owner'], world['org_a'], f'threat:{threat_b.id}').status_code == 404
    assert _execute(client, world['owner'], world['org_b'], f'threat:{threat_b.id}', ['isolate_resource']).status_code == 403
    # A target resource of another tenant cannot be chosen.
    threat_a = _threat(world['org_a'])
    resp = _plan(client, world['owner'], world['org_a'], f'threat:{threat_a.id}', target_resource_id=vm_b.id)
    assert resp.status_code == 404


def test_duplicate_execution_is_refused(client, world):
    org = world['org_a']
    vm = make_vm(org, 'web4')
    threat = _threat(org, resources=[vm.instance_id])
    key = f'threat:{threat.id}'
    assert _execute(client, world['admin'], org, key, ['isolate_resource', 'scale_up']).status_code == 200
    again = _execute(client, world['admin'], org, key, ['isolate_resource', 'scale_up'])
    assert again.status_code == 409
    assert db.session.get(VirtualMachine, vm.id).instance_type == 't2.medium'  # not scaled twice
    assert _execute(client, world['admin'], org, key, ['scale_up', 'scale_up']).status_code == 400


def test_failed_action_rolls_back_everything_and_issue_stays_open(client, world):
    org = world['org_a']
    vm = make_vm(org, 'big', instance_type='t2.xlarge', vcpu=4, memory_gb=16, cpu_utilization=95.0)
    threat = _threat(org, resources=[vm.instance_id])
    # scale_up is not applicable on the largest type: refused before any change.
    resp = _execute(client, world['admin'], org, f'threat:{threat.id}', ['isolate_resource', 'scale_up'])
    assert resp.status_code == 409
    vm = db.session.get(VirtualMachine, vm.id)
    assert vm.security_groups == [] and vm.instance_type == 't2.xlarge'
    assert db.session.get(ThreatDetection, threat.id).status == 'active'


def test_failure_during_execution_is_rolled_back_and_recorded(client, world, monkeypatch):
    from app.services import remediation_service as svc
    org = world['org_a']
    vm = make_vm(org, 'web5')
    threat = _threat(org, resources=[vm.instance_id])
    real_apply = svc._apply

    def flaky(action, row, org_id, threat, params):
        if action == 'isolate_resource':
            raise svc.RemediationError('simulated failure', 422, 'action_failed')
        return real_apply(action, row, org_id, threat, params)

    monkeypatch.setattr(svc, '_apply', flaky)
    resp = _execute(client, world['admin'], org, f'threat:{threat.id}', ['isolate_resource', 'scale_up'])
    assert resp.status_code == 422
    assert db.session.get(VirtualMachine, vm.id).instance_type == 't2.micro'  # scale_up ran first, was rolled back
    assert db.session.get(ThreatDetection, threat.id).status == 'active'
    rows = RemediationAction.query.filter_by(issue_key=f'threat:{threat.id}').all()
    assert rows and {r.status for r in rows} == {'failed'}
    failure = AuditLog.query.filter_by(action='remediation_failed').one()
    assert failure.outcome == 'failure'


def test_low_confidence_threat_goes_to_review_without_changes(client, world):
    org = world['org_a']
    threat = _threat(org, kind=ThreatType.SUSPICIOUS_BEHAVIOR, confidence=0.4)
    plan = _plan(client, world['admin'], org, f'threat:{threat.id}').get_json()['data']
    assert [a['action'] for a in plan['actions']] == ['request_review']
    resp = _execute(client, world['admin'], org, f'threat:{threat.id}', ['request_review'], approved=False)
    assert resp.status_code == 200
    assert resp.get_json()['data']['issue_status'] == 'under_review'
    assert db.session.get(ThreatDetection, threat.id).status == 'under_review'


def test_public_unencrypted_database_violation_is_fixed_and_verified(client, world):
    org = world['org_a']
    database = Database(organization_id=org, name='orders', instance_id='db-orders', engine='PostgreSQL',
                        instance_class='db.t3.micro', status=ResourceStatus.RUNNING, publicly_accessible=True,
                        storage_encrypted=False, hourly_rate=0.025)
    db.session.add(database)
    policy = Policy(organization_id=org, name='Secure DBs', natural_language_rule='resource_type=database;requires_encryption=true;requires_public_block=true',
                    compiled_rule={'resource_type': 'database', 'requires_encryption': True, 'requires_public_block': True},
                    policy_type='security', severity='critical', status=PolicyStatus.ACTIVE, created_by=world['owner_id'])
    db.session.add(policy)
    db.session.commit()
    governance_engine.evaluate_org_policies(org)
    issues = client.get(f'/api/remediation/issues?organization_id={org}', headers=world['admin']).get_json()['data']['issues']
    violation = next(i for i in issues if i['type'] == 'violation')
    plan = _plan(client, world['admin'], org, violation['key']).get_json()['data']
    assert {a['action'] for a in plan['actions']} == {'enable_encryption', 'disable_public_access'}
    resp = _execute(client, world['admin'], org, violation['key'], ['enable_encryption', 'disable_public_access'])
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()['data']
    assert data['issue_status'] == 'resolved' and data['verification']['compliant'] is True
    database = db.session.get(Database, database.id)
    assert database.storage_encrypted is True and database.publicly_accessible is False
    # The refreshed governance state no longer lists the violation.
    assert governance_engine.get_latest_state(org)['violations'] == []


def test_partial_fix_of_violation_fails_verification_and_rolls_back(client, world):
    org = world['org_a']
    database = Database(organization_id=org, name='logs', instance_id='db-logs', engine='PostgreSQL',
                        instance_class='db.t3.micro', status=ResourceStatus.RUNNING, publicly_accessible=True,
                        storage_encrypted=False, hourly_rate=0.025)
    db.session.add(database)
    db.session.add(Policy(organization_id=org, name='Secure', natural_language_rule='x',
                          compiled_rule={'resource_type': 'database', 'requires_encryption': True, 'requires_public_block': True},
                          severity='high', status=PolicyStatus.ACTIVE, created_by=world['owner_id']))
    db.session.commit()
    governance_engine.evaluate_org_policies(org)
    key = next(i['key'] for i in client.get(f'/api/remediation/issues?organization_id={org}', headers=world['admin']).get_json()['data']['issues'] if i['type'] == 'violation')
    resp = _execute(client, world['admin'], org, key, ['enable_encryption'])
    assert resp.status_code == 422
    assert db.session.get(Database, database.id).storage_encrypted is False  # rolled back


def test_idle_vm_is_stopped_and_history_is_listed(client, world):
    org = world['org_a']
    vm = make_vm(org, 'idle2', instance_type='t2.medium', vcpu=2, memory_gb=4, cpu_utilization=4.0, hourly_rate=0.0464)
    key = f'idle:vm:{vm.id}'
    resp = _execute(client, world['owner'], org, key, ['downsize_resource', 'stop_idle_resource'])
    assert resp.status_code == 200, resp.get_json()
    vm = db.session.get(VirtualMachine, vm.id)
    assert vm.status == ResourceStatus.STOPPED and vm.instance_type == 't2.small' and vm.hourly_rate == 0.023
    hist = client.get(f'/api/remediation/history?organization_id={org}', headers=world['viewer']).get_json()['data']
    assert hist['total'] == 2 and {a['action_type'] for a in hist['actions']} == {'downsize_resource', 'stop_idle_resource'}
    assert client.get(f'/api/remediation/history?organization_id={org}', headers=world['other']).status_code == 403


def test_actions_not_recommended_cannot_be_injected(client, world):
    org = world['org_a']
    vm = make_vm(org, 'web6')
    threat = _threat(org, resources=[vm.instance_id])
    resp = _execute(client, world['admin'], org, f'threat:{threat.id}', ['stop_idle_resource'])
    assert resp.status_code == 400
    assert db.session.get(VirtualMachine, vm.id).status == ResourceStatus.RUNNING


def test_concurrent_execution_runs_once(app, world):
    """Two simultaneous executions of one issue: the row lock lets exactly one succeed."""
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('row-level locking needs PostgreSQL')
    import threading
    from app.services import remediation_service as svc
    org = world['org_a']
    vm = make_vm(org, 'race', cpu_utilization=90.0)
    threat = _threat(org, resources=[vm.instance_id])
    key, results = f'threat:{threat.id}', []
    barrier = threading.Barrier(2)

    def run():
        with app.app_context():
            barrier.wait()
            try:
                svc.execute(org, world['admin_id'], key, ['scale_up'], True)
                results.append('ok')
            except svc.RemediationError as exc:
                results.append(exc.code)
            finally:
                db.session.remove()

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    db.session.expire_all()
    assert sorted(results) == ['already_resolved', 'ok']
    assert db.session.get(VirtualMachine, vm.id).instance_type == 't2.medium'  # scaled exactly once
    assert RemediationAction.query.filter_by(issue_key=key, status='succeeded').count() == 1
