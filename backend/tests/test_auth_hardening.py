"""Final security hardening: rate limits, enumeration resistance, purpose-bound reset tokens,
session invalidation on password change, password-hash upgrade, headers, CORS and secrets."""

from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import db
from app.models.user import EmailVerification, User

PASSWORD = 'Str0ng!Passw0rd'


def _register(client, email):
    return client.post('/api/auth/register', json={'email': email, 'password': PASSWORD,
                                                   'first_name': 'A', 'last_name': 'B'})


def _login(client, email, password=PASSWORD):
    return client.post('/api/auth/login', json={'email': email, 'password': password})


def _bearer(token):
    return {'Authorization': f'Bearer {token}'}


# ── rate limits ───────────────────────────────────────────────────────────────

def test_registration_is_rate_limited_per_ip(client, app):
    codes = [_register(client, f'r{i}@t.io').status_code for i in range(31)]
    assert codes[:30] == [201] * 30 and codes[30] == 429


def test_forgot_password_is_rate_limited_per_ip_and_per_address(client, app):
    codes = [client.post('/api/auth/forgot-password', json={'email': 'x@t.io'}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]  # 3 per address per hour


def test_reset_and_verify_endpoints_are_rate_limited(client, app):
    reset = [client.post('/api/auth/reset-password', json={'token': 'bad', 'new_password': PASSWORD}).status_code
             for _ in range(11)]
    assert reset[:10] == [400] * 10 and reset[10] == 429
    verify = [client.get('/api/auth/verify-email?token=bad').status_code for _ in range(21)]
    assert verify[:20] == [400] * 20 and verify[20] == 429


# ── enumeration resistance ────────────────────────────────────────────────────

def test_lockout_answer_is_the_same_for_unknown_and_existing_accounts(client, app):
    _register(client, 'real@t.io')
    for email in ('real@t.io', 'ghost@t.io'):
        for _ in range(5):
            assert _login(client, email, 'wrong').status_code == 401
    real, ghost = _login(client, 'real@t.io', 'wrong'), _login(client, 'ghost@t.io', 'wrong')
    assert real.status_code == ghost.status_code == 429
    assert real.get_json() == ghost.get_json()


def test_forgot_password_answer_does_not_reveal_accounts(client, app):
    _register(client, 'known@t.io')
    known = client.post('/api/auth/forgot-password', json={'email': 'known@t.io'}).get_json()
    unknown = client.post('/api/auth/forgot-password', json={'email': 'nobody@t.io'}).get_json()
    assert known == unknown


# ── tokens ────────────────────────────────────────────────────────────────────

def test_verification_token_cannot_reset_a_password(client, app):
    _register(client, 'v@t.io')
    user = User.query.filter_by(email='v@t.io').one()
    token = EmailVerification.create_token(user.id, purpose='verify')
    db.session.add(token)
    db.session.commit()
    resp = client.post('/api/auth/reset-password', json={'token': token.token, 'new_password': 'N3w!Passw0rdX'})
    assert resp.status_code == 400
    assert _login(client, 'v@t.io').status_code == 200  # password unchanged


def test_reset_tokens_are_short_lived_single_use_and_end_sessions(client, app):
    _register(client, 'reset@t.io')
    old = _login(client, 'reset@t.io').get_json()['data']
    import time
    time.sleep(1.1)  # iat has one-second resolution
    user = User.query.filter_by(email='reset@t.io').one()
    token = EmailVerification.create_token(user.id, purpose='reset')
    assert timedelta(minutes=59) < token.expires_at - datetime.utcnow() <= timedelta(hours=1)
    db.session.add(token)
    db.session.commit()
    body = {'token': token.token, 'new_password': 'N3w!Passw0rdX'}
    assert client.post('/api/auth/reset-password', json=body).status_code == 200
    assert client.post('/api/auth/reset-password', json=body).status_code == 400  # single use
    assert client.get('/api/settings', headers=_bearer(old['access_token'])).status_code == 401
    assert client.post('/api/auth/refresh', headers=_bearer(old['refresh_token'])).status_code == 401
    assert _login(client, 'reset@t.io', 'N3w!Passw0rdX').status_code == 200


def test_password_change_ends_other_sessions_and_returns_fresh_tokens(client, app):
    _register(client, 'chg@t.io')
    other = _login(client, 'chg@t.io').get_json()['data']
    this = _login(client, 'chg@t.io').get_json()['data']
    import time
    time.sleep(1.1)  # iat has one-second resolution
    resp = client.post('/api/auth/change-password', headers=_bearer(this['access_token']),
                       json={'current_password': PASSWORD, 'new_password': 'N3w!Passw0rdX'})
    assert resp.status_code == 200
    fresh = resp.get_json()['data']
    assert client.get('/api/settings', headers=_bearer(other['access_token'])).status_code == 401
    assert client.get('/api/settings', headers=_bearer(fresh['access_token'])).status_code == 200


def test_legacy_pbkdf2_hashes_are_upgraded_at_login_without_ending_sessions(client, app):
    _register(client, 'legacy@t.io')
    user = User.query.filter_by(email='legacy@t.io').one()
    user.password_hash = generate_password_hash(PASSWORD, method='pbkdf2:sha256:100000')
    user.password_changed_at = None
    db.session.commit()
    assert _login(client, 'legacy@t.io').status_code == 200
    db.session.expire_all()
    user = User.query.filter_by(email='legacy@t.io').one()
    assert user.password_hash.startswith('scrypt:') and user.password_changed_at is None


# ── transport and configuration ───────────────────────────────────────────────

def test_security_headers_and_no_store_on_auth(client, app):
    resp = _login(client, 'nobody@t.io', 'x')
    for header in ('X-Content-Type-Options', 'X-Frame-Options', 'Content-Security-Policy', 'Referrer-Policy'):
        assert header in resp.headers
    assert resp.headers['Cache-Control'] == 'no-store'


def test_cors_allows_only_configured_origins(client, app):
    ok = client.options('/api/auth/login', headers={'Origin': 'http://localhost:3000',
                                                    'Access-Control-Request-Method': 'POST'})
    bad = client.options('/api/auth/login', headers={'Origin': 'https://evil.example',
                                                     'Access-Control-Request-Method': 'POST'})
    assert ok.headers.get('Access-Control-Allow-Origin') == 'http://localhost:3000'
    assert 'Access-Control-Allow-Origin' not in bad.headers


def test_production_refuses_placeholder_secrets(monkeypatch):
    from app.config import ProductionConfig
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('JWT_SECRET_KEY', raising=False)
    with pytest.raises(RuntimeError):
        ProductionConfig.validate()
    monkeypatch.setenv('SECRET_KEY', 'a' * 32)
    monkeypatch.setenv('JWT_SECRET_KEY', 'b' * 32)
    ProductionConfig.validate()
