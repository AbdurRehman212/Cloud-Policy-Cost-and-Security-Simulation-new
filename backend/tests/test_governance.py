from app.models.resources import ResourceStatus
from tests.conftest import make_vm

G = '/api/governance'


def _create(client, world, who='admin', org='org_a', **over):
    body = {'organization_id': world[org], 'name': 'P', 'policy_rule': 'resource_type=vm; max_cpu=70; severity=high'}
    body.update(over)
    return client.post(f'{G}/policies', json=body, headers=world[who])


def _check(client, world, who='admin'):
    return client.post(f'{G}/compliance/check', json={'organization_id': world['org_a']}, headers=world[who])


def test_policy_crud_and_audit(client, world):  # TC-M7-01..04, TC-M7-10
    r = _create(client, world)
    assert r.status_code == 201
    pid = r.get_json()['data']['policy']['id']
    r = client.put(f'{G}/policies/{pid}', json={'name': 'Renamed', 'status': 'disabled'}, headers=world['admin'])
    assert r.get_json()['data']['policy']['status'] == 'disabled'
    assert client.put(f'{G}/policies/{pid}', json={'status': 'bogus'}, headers=world['admin']).status_code == 400
    assert _create(client, world, name='  ').status_code == 400
    assert _create(client, world, policy_rule='gibberish words').status_code == 400
    assert client.delete(f'{G}/policies/{pid}', headers=world['admin']).status_code == 200
    logs = client.get(f"{G}/audit-logs?organization_id={world['org_a']}", headers=world['viewer']).get_json()['data']['logs']
    assert [l['action'] for l in logs][:3] == ['policy_deleted', 'policy_updated', 'policy_created']


def test_validation_and_violations(client, world, app):  # TC-M7-05..07
    make_vm(world['org_a'], 'hot', cpu_utilization=90.0)
    make_vm(world['org_a'], 'cool', cpu_utilization=10.0)
    make_vm(world['org_a'], 'gone', cpu_utilization=99.0, status=ResourceStatus.TERMINATED)
    _create(client, world)
    result = _check(client, world).get_json()['data']
    assert result['resources_evaluated'] == 2  # terminated VM is not evaluated
    assert result['violations_found'] == 1
    v = client.get(f"{G}/violations?organization_id={world['org_a']}", headers=world['viewer']).get_json()['data']
    assert v['total'] == 1 and v['violations'][0]['resource_id'] == 'i-hot'
    assert 'CPU utilization exceeds 70.0%' in v['violations'][0]['violations']
    none = client.get(f"{G}/violations?organization_id={world['org_a']}&severity=low", headers=world['viewer'])
    assert none.get_json()['data']['total'] == 0


def test_weighted_score_is_explainable(client, world):  # TC-M7-08..09
    make_vm(world['org_a'], 'hot', cpu_utilization=90.0)
    make_vm(world['org_a'], 'cool', cpu_utilization=10.0)
    _create(client, world, name='hi', policy_rule='resource_type=vm; max_cpu=70; severity=high')       # w=3, 1/2 pass
    _create(client, world, name='lo', policy_rule='resource_type=vm; max_cpu=95; severity=low')        # w=1, 2/2 pass
    _check(client, world)
    s = client.get(f"{G}/score?organization_id={world['org_a']}", headers=world['viewer']).get_json()['data']
    assert s['evaluated'] is True
    assert s['score'] == 62.5  # (3*1 + 1*2) / (3*2 + 1*2) = 5/8
    by_name = {b['policy_name']: b for b in s['breakdown']}
    assert by_name['hi']['weight'] == 3 and by_name['hi']['penalty_points'] == 3
    assert 'weight' in s['formula']


def test_score_before_any_run(client, world):
    s = client.get(f"{G}/score?organization_id={world['org_a']}", headers=world['viewer']).get_json()['data']
    assert s['evaluated'] is False and s['score'] == 100.0


def test_rbac_and_isolation(client, world):  # TC-M7-11..12
    assert _create(client, world, who='viewer').status_code == 403
    assert _create(client, world, who='other').status_code == 403
    pid = _create(client, world).get_json()['data']['policy']['id']
    assert client.put(f'{G}/policies/{pid}', json={'name': 'x'}, headers=world['other']).status_code == 403
    assert client.delete(f'{G}/policies/{pid}', headers=world['viewer']).status_code == 403
    for path in ('policies', 'violations', 'score', 'audit-logs', 'compliance/checks'):
        r = client.get(f"{G}/{path}?organization_id={world['org_a']}", headers=world['other'])
        assert r.status_code == 403, path


def test_unknown_rule_keys_are_rejected_not_silently_ignored():
    from app.ai_models.policy_engine import policy_engine
    result = policy_engine.parse_policy('resource_type=vm;required_tags=owner')
    assert result['success'] is False and 'required_tags' in result['error']


def test_bare_tag_rule_requires_the_tag_with_any_value():
    from app.ai_models.policy_engine import policy_engine
    rule = policy_engine.parse_policy('resource_type=vm;tag=owner')['parsed_rule']['fields']
    assert rule['required_tags'] == [{'key': 'owner', 'value': ''}]
    untagged = {'resource_kind': 'vm', 'tags': []}
    tagged = {'resource_kind': 'vm', 'tags': [{'key': 'owner', 'value': 'team-a'}]}
    assert policy_engine.evaluate_resource(rule, untagged)['violations'] == ['Required tag missing: owner']
    assert policy_engine.evaluate_resource(rule, tagged)['compliant'] is True


def test_policy_text_is_length_bounded_and_name_rule_still_parses():
    from app.ai_models.policy_engine import policy_engine
    assert policy_engine.parse_policy('x=' + 'a' * 600)['success'] is False
    parsed = policy_engine.parse_policy('VM names must match ^web-')
    assert parsed['success'] and parsed['parsed_rule']['fields']['required_name_regex'] == '^web-'
