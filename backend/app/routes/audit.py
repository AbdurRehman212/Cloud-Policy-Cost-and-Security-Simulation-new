"""Module 11 — Audit Trail API (read-only).

There are deliberately no create/update/delete endpoints: rows are written only by
``app.services.audit_service`` as a side effect of real actions, and the model rejects
ORM updates/deletes.

Least privilege: owners and admins see the organization's whole trail; members and viewers
see only their own actions in that organization. ``/me`` returns the caller's own events,
including account-level events (login, settings) that have no organization.
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.utils.identity import get_jwt_identity  # int identity; tokens carry it as a string
from sqlalchemy import or_

from app import db
from app.models.governance import AuditLog
from app.services.audit_service import CATEGORIES, actions_for_category
from app.utils.rbac import ROLE_HIERARCHY, active_membership

audit_bp = Blueprint('audit', __name__)
MAX_PER_PAGE = 100


def _ok(data, status=200):
    return jsonify({'status': 'success', 'data': data}), status


def _err(message, status=400):
    return jsonify({'status': 'error', 'error': {'message': message}}), status


def _parse_date(value, end=False):
    """(datetime or None, error message or None)."""
    if not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None, 'Invalid date (use YYYY-MM-DD)'
    if end and len(str(value)) <= 10:  # a bare date means "through the end of that day"
        parsed += timedelta(days=1)
    return parsed, None


def _apply_filters(query, args):
    """(filtered query, error message or None); errors are fixed strings, never exception text."""
    category = (args.get('category') or '').strip().lower()
    if category:
        if category not in CATEGORIES and category != 'other':
            return query, 'Unknown category'
        legacy = [AuditLog.action.like(f'{prefix}%') for prefix in actions_for_category(category)]
        query = query.filter(or_(AuditLog.category == category,
                                 db.and_(AuditLog.category.is_(None), or_(*legacy)) if legacy else db.false()))
    outcome = (args.get('outcome') or '').strip().lower()
    if outcome:
        if outcome not in ('success', 'failure', 'denied'):
            return query, 'Unknown outcome'
        query = query.filter(AuditLog.outcome == outcome) if outcome != 'success' else query.filter(
            or_(AuditLog.outcome == 'success', AuditLog.outcome.is_(None)))
    action = (args.get('action') or '').strip()
    if action:
        query = query.filter(AuditLog.action == action)
    search = (args.get('q') or '').strip()
    if search:
        like = f'%{search[:100]}%'
        query = query.filter(or_(AuditLog.action.ilike(like), AuditLog.resource_type.ilike(like),
                                 AuditLog.resource_id.ilike(like)))
    user_filter = args.get('user_id', type=int)
    if user_filter:
        query = query.filter(AuditLog.user_id == user_filter)
    date_from, error = _parse_date(args.get('date_from'))
    if error:
        return query, error
    date_to, error = _parse_date(args.get('date_to'), end=True)
    if error:
        return query, error
    if date_from and date_to and date_from > date_to:
        return query, 'date_from must be before date_to'
    if date_from:
        query = query.filter(AuditLog.timestamp >= date_from)
    if date_to:
        query = query.filter(AuditLog.timestamp < date_to)
    return query, None


def _page(query):
    page = max(1, request.args.get('page', default=1, type=int))
    per_page = max(1, min(request.args.get('per_page', default=25, type=int), MAX_PER_PAGE))
    order = (request.args.get('order') or 'desc').lower()
    ordering = (AuditLog.timestamp.asc(), AuditLog.id.asc()) if order == 'asc' else (AuditLog.timestamp.desc(), AuditLog.id.desc())
    total = query.count()
    rows = query.order_by(*ordering).offset((page - 1) * per_page).limit(per_page).all()
    return {
        'events': [row.to_dict() for row in rows],
        'total': total, 'page': page, 'per_page': per_page,
        'pages': (total + per_page - 1) // per_page,
    }


def _org_scope():
    user_id = int(get_jwt_identity())
    org_id = request.args.get('organization_id', type=int) or request.args.get('org_id', type=int)
    if not org_id:
        return None, None, _err('organization_id required')
    member = active_membership(user_id, org_id)
    if member is None:
        return None, None, _err('Access denied', 403)
    query = AuditLog.query.filter(AuditLog.organization_id == org_id)
    full_access = ROLE_HIERARCHY.get(member.role, -1) >= ROLE_HIERARCHY['admin']
    if not full_access:
        query = query.filter(AuditLog.user_id == user_id)
    return query, full_access, None


@audit_bp.route('/events', methods=['GET'])
@jwt_required()
def list_events():
    query, full_access, error = _org_scope()
    if error:
        return error
    query, error = _apply_filters(query, request.args)
    if error:
        return _err(error)
    data = _page(query)
    data['scope'] = 'organization' if full_access else 'own_actions'
    data['categories'] = list(CATEGORIES)
    return _ok(data)


@audit_bp.route('/events/<int:event_id>', methods=['GET'])
@jwt_required()
def get_event(event_id):
    query, _full, error = _org_scope()
    if error:
        return error
    event = query.filter(AuditLog.id == event_id).first()
    if event is None:
        return _err('Audit event not found', 404)
    data = event.to_dict()
    data['user_agent'] = event.user_agent
    return _ok(data)


@audit_bp.route('/summary', methods=['GET'])
@jwt_required()
def summary():
    query, full_access, error = _org_scope()
    if error:
        return error
    days = max(1, min(request.args.get('days', default=30, type=int), 365))
    since = datetime.utcnow() - timedelta(days=days)
    rows = (query.filter(AuditLog.timestamp >= since)
            .with_entities(AuditLog.category, AuditLog.outcome, db.func.count(AuditLog.id))
            .group_by(AuditLog.category, AuditLog.outcome).all())
    by_category, by_outcome = {}, {}
    for category, outcome, count in rows:
        by_category[category or 'other'] = by_category.get(category or 'other', 0) + count
        by_outcome[outcome or 'success'] = by_outcome.get(outcome or 'success', 0) + count
    return _ok({'days': days, 'by_category': by_category, 'by_outcome': by_outcome,
                'total': sum(by_category.values()), 'scope': 'organization' if full_access else 'own_actions'})


@audit_bp.route('/me', methods=['GET'])
@jwt_required()
def my_events():
    user_id = int(get_jwt_identity())
    query = AuditLog.query.filter(AuditLog.user_id == user_id)
    query, error = _apply_filters(query, request.args)
    if error:
        return _err(error)
    data = _page(query)
    data['scope'] = 'own_account'
    return _ok(data)
