R = '/api/resources'


def test_non_member_cannot_target_foreign_org(client, world):  # TC-M4-ISO
    org_a = world['org_a']
    assert client.post(f'{R}/vm', json={'organization_id': org_a, 'name': 'evil'}, headers=world['other']).status_code == 403
    assert client.post(f'{R}/create', json={'organization_id': org_a, 'name': 'evil'}, headers=world['other']).status_code == 403
    assert client.get(f'{R}?organization_id={org_a}', headers=world['other']).status_code == 403


def test_member_can_create_and_list_in_own_org(client, world):
    org_a = world['org_a']
    r = client.post(f'{R}/vm', json={'organization_id': org_a, 'name': 'ok-1'}, headers=world['admin'])
    assert r.status_code == 201
    listed = client.get(f'{R}?organization_id={org_a}', headers=world['viewer'])
    assert listed.status_code == 200 and [v['name'] for v in listed.get_json()['data']] == ['ok-1']


def test_vm_rejects_unknown_instance_type(client, world):  # TC-M4-VAL
    r = client.post(f'{R}/vm', json={'organization_id': world['org_a'], 'instance_type': 'zz.huge'}, headers=world['admin'])
    assert r.status_code == 400
