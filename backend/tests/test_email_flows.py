"""FR3/FR4 e-mail flows with mail delivery configured (messages captured, nothing sent)."""

import re
import time

import pytest

from app import mail
from app.models.user import User

PASSWORD = 'Str0ng!Passw0rd'


@pytest.fixture()
def mail_on(app):
    app.config.update(MAIL_SERVER='localhost', MAIL_PORT=1025, MAIL_DEFAULT_SENDER='noreply@simulator.local',
                      EMAIL_VERIFICATION_REQUIRED=True)
    with mail.record_messages() as outbox:
        yield outbox


def _wait_for(outbox, count):
    for _ in range(50):  # messages are sent on a background thread
        if len(outbox) >= count:
            return
        time.sleep(0.05)
    raise AssertionError(f'expected {count} e-mail(s), got {len(outbox)}')


def _link_token(message):
    return re.search(r'token=([A-Za-z0-9_\-]+)', message.body).group(1)


def test_registration_requires_e_mail_verification_when_enabled(client, mail_on):
    resp = client.post('/api/auth/register', json={'email': 'new@t.io', 'password': PASSWORD,
                                                   'first_name': 'N', 'last_name': 'U'})
    assert resp.status_code == 201 and 'verify' in resp.get_json()['data']['message']
    blocked = client.post('/api/auth/login', json={'email': 'new@t.io', 'password': PASSWORD})
    assert blocked.status_code == 403
    _wait_for(mail_on, 1)
    assert mail_on[0].recipients == ['new@t.io'] and '/verify-email?token=' in mail_on[0].body
    assert client.get(f'/api/auth/verify-email?token={_link_token(mail_on[0])}').status_code == 200
    assert client.post('/api/auth/login', json={'email': 'new@t.io', 'password': PASSWORD}).status_code == 200
    assert User.query.filter_by(email='new@t.io').one().email_verified is True


def test_password_recovery_by_e_mail(client, app, mail_on):
    app.config['EMAIL_VERIFICATION_REQUIRED'] = False
    client.post('/api/auth/register', json={'email': 'lost@t.io', 'password': PASSWORD,
                                            'first_name': 'L', 'last_name': 'P'})
    resp = client.post('/api/auth/forgot-password', json={'email': 'lost@t.io'})
    assert resp.get_json()['data']['delivery_configured'] is True
    _wait_for(mail_on, 1)
    token = _link_token(mail_on[0])
    assert 'expires in 1 hour' in mail_on[0].body
    assert client.post('/api/auth/reset-password', json={'token': token, 'new_password': 'N3w!Passw0rdX'}).status_code == 200
    assert client.post('/api/auth/login', json={'email': 'lost@t.io', 'password': 'N3w!Passw0rdX'}).status_code == 200
    # Only the newest link works: requesting again invalidates the earlier one.
    client.post('/api/auth/forgot-password', json={'email': 'lost@t.io'})
    client.post('/api/auth/forgot-password', json={'email': 'lost@t.io'})
    _wait_for(mail_on, 3)
    first, second = _link_token(mail_on[1]), _link_token(mail_on[2])
    assert client.post('/api/auth/reset-password', json={'token': first, 'new_password': 'An0ther!Pass'}).status_code == 400
    assert client.post('/api/auth/reset-password', json={'token': second, 'new_password': 'An0ther!Pass'}).status_code == 200


def test_unknown_address_gets_no_e_mail_and_the_same_answer(client, mail_on):
    resp = client.post('/api/auth/forgot-password', json={'email': 'nobody@t.io'})
    assert resp.status_code == 200
    time.sleep(0.3)
    assert mail_on == []


def test_reset_link_ignores_a_forged_host_header(client, app, mail_on):
    app.config['EMAIL_VERIFICATION_REQUIRED'] = False
    client.post('/api/auth/register', json={'email': 'host@t.io', 'password': PASSWORD,
                                            'first_name': 'H', 'last_name': 'H'})
    client.post('/api/auth/forgot-password', json={'email': 'host@t.io'}, headers={'Host': 'evil.example'})
    _wait_for(mail_on, 1)
    assert 'evil.example' not in mail_on[0].body
    assert mail_on[0].body.count(app.config['FRONTEND_BASE_URL'] + '/reset-password?token=') == 1
