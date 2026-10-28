"""Deny-by-default sweep over every registered /api route (OWASP ASVS V4 access control)."""
import re

import pytest

# Endpoints that are intentionally reachable without a bearer token.
PUBLIC = {
    '/api/auth/register', '/api/auth/login', '/api/auth/verify-email', '/api/auth/forgot-password',
    '/api/auth/reset-password', '/api/auth/refresh',  # refresh needs a refresh token, checked separately
    '/api/assistant/chat',               # keyword help bot: no tenant data, input length capped
    '/api/learning/content/<action_key>',  # static lesson text
}
SKIP_METHODS = {'HEAD', 'OPTIONS'}


def _routes(app):
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith('/api/') or rule.endpoint == 'static':
            continue
        for method in rule.methods - SKIP_METHODS:
            path = re.sub(r'<[^>]+>', '1', rule.rule)
            yield method, path, rule.rule


def test_every_non_public_route_rejects_missing_token(client, app):
    leaks = []
    for method, path, rule in _routes(app):
        if rule in PUBLIC:
            continue
        res = client.open(path, method=method, json={} if method in {'POST', 'PUT', 'PATCH'} else None)
        if res.status_code not in (401, 422):
            leaks.append(f'{method} {rule} -> {res.status_code}')
    assert not leaks, 'routes reachable without a token:\n' + '\n'.join(sorted(leaks))


def test_outsider_gets_no_data_from_org_scoped_reads(client, app, world):
    """A user from another tenant must never receive 200 for GET routes scoped by organization_id."""
    org = world['org_a']
    leaks = []
    for method, path, rule in _routes(app):
        if method != 'GET' or rule in PUBLIC or '<' in rule:
            continue
        res = client.get(f'{path}?organization_id={org}', headers=world['other'])
        if res.status_code == 200:
            body = res.get_data(as_text=True)
            if re.search(rf'"(organization_id|org_id)":\s*{org}\b', body):
                leaks.append(f'GET {rule} returned org {org} data')
    assert not leaks, '\n'.join(sorted(leaks))


def test_assistant_rejects_oversized_input(client):
    assert client.post('/api/assistant/chat', json={'message': 'x' * 1001}).status_code == 400
    assert client.post('/api/assistant/chat', json={'message': 'how to run locally'}).status_code == 200


# Mutating routes a viewer may legitimately call because they only touch the caller's own account/progress.
VIEWER_SELF_SERVICE_PREFIXES = (
    '/api/auth/', '/api/settings', '/api/assistant', '/api/learning', '/api/scenarios', '/api/progress',
    '/api/membership',
)
# Allowed for every authenticated user: creating one's OWN organization, and read-only PDF generation.
VIEWER_ALLOWED_ROUTES = {('POST', '/api/org/'), ('POST', '/api/reports/generate')}


def test_viewer_cannot_mutate_organization_data(client, app, world):
    """Least privilege: a viewer's write attempts on org-scoped routes must not succeed."""
    org = world['org_a']
    succeeded = []
    for method, path, rule in _routes(app):
        if method not in {'POST', 'PUT', 'PATCH', 'DELETE'} or rule.startswith(VIEWER_SELF_SERVICE_PREFIXES):
            continue
        if (method, rule) in VIEWER_ALLOWED_ROUTES:
            continue
        res = client.open(f'{path}?organization_id={org}', method=method,
                          json={'organization_id': org, 'name': 'x', 'email': 'v@t.io', 'role': 'viewer',
                                'policy_rule': 'VM names must start with web-', 'amount': 5, 'start_date': '2026-10-01'},
                          headers=world['viewer'])
        if 200 <= res.status_code < 300:
            succeeded.append(f'{method} {rule} -> {res.status_code}')
    assert not succeeded, 'viewer write succeeded:\n' + '\n'.join(sorted(succeeded))


def test_system_reset_is_disabled_by_default(client, world):  # destructive, cross-tenant
    for role in ('viewer', 'admin', 'owner', 'other'):
        assert client.post('/api/admin/reset-system', headers=world[role]).status_code == 404
    assert client.post('/api/admin/reset-system').status_code in (401, 422)
