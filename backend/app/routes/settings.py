"""Module 12 — User Settings (UC13 Manage Settings).

GET    /api/settings          current settings (created with defaults on first read)
PUT    /api/settings          validate everything, then save (all-or-nothing)
POST   /api/settings/reset    restore default preferences (profile data is kept)
GET    /api/settings/alerts   in-app alerts for an organization, filtered by the
                              caller's alert preferences (the only notification channel
                              this build delivers; e-mail/SMS/push are not implemented)

A user can only read and change their own settings: the user id always comes from the
JWT, never from the request. The default organization must be one the user belongs to.
"""

from copy import deepcopy
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from app.utils.identity import get_jwt_identity  # int identity; tokens carry it as a string

from app import db
from app.models.settings import NotificationPreference, UserSettings
from app.models.user import User, UserProfile
from app.services.audit_service import record_audit
from app.utils.rbac import active_membership

settings_bp = Blueprint('settings', __name__)

ALLOWED_THEMES = {'light', 'dark'}
# 'grid'/'list' drive the Resources layout; 'overview' and 'map' are accepted for rows saved by
# earlier builds and are shown as the grid layout.
ALLOWED_DASHBOARD_VIEWS = {'grid', 'list', 'overview', 'map'}
ALLOWED_DATE_FORMATS = {'YYYY-MM-DD', 'DD/MM/YYYY', 'MM/DD/YYYY'}
ALLOWED_LANGUAGES = {'en'}
ALLOWED_SEVERITIES = ['low', 'medium', 'high', 'critical']
SESSION_TIMEOUT_RANGE = (5, 480)  # minutes of inactivity before the app signs out
COST_THRESHOLD_RANGE = (1, 100)  # percent of a budget
PROFILE_LIMITS = {'first_name': 100, 'last_name': 100, 'department': 100, 'job_title': 100, 'phone': 20, 'bio': 1000}
DEFAULT_WIDGET_ORDER = ['resources', 'security', 'costs', 'governance', 'activity']

DEFAULTS = {
    'theme': 'light', 'language': 'en', 'timezone': 'UTC', 'date_format': 'YYYY-MM-DD',
    'default_view': 'grid', 'default_organization_id': None, 'session_timeout': 30,
    'cost_alerts': True, 'cost_threshold': 80.0, 'security_alerts': True, 'security_severity': 'medium',
    'compliance_alerts': True,
}


class SettingsError(ValueError):
    """Raised by validators after they record a fixed, user-facing message in ``g``."""

    def __init__(self, message):
        g.settings_error = message  # read by the route; exception text never reaches a response
        super().__init__('invalid settings')


def _success(data, status_code=200):
    return jsonify({'status': 'success', 'data': data}), status_code


def _error(message, status_code=400):
    return jsonify({'status': 'error', 'error': {'message': message}}), status_code


def _get_or_create(user_id):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
    notifications = NotificationPreference.query.filter_by(user_id=user_id).first()
    if not notifications:
        notifications = NotificationPreference(user_id=user_id)
        db.session.add(notifications)
    db.session.flush()
    return settings, notifications


def _layout(layout):
    payload = deepcopy(layout) if isinstance(layout, dict) else {}
    if not isinstance(payload.get('widget_order'), list) or not payload['widget_order']:
        payload['widget_order'] = DEFAULT_WIDGET_ORDER.copy()
    if not isinstance(payload.get('hidden_widgets'), list):
        payload['hidden_widgets'] = []
    payload['widget_order'] = [str(i) for i in payload['widget_order']]
    payload['hidden_widgets'] = [str(i) for i in payload['hidden_widgets']]
    return payload


def _serialize(user, settings, notifications):
    profile = user.profile
    preferences = {
        'cost_alerts': bool(notifications.cost_alert_enabled),
        'security_alerts': bool(notifications.security_alert_enabled),
        'cost_threshold': float(notifications.cost_alert_threshold if notifications.cost_alert_threshold is not None else 80.0),
        'security_severity': notifications.security_alert_severity or 'medium',
        'compliance_alerts': bool(notifications.compliance_alert_enabled),
        # Stored for compatibility; not delivered by this build (no e-mail/SMS/push channel).
        'email_cost_alerts': bool(notifications.email_cost_alerts),
        'email_security_alerts': bool(notifications.email_security_alerts),
        'in_app_cost_alerts': bool(notifications.in_app_cost_alerts),
        'in_app_security_alerts': bool(notifications.in_app_security_alerts),
        'maintenance_notifications': bool(notifications.maintenance_notifications),
        'feature_announcements': bool(notifications.feature_announcements),
    }
    dashboard = {
        'default_organization_id': settings.default_organization_id,
        'default_view': settings.default_view or 'grid',
        'dashboard_layout': _layout(settings.dashboard_layout),
    }
    security = {
        'session_timeout': int(settings.session_timeout or 30),
        'login_notifications': bool(settings.login_notifications),
        'suspicious_activity_alerts': bool(settings.suspicious_activity_alerts),
        'two_factor': {'supported': False, 'enabled': False, 'status': 'not_enabled_in_this_build'},
    }
    notification_block = {
        'email': bool(settings.email_notifications), 'push': bool(settings.push_notifications),
        'sms': bool(settings.sms_notifications), 'preferences': preferences,
        'delivery': {'in_app': True, 'email': False, 'sms': False, 'push': False},
    }
    return {
        'user': user.to_dict(),
        'profile': {
            'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email,
            'department': profile.department if profile else None,
            'job_title': profile.job_title if profile else None,
            'phone': profile.phone if profile else None,
            'bio': profile.bio if profile else None,
        },
        'appearance': {
            'theme': settings.theme if settings.theme in ALLOWED_THEMES else 'light',
            'language': settings.language or 'en',
            'timezone': settings.timezone or 'UTC',
            'date_format': settings.date_format if settings.date_format in ALLOWED_DATE_FORMATS else 'YYYY-MM-DD',
        },
        'dashboard': dashboard,
        'notifications': notification_block,
        'security': security,
        'options': {
            'themes': sorted(ALLOWED_THEMES), 'default_views': ['grid', 'list'],
            'date_formats': sorted(ALLOWED_DATE_FORMATS), 'severities': ALLOWED_SEVERITIES,
            'session_timeout_range': list(SESSION_TIMEOUT_RANGE), 'cost_threshold_range': list(COST_THRESHOLD_RANGE),
        },
        'updated_at': settings.updated_at.isoformat() if settings.updated_at else None,
        # Kept for older frontend code.
        'user_preferences': {'theme': settings.theme or 'light', 'dashboard': dashboard,
                             'notifications': notification_block, 'security': security},
    }


# ── validation ────────────────────────────────────────────────────────────────

def _bool(value, name):
    if isinstance(value, bool):
        return value
    raise SettingsError(f'{name} must be true or false')


def _choice(value, allowed, message):
    text = str(value or '').strip()
    normalized = text.lower() if allowed is not ALLOWED_DATE_FORMATS else text.upper()
    if normalized not in allowed:
        raise SettingsError(message)
    return normalized


def _number(value, name, low, high, integer=False):
    if isinstance(value, bool):
        raise SettingsError(f'{name} must be numeric')
    try:
        number = int(value) if integer and float(value) == int(float(value)) else float(value)
    except (TypeError, ValueError):
        raise SettingsError(f'{name} must be numeric')
    if integer and not isinstance(number, int):
        raise SettingsError(f'{name} must be a whole number')
    if not (low <= number <= high):
        raise SettingsError(f'{name} must be between {low} and {high}')
    return number


def _timezone(value):
    name = str(value or '').strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise SettingsError('Unsupported timezone')
    return name


def _text(value, name, limit):
    if value is None:
        return None
    if not isinstance(value, str):
        raise SettingsError(f'{name} must be text')
    value = value.strip()
    if len(value) > limit:
        raise SettingsError(f'{name} must be at most {limit} characters')
    return value


def _plan_changes(user_id, data):
    """Validate the whole payload; return {(target, field): value} without touching the DB."""
    if not isinstance(data, dict):
        raise SettingsError('Request body must be a JSON object')
    changes = {}

    profile = data.get('profile') or {}
    for field, limit in PROFILE_LIMITS.items():
        if field in profile:
            value = _text(profile[field], field.replace('_', ' ').capitalize(), limit)
            if field in ('first_name', 'last_name') and not value:
                raise SettingsError(f'{field.replace("_", " ").capitalize()} is required')
            changes[('profile', field)] = value

    appearance = data.get('appearance') or {}
    if 'theme' in appearance:
        changes[('settings', 'theme')] = _choice(appearance['theme'], ALLOWED_THEMES, 'Unsupported theme')
    if 'date_format' in appearance:
        changes[('settings', 'date_format')] = _choice(appearance['date_format'], ALLOWED_DATE_FORMATS, 'Unsupported date format')
    if 'language' in appearance:
        changes[('settings', 'language')] = _choice(appearance['language'], ALLOWED_LANGUAGES, 'Unsupported language')
    if 'timezone' in appearance:
        changes[('settings', 'timezone')] = _timezone(appearance['timezone'])

    dashboard = data.get('dashboard') or {}
    if 'default_view' in dashboard:
        changes[('settings', 'default_view')] = _choice(dashboard['default_view'], ALLOWED_DASHBOARD_VIEWS,
                                                        'Unsupported dashboard default view')
    if 'default_organization_id' in dashboard:
        org_id = dashboard['default_organization_id']
        if org_id in (None, ''):
            changes[('settings', 'default_organization_id')] = None
        else:
            try:
                org_id = int(org_id)
            except (TypeError, ValueError):
                raise SettingsError('default_organization_id must be an organization id')
            if active_membership(user_id, org_id) is None:
                raise SettingsError('You can only choose an organization you belong to')
            changes[('settings', 'default_organization_id')] = org_id
    if 'dashboard_layout' in dashboard:
        if not isinstance(dashboard['dashboard_layout'], dict):
            raise SettingsError('dashboard_layout must be an object')
        changes[('settings', 'dashboard_layout')] = dashboard['dashboard_layout']

    prefs = (data.get('notifications') or {}).get('preferences') or {}
    for key, field in (('cost_alerts', 'cost_alert_enabled'), ('security_alerts', 'security_alert_enabled'),
                       ('compliance_alerts', 'compliance_alert_enabled'),
                       ('email_cost_alerts', 'email_cost_alerts'), ('email_security_alerts', 'email_security_alerts'),
                       ('in_app_cost_alerts', 'in_app_cost_alerts'), ('in_app_security_alerts', 'in_app_security_alerts'),
                       ('maintenance_notifications', 'maintenance_notifications'),
                       ('feature_announcements', 'feature_announcements')):
        if key in prefs:
            changes[('notifications', field)] = _bool(prefs[key], key.replace('_', ' ').capitalize())
    if 'cost_threshold' in prefs:
        changes[('notifications', 'cost_alert_threshold')] = float(
            _number(prefs['cost_threshold'], 'Cost threshold', *COST_THRESHOLD_RANGE))
    if 'security_severity' in prefs:
        changes[('notifications', 'security_alert_severity')] = _choice(
            prefs['security_severity'], set(ALLOWED_SEVERITIES), 'Unsupported security alert severity')

    security = data.get('security') or {}
    if 'session_timeout' in security:
        changes[('settings', 'session_timeout')] = _number(
            security['session_timeout'], 'Session timeout', *SESSION_TIMEOUT_RANGE, integer=True)
    for key in ('login_notifications', 'suspicious_activity_alerts'):
        if key in security:
            changes[('settings', key)] = _bool(security[key], key.replace('_', ' ').capitalize())
    if (security.get('two_factor') or {}).get('enabled'):
        raise SettingsError('Two-factor authentication is not enabled in this build')
    return changes


def _apply(user, settings, notifications, changes):
    targets = {'settings': settings, 'notifications': notifications}
    old, new = {}, {}
    if any(target == 'profile' for target, _ in changes) and user.profile is None:
        user.profile = UserProfile(user_id=user.id)
        db.session.add(user.profile)
    for (target, field), value in changes.items():
        obj = (user if field in ('first_name', 'last_name') else user.profile) if target == 'profile' else targets[target]
        current = getattr(obj, field)
        if current != value:
            old[f'{target}.{field}'], new[f'{target}.{field}'] = current, value
            setattr(obj, field, value)
    return old, new


@settings_bp.route('', methods=['GET'])
@settings_bp.route('/', methods=['GET'])
@jwt_required()
def get_settings():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return _error('User not found', status_code=404)
    settings, notifications = _get_or_create(user.id)
    if settings.default_organization_id and active_membership(user.id, settings.default_organization_id) is None:
        settings.default_organization_id = None  # membership was removed since it was saved
    db.session.commit()
    return _success(_serialize(user, settings, notifications))


@settings_bp.route('', methods=['PUT'])
@settings_bp.route('/', methods=['PUT'])
@jwt_required()
def update_settings():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return _error('User not found', status_code=404)
    try:
        changes = _plan_changes(user.id, request.get_json(silent=True))
    except SettingsError:
        db.session.rollback()
        return _error(g.get('settings_error', 'Invalid settings'))
    settings, notifications = _get_or_create(user.id)
    old, new = _apply(user, settings, notifications, changes)
    if new:
        record_audit('settings_updated', org_id=None, user_id=user.id, resource_type='settings',
                     resource_id=user.id, old_values=old, new_values=new)
    db.session.commit()
    return _success(_serialize(user, settings, notifications))


@settings_bp.route('/reset', methods=['POST'])
@jwt_required()
def reset_settings():
    """Alternative flow of UC13: replace preferences with defaults (profile is not touched)."""
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return _error('User not found', status_code=404)
    settings, notifications = _get_or_create(user.id)
    changes = {
        ('settings', 'theme'): DEFAULTS['theme'], ('settings', 'language'): DEFAULTS['language'],
        ('settings', 'timezone'): DEFAULTS['timezone'], ('settings', 'date_format'): DEFAULTS['date_format'],
        ('settings', 'default_view'): DEFAULTS['default_view'],
        ('settings', 'default_organization_id'): DEFAULTS['default_organization_id'],
        ('settings', 'session_timeout'): DEFAULTS['session_timeout'],
        ('settings', 'dashboard_layout'): {'widget_order': DEFAULT_WIDGET_ORDER.copy(), 'hidden_widgets': []},
        ('notifications', 'cost_alert_enabled'): DEFAULTS['cost_alerts'],
        ('notifications', 'cost_alert_threshold'): DEFAULTS['cost_threshold'],
        ('notifications', 'security_alert_enabled'): DEFAULTS['security_alerts'],
        ('notifications', 'security_alert_severity'): DEFAULTS['security_severity'],
        ('notifications', 'compliance_alert_enabled'): DEFAULTS['compliance_alerts'],
    }
    old, new = _apply(user, settings, notifications, changes)
    record_audit('settings_reset', org_id=None, user_id=user.id, resource_type='settings', resource_id=user.id,
                 old_values=old, new_values=new)
    db.session.commit()
    return _success(_serialize(user, settings, notifications))


@settings_bp.route('/alerts', methods=['GET'])
@jwt_required()
def get_alerts():
    """In-app alerts for one organization, filtered by the caller's alert preferences."""
    from app.models.cost import Budget
    from app.models.security import ThreatDetection
    from app.services.governance_engine import governance_engine

    user_id = int(get_jwt_identity())
    org_id = request.args.get('organization_id', type=int)
    if not org_id or active_membership(user_id, org_id) is None:
        return _error('Access denied', status_code=403)
    _settings, prefs = _get_or_create(user_id)
    db.session.commit()

    alerts = []
    if prefs.security_alert_enabled:
        floor = ALLOWED_SEVERITIES.index(prefs.security_alert_severity or 'medium')
        threats = (ThreatDetection.query
                   .filter(ThreatDetection.organization_id == org_id, ThreatDetection.status.in_(('active', 'contained', 'under_review')))
                   .order_by(ThreatDetection.detected_at.desc()).limit(50).all())
        for threat in threats:
            severity = threat.severity.value if threat.severity else 'medium'
            if ALLOWED_SEVERITIES.index(severity) >= floor:
                alerts.append({
                    'type': 'security', 'severity': severity, 'link': '/remediation',
                    'title': f'{threat.threat_type.value.replace("_", " ").title()} threat ({threat.status})',
                    'detail': threat.detection_pattern, 'at': threat.detected_at.isoformat() if threat.detected_at else None,
                })
    if prefs.cost_alert_enabled:
        threshold = float(prefs.cost_alert_threshold or 80.0)
        for budget in Budget.query.filter_by(organization_id=org_id, is_active=True).all():
            info = budget.to_dict()
            used = float(info.get('percentage_used') or 0)
            if used >= threshold:
                alerts.append({
                    'type': 'cost', 'severity': 'high' if used >= 100 else 'medium', 'link': '/cost',
                    'title': f'Budget "{budget.name}" at {used:.1f}%',
                    'detail': f'Your alert threshold is {threshold:.0f}% of the budget.', 'at': None,
                })
    if prefs.compliance_alert_enabled:
        state = governance_engine.get_latest_state(org_id)
        open_violations = [v for v in state['violations'] if not v.get('remediation_applied')]
        if open_violations:
            alerts.append({
                'type': 'compliance', 'severity': 'medium', 'link': '/governance',
                'title': f'{len(open_violations)} open policy violation(s)',
                'detail': 'From the latest compliance check.', 'at': state['last_checked_at'],
            })
    return _success({
        'alerts': alerts, 'total': len(alerts),
        'preferences': {'security': bool(prefs.security_alert_enabled), 'security_severity': prefs.security_alert_severity,
                        'cost': bool(prefs.cost_alert_enabled), 'cost_threshold': float(prefs.cost_alert_threshold or 80.0),
                        'compliance': bool(prefs.compliance_alert_enabled)},
    })
