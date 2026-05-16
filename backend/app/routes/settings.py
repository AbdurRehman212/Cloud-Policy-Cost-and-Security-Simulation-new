from copy import deepcopy

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.models.settings import NotificationPreference, UserSettings
from app.models.user import User

settings_bp = Blueprint('settings', __name__)


ALLOWED_THEMES = {'light', 'dark'}
ALLOWED_DASHBOARD_VIEWS = {'overview', 'grid', 'list', 'map'}
DEFAULT_WIDGET_ORDER = ['resources', 'security', 'costs', 'governance', 'activity']


def _success(data, status_code=200):
    return jsonify({'status': 'success', 'data': data}), status_code


def _error(message, status_code=400):
    return jsonify({'status': 'error', 'error': {'message': message}}), status_code


def _get_or_create_settings(user_id):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
        db.session.flush()
    return settings


def _get_or_create_notification_preferences(user_id):
    notifications = NotificationPreference.query.filter_by(user_id=user_id).first()
    if not notifications:
        notifications = NotificationPreference(user_id=user_id)
        db.session.add(notifications)
        db.session.flush()
    return notifications


def _normalize_dashboard_layout(layout):
    payload = deepcopy(layout) if isinstance(layout, dict) else {}
    widget_order = payload.get('widget_order')
    if not isinstance(widget_order, list) or not widget_order:
        widget_order = DEFAULT_WIDGET_ORDER.copy()
    hidden_widgets = payload.get('hidden_widgets')
    if not isinstance(hidden_widgets, list):
        hidden_widgets = []
    payload['widget_order'] = [str(item) for item in widget_order]
    payload['hidden_widgets'] = [str(item) for item in hidden_widgets]
    payload.setdefault('learning_level', payload.get('learning_level'))
    payload.setdefault('learning_mode', payload.get('learning_mode'))
    return payload


def _serialize_settings(user, settings, notifications):
    dashboard_layout = _normalize_dashboard_layout(settings.dashboard_layout)
    user_preferences = {
        'theme': settings.theme or 'light',
        'dashboard': {
            'default_organization_id': settings.default_organization_id,
            'default_view': settings.default_view,
            'dashboard_layout': dashboard_layout,
        },
        'notifications': {
            'email': bool(settings.email_notifications),
            'push': bool(settings.push_notifications),
            'sms': bool(settings.sms_notifications),
            'preferences': {
                'cost_alerts': bool(notifications.cost_alert_enabled),
                'security_alerts': bool(notifications.security_alert_enabled),
                'cost_threshold': float(notifications.cost_alert_threshold or 80.0),
                'security_severity': notifications.security_alert_severity or 'medium',
                'compliance_alerts': bool(notifications.compliance_alert_enabled),
                'maintenance_notifications': bool(notifications.maintenance_notifications),
                'feature_announcements': bool(notifications.feature_announcements),
                'email_cost_alerts': bool(notifications.email_cost_alerts),
                'email_security_alerts': bool(notifications.email_security_alerts),
                'in_app_cost_alerts': bool(notifications.in_app_cost_alerts),
                'in_app_security_alerts': bool(notifications.in_app_security_alerts),
            },
        },
        'security': {
            'login_notifications': bool(settings.login_notifications),
            'suspicious_activity_alerts': bool(settings.suspicious_activity_alerts),
            'session_timeout': int(settings.session_timeout or 30),
        },
    }
    return {
        'user': user.to_dict(),
        'appearance': {
            'theme': settings.theme or 'light',
            'language': settings.language or 'en',
            'timezone': settings.timezone or 'UTC',
            'date_format': settings.date_format or 'YYYY-MM-DD',
        },
        'dashboard': {
            'default_organization_id': settings.default_organization_id,
            'default_view': settings.default_view,
            'dashboard_layout': dashboard_layout,
        },
        'notifications': user_preferences['notifications'],
        'security': {
            **user_preferences['security'],
            'two_factor': {
                'supported': False,
                'enabled': False,
                'status': 'not_enabled_in_this_build',
            },
        },
        'user_preferences': user_preferences,
    }


@settings_bp.route('', methods=['GET'])
@settings_bp.route('/', methods=['GET'])
@jwt_required()
def get_settings():
    """Get persisted user settings."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return _error('User not found', status_code=404)

    settings = _get_or_create_settings(user_id)
    notifications = _get_or_create_notification_preferences(user_id)
    db.session.commit()

    return _success(_serialize_settings(user, settings, notifications))


@settings_bp.route('', methods=['PUT'])
@settings_bp.route('/', methods=['PUT'])
@jwt_required()
def update_settings():
    """Update persisted user settings."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return _error('User not found', status_code=404)

    data = request.get_json() or {}
    settings = _get_or_create_settings(user_id)
    notifications = _get_or_create_notification_preferences(user_id)

    dashboard_payload = data.get('dashboard') or {}
    if 'default_organization_id' in dashboard_payload:
        settings.default_organization_id = dashboard_payload.get('default_organization_id')
    if 'default_view' in dashboard_payload:
        default_view = (dashboard_payload.get('default_view') or '').strip().lower()
        if default_view not in ALLOWED_DASHBOARD_VIEWS:
            return _error('Unsupported dashboard default_view')
        settings.default_view = default_view
    if 'dashboard_layout' in dashboard_payload:
        current_layout = _normalize_dashboard_layout(settings.dashboard_layout)
        incoming_layout = dashboard_payload.get('dashboard_layout') or {}
        if not isinstance(incoming_layout, dict):
            return _error('dashboard_layout must be an object')
        current_layout.update(incoming_layout)
        settings.dashboard_layout = _normalize_dashboard_layout(current_layout)

    appearance_payload = data.get('appearance') or {}
    if 'theme' in appearance_payload:
        theme = (appearance_payload.get('theme') or '').strip().lower()
        if theme not in ALLOWED_THEMES:
            return _error('Unsupported theme')
        settings.theme = theme
    if 'language' in appearance_payload:
        settings.language = (appearance_payload.get('language') or 'en').strip() or 'en'
    if 'timezone' in appearance_payload:
        settings.timezone = (appearance_payload.get('timezone') or 'UTC').strip() or 'UTC'
    if 'date_format' in appearance_payload:
        settings.date_format = (appearance_payload.get('date_format') or 'YYYY-MM-DD').strip() or 'YYYY-MM-DD'

    notifications_payload = data.get('notifications') or {}
    if 'email' in notifications_payload:
        settings.email_notifications = bool(notifications_payload.get('email'))
    if 'push' in notifications_payload:
        settings.push_notifications = bool(notifications_payload.get('push'))
    if 'sms' in notifications_payload:
        settings.sms_notifications = bool(notifications_payload.get('sms'))

    notification_preferences_payload = notifications_payload.get('preferences') or {}
    if 'cost_alerts' in notification_preferences_payload:
        notifications.cost_alert_enabled = bool(notification_preferences_payload.get('cost_alerts'))
    if 'security_alerts' in notification_preferences_payload:
        notifications.security_alert_enabled = bool(notification_preferences_payload.get('security_alerts'))
    if 'cost_threshold' in notification_preferences_payload:
        try:
            notifications.cost_alert_threshold = float(notification_preferences_payload.get('cost_threshold'))
        except (TypeError, ValueError):
            return _error('cost_threshold must be numeric')
    if 'security_severity' in notification_preferences_payload:
        notifications.security_alert_severity = (
            notification_preferences_payload.get('security_severity') or 'medium'
        ).strip().lower() or 'medium'
    if 'compliance_alerts' in notification_preferences_payload:
        notifications.compliance_alert_enabled = bool(notification_preferences_payload.get('compliance_alerts'))
    if 'maintenance_notifications' in notification_preferences_payload:
        notifications.maintenance_notifications = bool(notification_preferences_payload.get('maintenance_notifications'))
    if 'feature_announcements' in notification_preferences_payload:
        notifications.feature_announcements = bool(notification_preferences_payload.get('feature_announcements'))
    if 'email_cost_alerts' in notification_preferences_payload:
        notifications.email_cost_alerts = bool(notification_preferences_payload.get('email_cost_alerts'))
    if 'email_security_alerts' in notification_preferences_payload:
        notifications.email_security_alerts = bool(notification_preferences_payload.get('email_security_alerts'))
    if 'in_app_cost_alerts' in notification_preferences_payload:
        notifications.in_app_cost_alerts = bool(notification_preferences_payload.get('in_app_cost_alerts'))
    if 'in_app_security_alerts' in notification_preferences_payload:
        notifications.in_app_security_alerts = bool(notification_preferences_payload.get('in_app_security_alerts'))

    security_payload = data.get('security') or {}
    if 'login_notifications' in security_payload:
        settings.login_notifications = bool(security_payload.get('login_notifications'))
    if 'suspicious_activity_alerts' in security_payload:
        settings.suspicious_activity_alerts = bool(security_payload.get('suspicious_activity_alerts'))
    if 'session_timeout' in security_payload:
        try:
            settings.session_timeout = int(security_payload.get('session_timeout'))
        except (TypeError, ValueError):
            return _error('session_timeout must be an integer')

    if 'two_factor' in security_payload:
        requested = security_payload.get('two_factor') or {}
        if requested.get('enabled'):
            return _error('Two-factor authentication is not enabled in this build', status_code=400)

    db.session.commit()
    return _success(_serialize_settings(user, settings, notifications))
