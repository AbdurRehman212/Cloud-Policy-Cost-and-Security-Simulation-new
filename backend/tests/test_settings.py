"""Module 12 — User Settings: Chapter 6 UT-66..UT-71, IT-20, validation and authorization."""

import pytest

from app import db
from app.models.governance import AuditLog
from app.models.settings import UserSettings


def _get(client, headers):
    resp = client.get('/api/settings', headers=headers)
    assert resp.status_code == 200
    return resp.get_json()['data']


def _put(client, headers, payload):
    return client.put('/api/settings', json=payload, headers=headers)


def test_ut66_defaults_for_new_account(client, world):
    data = _get(client, world['owner'])
    assert data['appearance']['theme'] == 'light'
    assert data['appearance']['date_format'] == 'YYYY-MM-DD'
    assert data['dashboard']['default_view'] == 'grid'
    assert data['notifications']['preferences']['cost_threshold'] == 80.0


def test_ut67_theme_change_is_saved_and_returned_on_next_load(client, world):
    assert _put(client, world['owner'], {'appearance': {'theme': 'dark'}}).status_code == 200
    db.session.expire_all()
    assert _get(client, world['owner'])['appearance']['theme'] == 'dark'
    assert UserSettings.query.filter_by(user_id=world['owner_id']).one().theme == 'dark'  # persisted


def test_ut68_unsupported_theme_is_refused(client, world):
    resp = _put(client, world['owner'], {'appearance': {'theme': 'neon'}})
    assert resp.status_code == 400 and resp.get_json()['error']['message'] == 'Unsupported theme'


def test_ut69_unsupported_default_view_is_refused(client, world):
    resp = _put(client, world['owner'], {'dashboard': {'default_view': 'zzz'}})
    assert resp.status_code == 400
    assert resp.get_json()['error']['message'] == 'Unsupported dashboard default view'


def test_ut70_non_numeric_cost_threshold_is_refused(client, world):
    resp = _put(client, world['owner'], {'notifications': {'preferences': {'cost_threshold': 'abc'}}})
    assert resp.status_code == 400
    assert resp.get_json()['error']['message'] == 'Cost threshold must be numeric'


def test_ut71_profile_details_are_stored_and_returned(client, world):
    resp = _put(client, world['owner'], {'profile': {'department': 'IT', 'job_title': 'Student'}})
    assert resp.status_code == 200
    db.session.expire_all()
    profile = _get(client, world['owner'])['profile']
    assert profile['department'] == 'IT' and profile['job_title'] == 'Student'


def test_it20_saved_default_organization_is_returned(client, world):
    resp = client.post('/api/org/', json={'name': 'Fresh Org'}, headers=world['owner'])
    assert resp.status_code in (200, 201)
    new_org = resp.get_json()['data']['organization']['id']
    assert _put(client, world['owner'], {'dashboard': {'default_organization_id': new_org}}).status_code == 200
    assert _get(client, world['owner'])['dashboard']['default_organization_id'] == new_org


def test_default_organization_must_be_a_membership(client, world):
    resp = _put(client, world['owner'], {'dashboard': {'default_organization_id': world['org_b']}})
    assert resp.status_code == 400
    assert _get(client, world['owner'])['dashboard']['default_organization_id'] is None


def test_invalid_payload_changes_nothing(client, world):
    resp = _put(client, world['owner'], {'appearance': {'theme': 'dark', 'date_format': 'nope'}})
    assert resp.status_code == 400
    assert _get(client, world['owner'])['appearance']['theme'] == 'light'  # all-or-nothing


@pytest.mark.parametrize('payload, message', [
    ({'notifications': {'preferences': {'cost_threshold': 150}}}, 'Cost threshold must be between 1 and 100'),
    ({'notifications': {'preferences': {'cost_alerts': 'false'}}}, 'Cost alerts must be true or false'),
    ({'notifications': {'preferences': {'security_severity': 'extreme'}}}, 'Unsupported security alert severity'),
    ({'security': {'session_timeout': 1}}, 'Session timeout must be between 5 and 480'),
    ({'appearance': {'timezone': 'Mars/Base'}}, 'Unsupported timezone'),
    ({'profile': {'first_name': ''}}, 'First name is required'),
    ({'profile': {'department': 'x' * 101}}, 'Department must be at most 100 characters'),
    ({'security': {'two_factor': {'enabled': True}}}, 'Two-factor authentication is not enabled in this build'),
])
def test_validation_messages(client, world, payload, message):
    resp = _put(client, world['owner'], payload)
    assert resp.status_code == 400 and resp.get_json()['error']['message'] == message


def test_users_only_change_their_own_settings(client, world):
    # The user id comes from the token; a body user_id is ignored.
    _put(client, world['viewer'], {'user_id': world['owner_id'], 'appearance': {'theme': 'dark'}})
    assert _get(client, world['owner'])['appearance']['theme'] == 'light'
    assert _get(client, world['viewer'])['appearance']['theme'] == 'dark'
    assert client.get('/api/settings').status_code == 401


def test_restore_defaults(client, world):
    _put(client, world['owner'], {'appearance': {'theme': 'dark', 'date_format': 'DD/MM/YYYY'},
                                  'dashboard': {'default_view': 'list', 'default_organization_id': world['org_a']},
                                  'notifications': {'preferences': {'cost_threshold': 55}},
                                  'profile': {'department': 'Ops'}})
    resp = client.post('/api/settings/reset', headers=world['owner'])
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['appearance']['theme'] == 'light' and data['appearance']['date_format'] == 'YYYY-MM-DD'
    assert data['dashboard']['default_view'] == 'grid' and data['dashboard']['default_organization_id'] is None
    assert data['notifications']['preferences']['cost_threshold'] == 80.0
    assert data['profile']['department'] == 'Ops'  # profile is kept
    assert AuditLog.query.filter_by(action='settings_reset', user_id=world['owner_id']).count() == 1


def test_settings_change_is_audited_with_diff(client, world):
    _put(client, world['owner'], {'appearance': {'theme': 'dark'}})
    entry = AuditLog.query.filter_by(action='settings_updated', user_id=world['owner_id']).one()
    assert entry.organization_id is None and entry.category == 'settings'
    assert entry.old_values == {'settings.theme': 'light'} and entry.new_values == {'settings.theme': 'dark'}


def test_alert_feed_follows_preferences(client, world):
    from app.models.cost import Budget, CostRecord
    from app.models.security import ThreatDetection, ThreatSeverity, ThreatType
    org = world['org_a']
    db.session.add(ThreatDetection(organization_id=org, threat_type=ThreatType.DDoS, severity=ThreatSeverity.LOW,
                                   confidence_score=0.9, status='active'))
    db.session.add(ThreatDetection(organization_id=org, threat_type=ThreatType.DDoS, severity=ThreatSeverity.HIGH,
                                   confidence_score=0.9, status='active'))
    db.session.commit()
    alerts = client.get(f'/api/settings/alerts?organization_id={org}', headers=world['owner']).get_json()['data']['alerts']
    assert [a['severity'] for a in alerts if a['type'] == 'security'] == ['high']  # default floor: medium
    _put(client, world['owner'], {'notifications': {'preferences': {'security_alerts': False}}})
    alerts = client.get(f'/api/settings/alerts?organization_id={org}', headers=world['owner']).get_json()['data']['alerts']
    assert not [a for a in alerts if a['type'] == 'security']
    assert client.get(f'/api/settings/alerts?organization_id={world["org_b"]}', headers=world['owner']).status_code == 403
