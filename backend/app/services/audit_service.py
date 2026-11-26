"""Central audit recording for all modules (Module 11 — Audit Trail).

Every audit row in the system is written by ``record_audit``. It:
- scopes the event to an organization (or to the user's account when ``org_id`` is None),
- assigns a category used by the audit timeline filters,
- removes secrets (passwords, tokens, keys) from recorded values,
- adds the request IP only for authentication events (other events do not need it).

The row joins the caller's transaction (``commit=False``) so the audit entry and the
change it describes are committed — or rolled back — together.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import has_request_context, request

from app import db
from app.models.governance import AuditLog

CATEGORIES = (
    'auth', 'organization', 'resource', 'security', 'governance',
    'cost', 'report', 'remediation', 'settings', 'data', 'learning',
)

# Most specific prefix first.
_CATEGORY_PREFIXES = [
    ('login', 'auth'), ('logout', 'auth'), ('register', 'auth'), ('password', 'auth'),
    ('account', 'auth'), ('email', 'auth'),
    ('org_', 'organization'), ('organization', 'organization'), ('member', 'organization'),
    ('invitation', 'organization'),
    ('vm_', 'resource'), ('db_', 'resource'), ('database', 'resource'), ('security_group', 'resource'),
    ('resource', 'resource'),
    ('threat', 'security'), ('attack', 'security'), ('alert_rule', 'security'), ('security', 'security'),
    ('policy', 'governance'), ('compliance', 'governance'),
    ('budget', 'cost'), ('cost', 'cost'), ('forecast', 'cost'),
    ('report', 'report'),
    ('remediation', 'remediation'),
    ('settings', 'settings'), ('profile', 'settings'),
    ('data_', 'data'), ('dataset', 'data'),
    ('scenario', 'learning'), ('lab', 'learning'),
]

SENSITIVE_KEY_PARTS = ('password', 'token', 'secret', 'api_key', 'apikey', 'authorization', 'jwt', 'otp')
_MAX_DEPTH = 4
_MAX_STRING = 500


def category_for(action: str) -> str:
    action = (action or '').lower()
    for prefix, category in _CATEGORY_PREFIXES:
        if action.startswith(prefix):
            return category
    return 'other'


def actions_for_category(category: str) -> list[str]:
    """Known action prefixes for a category (used for legacy rows with no stored category)."""
    return [prefix for prefix, cat in _CATEGORY_PREFIXES if cat == category]


def sanitize(value: Any, depth: int = 0) -> Any:
    """Drop secret-looking keys and bound the size of recorded values."""
    if depth > _MAX_DEPTH:
        return '…'
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS):
                clean[str(key)] = '[redacted]'
            else:
                clean[str(key)] = sanitize(item, depth + 1)
        return clean
    if isinstance(value, (list, tuple)):
        return [sanitize(item, depth + 1) for item in list(value)[:50]]
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING] + '…'
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def record_audit(
    action: str,
    *,
    org_id: int | None,
    user_id: int | None,
    resource_type: str | None = None,
    resource_id: Any = None,
    outcome: str = 'success',
    new_values: dict | None = None,
    old_values: dict | None = None,
    category: str | None = None,
    compliance_relevant: bool = False,
    commit: bool = False,
) -> AuditLog:
    category = category or category_for(action)
    ip_address = None
    user_agent = None
    if category == 'auth' and has_request_context():
        ip_address = (request.remote_addr or '')[:45] or None
        user_agent = (request.headers.get('User-Agent') or '')[:500] or None
    entry = AuditLog(
        organization_id=int(org_id) if org_id is not None else None,
        user_id=int(user_id) if user_id is not None else None,
        action=action[:100],
        category=category,
        outcome=outcome,
        resource_type=(resource_type or None) and str(resource_type)[:50],
        resource_id=None if resource_id is None else str(resource_id)[:50],
        timestamp=datetime.utcnow(),
        old_values=sanitize(old_values) if old_values is not None else None,
        new_values=sanitize(new_values or {}),
        ip_address=ip_address,
        user_agent=user_agent,
        compliance_relevant=compliance_relevant,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def record_audit_safely(action: str, **kwargs) -> None:
    """Commit an audit row in its own transaction; never raises into the caller.

    Used after the main change is already committed (or when it failed and was rolled back),
    so an audit-write problem cannot undo or mask the user's action.
    """
    try:
        record_audit(action, commit=True, **kwargs)
    except Exception:  # pragma: no cover - logged, not propagated
        db.session.rollback()
        import logging
        logging.getLogger(__name__).exception('audit write failed for %s', action)
