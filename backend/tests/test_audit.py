"""Module 11 — Audit Trail: centralized recording, cross-module events, immutability,
tenant isolation, least privilege, secret redaction, filters and pagination.
Also covers login throttling and token revocation (ENGINEERING_QUALITY_REPORT S10/S11)."""

from datetime import datetime, timedelta

import pytest

from app import db
from app.models.governance import AuditLog
from app.models.user import User
from app.services.audit_service import category_for, record_audit, sanitize
from tests.conftest import make_vm


def _events(client, headers, org, **params):
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    resp = client.get(f'/api/audit/events?organization_id={org}&{query}', headers=headers)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['data']


def _register_and_login(client, email='learner@t.io', password='Str0ng!Passw0rd'):
    resp = client.post('/api/auth/register', json={'email': email, 'password': password,
                                                   'first_name': 'Lea', 'last_name': 'Rner'})
    assert resp.status_code == 201, resp.get_json()
    login = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert login.status_code == 200, login.get_json()
    return login.get_json()['data']


def test_categories_are_assigned():
    assert category_for('login_failed') == 'auth'
    assert category_for('vm_created') == 'resource'
    assert category_for('remediation_executed') == 'remediation'
    assert category_for('budget_created') == 'cost'
    assert category_for('member_role_changed') == 'organization'
    assert category_for('policy_evaluated') == 'governance'


def test_secrets_are_redacted_recursively():
    clean = sanitize({'password': 'p', 'nested': {'api_key': 'k', 'refresh_token': 't', 'ok': 1}, 'list': [{'secret': 's'}]})
    assert clean == {'password': '[redacted]', 'nested': {'api_key': '[redacted]', 'refresh_token': '[redacted]', 'ok': 1},
                     'list': [{'secret': '[redacted]'}]}


def test_audit_rows_cannot_be_updated_or_deleted(app, world):
    entry = record_audit('vm_created', org_id=world['org_a'], user_id=world['owner_id'], commit=True)
    entry.action = 'tampered'
    with pytest.raises(ValueError):
        db.session.commit()
    db.session.rollback()
    with pytest.raises(ValueError):
        db.session.delete(db.session.get(AuditLog, entry.id))
        db.session.commit()
    db.session.rollback()
    assert db.session.get(AuditLog, entry.id).action == 'vm_created'


def test_no_write_endpoints_exist(client, world):
    entry = record_audit('vm_created', org_id=world['org_a'], user_id=world['owner_id'], commit=True)
    for method in ('put', 'delete', 'patch'):
        resp = getattr(client, method)(f'/api/audit/events/{entry.id}?organization_id={world["org_a"]}', headers=world['owner'])
        assert resp.status_code == 405
    assert client.post('/api/audit/events', json={}, headers=world['owner']).status_code == 405


def test_tenant_isolation_and_least_privilege(client, world):
    record_audit('vm_created', org_id=world['org_a'], user_id=world['owner_id'], commit=True)
    record_audit('vm_created', org_id=world['org_a'], user_id=world['member_id'], commit=True)
    record_audit('vm_created', org_id=world['org_b'], user_id=world['other_id'], commit=True)
    assert _events(client, world['admin'], world['org_a'])['total'] == 2        # whole org trail
    member_view = _events(client, world['member'], world['org_a'])
    assert member_view['total'] == 1 and member_view['scope'] == 'own_actions'  # only own actions
    assert client.get(f'/api/audit/events?organization_id={world["org_b"]}', headers=world['owner']).status_code == 403
    other_id = AuditLog.query.filter_by(organization_id=world['org_b']).first().id
    assert client.get(f'/api/audit/events/{other_id}?organization_id={world["org_a"]}', headers=world['owner']).status_code == 404


def test_filters_search_dates_and_pagination(client, world):
    org = world['org_a']
    for i in range(30):
        record_audit('vm_created', org_id=org, user_id=world['owner_id'], resource_type='vm', resource_id=f'i-{i}')
    record_audit('remediation_failed', org_id=org, user_id=world['owner_id'], outcome='failure', resource_id='threat:9')
    db.session.commit()
    page1 = _events(client, world['owner'], org, per_page=10, page=1)
    page4 = _events(client, world['owner'], org, per_page=10, page=4)
    assert page1['total'] == 31 and page1['pages'] == 4 and len(page4['events']) == 1
    assert page1['events'][0]['action'] == 'remediation_failed'  # newest first
    assert _events(client, world['owner'], org, category='remediation')['total'] == 1
    assert _events(client, world['owner'], org, outcome='failure')['total'] == 1
    assert _events(client, world['owner'], org, q='i-2')['total'] == 1 + 10  # i-2, i-20..i-29
    today = datetime.utcnow().date()
    assert _events(client, world['owner'], org, date_from=today.isoformat(), date_to=today.isoformat())['total'] == 31
    assert _events(client, world['owner'], org, date_to=(today - timedelta(days=1)).isoformat())['total'] == 0
    bad = client.get(f'/api/audit/events?organization_id={org}&date_from=yesterday', headers=world['owner'])
    assert bad.status_code == 400
    assert client.get(f'/api/audit/events?organization_id={org}&category=nope', headers=world['owner']).status_code == 400


def test_cross_module_events_are_recorded(client, world):
    org = world['org_a']
    # M2 organization + membership
    client.put(f'/api/org/{org}', json={'description': 'demo'}, headers=world['owner'])
    client.post(f'/api/org/{org}/invite', json={'email': 'new@t.io', 'role': 'viewer'}, headers=world['owner'])
    # M8 budget
    client.post('/api/cost/budgets', json={'organization_id': org, 'name': 'Monthly', 'amount': 100,
                                           'period': 'monthly', 'start_date': '2026-11-01'}, headers=world['owner'])
    # M7 policy
    client.post('/api/governance/policies', json={'organization_id': org, 'name': 'Tags',
                                                  'policy_rule': 'resource_type=vm;required_tags=env'}, headers=world['owner'])
    # M6 security
    client.post('/api/security/simulate-attack', json={'organization_id': org, 'attack_type': 'ddos'}, headers=world['owner'])
    # M9 report
    assert client.get(f'/api/reports/security.csv?organization_id={org}', headers=world['owner']).status_code == 200
    actions = {e['action'] for e in _events(client, world['owner'], org, per_page=100)['events']}
    assert {'org_updated', 'member_invited', 'budget_created', 'attack_simulated', 'report_generated'} <= actions
    assert any(a.startswith('policy') for a in actions)
    categories = {e['category'] for e in _events(client, world['owner'], org, per_page=100)['events']}
    assert {'organization', 'cost', 'security', 'report', 'governance'} <= categories


def test_auth_events_have_no_secrets_and_appear_in_my_activity(client, app):
    tokens = _register_and_login(client)
    headers = {'Authorization': f'Bearer {tokens["access_token"]}'}
    client.post('/api/auth/change-password', json={'current_password': 'wrong', 'new_password': 'N3w!Passw0rdX'}, headers=headers)
    mine = client.get('/api/audit/me', headers=headers).get_json()['data']
    actions = [e['action'] for e in mine['events']]
    assert {'register_succeeded', 'login_succeeded', 'password_change_failed'} <= set(actions)
    blob = str([AuditLog.query.all()[i].new_values for i in range(AuditLog.query.count())])
    assert 'Str0ng!Passw0rd' not in blob and tokens['access_token'] not in blob


def test_login_is_throttled_after_repeated_failures(client, app):
    _register_and_login(client, email='victim@t.io')
    for _ in range(5):
        assert client.post('/api/auth/login', json={'email': 'victim@t.io', 'password': 'bad'}).status_code == 401
    blocked = client.post('/api/auth/login', json={'email': 'victim@t.io', 'password': 'Str0ng!Passw0rd'})
    assert blocked.status_code == 429
    user = User.query.filter_by(email='victim@t.io').one()
    assert AuditLog.query.filter_by(user_id=user.id, action='login_failed', outcome='failure').count() == 5
    assert AuditLog.query.filter_by(user_id=user.id, action='login_blocked').count() == 1


def test_logout_revokes_access_and_refresh_tokens(client, app):
    tokens = _register_and_login(client, email='leaver@t.io')
    access = {'Authorization': f'Bearer {tokens["access_token"]}'}
    assert client.get('/api/settings', headers=access).status_code == 200
    resp = client.delete('/api/auth/logout', json={'access_token': tokens['access_token']},
                         headers={'Authorization': f'Bearer {tokens["refresh_token"]}'})
    assert resp.status_code == 200
    assert client.get('/api/settings', headers=access).status_code == 401
    assert client.post('/api/auth/refresh', headers={'Authorization': f'Bearer {tokens["refresh_token"]}'}).status_code == 401


def test_resource_lifecycle_and_remediation_appear_in_timeline(client, world):
    org = world['org_a']
    vm = make_vm(org, 'idle-audit', cpu_utilization=2.0)
    client.post(f'/api/remediation/execute', json={'organization_id': org, 'issue_key': f'idle:vm:{vm.id}',
                                                   'actions': ['stop_idle_resource'], 'approved': True}, headers=world['owner'])
    events = _events(client, world['owner'], org, category='remediation')['events']
    assert [e['action'] for e in events][:2] == ['remediation_executed', 'remediation_approved']
    detail = client.get(f'/api/audit/events/{events[0]["id"]}?organization_id={org}', headers=world['owner']).get_json()['data']
    assert detail['changes']['new']['issue_status'] == 'resolved'
    assert detail['actor']['id'] == world['owner_id']
