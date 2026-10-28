from flask_jwt_extended import create_access_token

from app import db
from app.models.organization import Invitation, OrganizationMember
from app.models.user import User
from tests.conftest import _user

ORG = '/api/org'


def _login_headers(user_id):
    return {'Authorization': f'Bearer {create_access_token(identity=user_id)}'}


def test_invitation_end_to_end_and_role_applied(client, world):  # TC-M2-INVITE
    invitee = _user('newbie@t.io')
    db.session.commit()
    hdr = _login_headers(invitee.id)
    org = world['org_a']

    r = client.post(f'{ORG}/{org}/invite', json={'email': 'newbie@t.io', 'role': 'viewer'}, headers=world['owner'])
    assert r.status_code == 201
    token = Invitation.query.filter_by(email='newbie@t.io').one().token

    # before accepting: no access
    assert client.get(f'/api/resources?organization_id={org}', headers=hdr).status_code == 403
    # wrong user cannot redeem someone else's invite
    assert client.post(f'{ORG}/accept-invite', json={'token': token}, headers=world['other']).status_code == 403
    assert client.post(f'{ORG}/accept-invite', json={'token': token}, headers=hdr).status_code == 200
    # token is single-use
    assert client.post(f'{ORG}/accept-invite', json={'token': token}, headers=hdr).status_code == 400

    member = OrganizationMember.query.filter_by(organization_id=org, user_id=invitee.id).one()
    assert member.role == 'viewer'
    assert client.get(f'/api/resources?organization_id={org}', headers=hdr).status_code == 200
    assert client.post(f'{ORG}/{org}/invite', json={'email': 'x@t.io', 'role': 'viewer'}, headers=hdr).status_code == 403


def test_invite_validation(client, world):
    org = world['org_a']
    assert client.post(f'{ORG}/{org}/invite', json={'email': 'a@t.io', 'role': 'owner'}, headers=world['owner']).status_code == 400
    assert client.post(f'{ORG}/{org}/invite', json={'email': 'viewer@t.io', 'role': 'viewer'}, headers=world['owner']).status_code == 409
    assert client.post(f'{ORG}/accept-invite', json={'token': 'nope'}, headers=world['other']).status_code == 400


def test_role_matrix(client, world):  # TC-M2-RBAC
    org = world['org_a']
    body = {'organization_id': org, 'name': 'Req tag', 'policy_rule': 'All VMs must have tag environment'}
    budget = {'organization_id': org, 'name': 'B', 'amount': 10, 'start_date': '2026-10-01'}
    # viewer: read-only
    assert client.get(f'/api/cost/summary?organization_id={org}', headers=world['viewer']).status_code == 200
    assert client.post('/api/governance/policies', json=body, headers=world['viewer']).status_code == 403
    assert client.post('/api/cost/budgets', json=budget, headers=world['viewer']).status_code == 403
    assert client.post(f'{ORG}/{org}/invite', json={'email': 'a@t.io', 'role': 'viewer'}, headers=world['viewer']).status_code == 403
    assert client.post('/api/resources/vm', json={'organization_id': org, 'name': 'v'}, headers=world['viewer']).status_code == 403
    # admin: manage governance, budgets and members
    assert client.post('/api/governance/policies', json=body, headers=world['admin']).status_code in (200, 201)
    assert client.post('/api/cost/budgets', json=budget, headers=world['admin']).status_code == 201
    assert client.post(f'{ORG}/{org}/invite', json={'email': 'a@t.io', 'role': 'viewer'}, headers=world['admin']).status_code == 201
    # nobody can change or remove the owner
    owner_id = world['owner_id']
    assert client.put(f'{ORG}/{org}/members/{owner_id}/role', json={'role': 'viewer'}, headers=world['admin']).status_code == 403


def test_cannot_spoof_other_org_in_request_body_or_query(client, world):  # TC-M2-ISO
    org_a, org_b = world['org_a'], world['org_b']
    other = world['other']  # owner of org B only
    victim = OrganizationMember.query.filter_by(organization_id=org_a, user_id=User.query.filter_by(email='viewer@t.io').one().id).one()
    spoof = {'organization_id': org_b}
    assert client.post(f'{ORG}/{org_a}/invite', json={'email': 'a@t.io', 'role': 'admin', **spoof}, headers=other).status_code == 403
    assert client.post(f'{ORG}/{org_a}/invite?organization_id={org_b}', json={'email': 'a@t.io', 'role': 'admin'}, headers=other).status_code == 403
    assert client.delete(f'{ORG}/{org_a}/members/{victim.id}?organization_id={org_b}', headers=other).status_code == 403
    assert OrganizationMember.query.get(victim.id) is not None
    assert client.get(f'/api/cost/summary?organization_id={org_a}', headers=other).status_code == 403
    assert client.get(f'/api/reports/cost.csv?organization_id={org_a}', headers=other).status_code == 403
    assert client.get(f'/api/security/threats?organization_id={org_a}', headers=other).status_code == 403
    assert client.get(f'/api/governance/violations?organization_id={org_a}', headers=other).status_code == 403


def test_invite_demo_never_creates_accounts_or_default_passwords(client, world):  # ASVS V2: no default credentials
    org = world['org_a']
    before = User.query.count()
    r = client.post(f'{ORG}/invite_demo', json={'email': 'ghost@t.io', 'role': 'viewer', 'organization_id': org}, headers=world['owner'])
    assert r.status_code == 404
    assert User.query.count() == before


def test_role_assignment_rules(client, world):  # TC-M2-ROLES
    org = world['org_a']
    uid = lambda email: User.query.filter_by(email=email).one().id  # noqa: E731
    # admin cannot grant admin, demote the owner, or touch another admin
    assert client.post(f'{ORG}/invite_demo', json={'email': 'viewer@t.io', 'role': 'admin', 'organization_id': org}, headers=world['admin']).status_code == 403
    assert client.post(f'{ORG}/invite_demo', json={'email': 'owner@t.io', 'role': 'viewer', 'organization_id': org}, headers=world['admin']).status_code == 403
    assert client.put(f'{ORG}/{org}/members/{uid("viewer@t.io")}/role', json={'role': 'admin'}, headers=world['admin']).status_code == 403
    assert client.post(f'{ORG}/{org}/invite', json={'email': 'x@t.io', 'role': 'admin'}, headers=world['admin']).status_code == 403
    # admin may manage members/viewers
    assert client.put(f'{ORG}/{org}/members/{uid("viewer@t.io")}/role', json={'role': 'member'}, headers=world['admin']).status_code == 200
    # owner may grant admin; the owner role itself can never be changed
    assert client.put(f'{ORG}/{org}/members/{uid("viewer@t.io")}/role', json={'role': 'admin'}, headers=world['owner']).status_code == 200
    assert client.put(f'{ORG}/{org}/members/{world["owner_id"]}/role', json={'role': 'viewer'}, headers=world['owner']).status_code == 403
    # a (now second) admin cannot be removed by an admin, but can be by the owner
    victim = OrganizationMember.query.filter_by(organization_id=org, user_id=uid('viewer@t.io')).one()
    assert client.delete(f'{ORG}/{org}/members/{victim.id}', headers=world['admin']).status_code == 403
    assert client.delete(f'{ORG}/{org}/members/{victim.id}', headers=world['owner']).status_code == 200


def test_role_change_applies_immediately_to_existing_token(client, world):  # stale privileges
    org = world['org_a']
    body = {'organization_id': org, 'name': 'b', 'amount': 5, 'start_date': '2026-10-01'}
    assert client.post('/api/cost/budgets', json=body, headers=world['admin']).status_code == 201
    admin_id = User.query.filter_by(email='admin@t.io').one().id
    assert client.put(f'{ORG}/{org}/members/{admin_id}/role', json={'role': 'viewer'}, headers=world['owner']).status_code == 200
    assert client.post('/api/cost/budgets', json=body, headers=world['admin']).status_code == 403


def test_deleted_organization_grants_no_access(client, world):
    org = world['org_a']
    assert client.delete(f'{ORG}/{org}', headers=world['admin']).status_code == 403  # owner only
    assert client.delete(f'{ORG}/{org}', headers=world['owner']).status_code == 200
    listed = client.get(f'{ORG}/', headers=world['owner']).get_json()['data']['organizations']
    assert org not in [o['id'] for o in listed]
    assert client.get(f'/api/resources?organization_id={org}', headers=world['owner']).status_code == 403
    assert client.post('/api/resources/vm', json={'organization_id': org, 'name': 'zombie'}, headers=world['owner']).status_code == 403
