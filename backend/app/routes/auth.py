from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt
from app.utils.identity import get_jwt_identity  # int identity; tokens carry it as a string
from app import db, mail
from app.models.user import User, UserProfile, EmailVerification, TokenBlacklist
from app.models.settings import UserSettings
from app.models.organization import ensure_default_organization_membership
from flask_mail import Message
from app.services.audit_service import record_audit, record_audit_safely
from app.models.governance import AuditLog
from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock
import re
auth_bp = Blueprint('auth', __name__)

# Login throttling (OWASP ASVS V2.2). Per account: failed attempts are counted from the
# persisted audit trail, so the limit survives restarts. Per client IP: a small in-memory
# window also limits guessing across many e-mail addresses.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW = timedelta(minutes=15)
IP_MAX_ATTEMPTS = 50  # failed attempts per IP per window
_ip_attempts = defaultdict(deque)
_ip_lock = Lock()


def _ip_throttled(ip, record_failure=False):
    """True when this client IP has too many recent failed logins; optionally record one."""
    now = datetime.utcnow()
    with _ip_lock:
        window = _ip_attempts[ip]
        while window and now - window[0] > LOGIN_WINDOW:
            window.popleft()
        if record_failure:
            window.append(now)
        return len(window) >= IP_MAX_ATTEMPTS


def _account_locked(user):
    since = datetime.utcnow() - LOGIN_WINDOW
    last_success = (AuditLog.query.with_entities(db.func.max(AuditLog.timestamp))
                    .filter(AuditLog.user_id == user.id, AuditLog.action == 'login_succeeded').scalar())
    if last_success and last_success > since:
        since = last_success  # a successful login resets the counter
    failures = AuditLog.query.filter(
        AuditLog.user_id == user.id, AuditLog.action == 'login_failed', AuditLog.timestamp > since
    ).count()
    return failures >= LOGIN_MAX_FAILURES

DEMO_EMAIL_VERIFICATION_BYPASS = True


def _success(data, status_code=200):
    return jsonify({'status': 'success', 'data': data}), status_code


def _error(message, status_code=400):
    return jsonify({'status': 'error', 'error': {'message': message}}), status_code


def _frontend_url(path):
    base_url = current_app.config.get('FRONTEND_BASE_URL') or request.host_url.rstrip('/')
    return f"{base_url}{path}" if base_url else path


def _mail_delivery_configured():
    return bool(
        current_app.config.get('MAIL_SERVER')
        and current_app.config.get('MAIL_PORT')
        and current_app.config.get('MAIL_DEFAULT_SENDER')
        and current_app.config.get('MAIL_USERNAME')
        and current_app.config.get('MAIL_PASSWORD')
    )


def is_valid_email(email):
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None
def is_valid_password(password):
    """Validate password strength."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain digit"
    return True, "Valid"
@auth_bp.route('/register', methods=['POST'])
def register():
    """Register new user."""
    data = request.get_json() or {}
    # Validation
    required = ['email', 'password', 'first_name', 'last_name']
    for field in required:
        if not data.get(field):
            return _error(f'{field} is required', status_code=400)
    email = data['email'].lower().strip()
    if not is_valid_email(email):
        return _error('Invalid email format', status_code=400)
    valid_pwd, msg = is_valid_password(data['password'])
    if not valid_pwd:
        return _error(msg, status_code=400)
    if User.query.filter_by(email=email).first():
        return _error('Email already registered', status_code=409)
    try:
        # Create user
        user = User(
            email=email,
            first_name=data['first_name'],
            last_name=data['last_name'],
            # Email verification bypassed for demo; production uses external email service
            is_active=DEMO_EMAIL_VERIFICATION_BYPASS,
            email_verified=DEMO_EMAIL_VERIFICATION_BYPASS,
        )
        user.set_password(data['password'])
        db.session.add(user)
        db.session.flush()  # Get user.id without committing
        # Create profile
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)
        # Create settings
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)

        # Ensure every user starts with a valid owner membership for demo stability.
        ensure_default_organization_membership(user)
        record_audit('register_succeeded', org_id=None, user_id=user.id, resource_type='user', resource_id=user.id)

        verification = None
        if not DEMO_EMAIL_VERIFICATION_BYPASS:
            verification = EmailVerification.create_token(user.id)
            db.session.add(verification)

        db.session.commit()

        if verification is not None:
            send_verification_email(user.email, verification.token)

        payload = {
            'message': 'Registration successful. You can now log in.' if DEMO_EMAIL_VERIFICATION_BYPASS else 'Registration successful. Please check your email to verify your account.',
            'user': user.to_dict(),
        }
        return _success(payload, status_code=201)
    except Exception as e:
        db.session.rollback()
        return _error(f'Registration failed: {e}', status_code=500)
def send_verification_email(email, token):
    """Send email verification."""
    try:
        msg = Message(
            'Verify Your Cloud Policy, Cost & Security Simulator Account',
            recipients=[email]
        )
        verify_url = _frontend_url(f"/verify-email?token={token}")
        msg.body = f"""
        Welcome to Cloud Policy, Cost & Security Simulator!
        Please verify your email by clicking: {verify_url}
        This link expires in 24 hours.
        """
        mail.send(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")
@auth_bp.route('/verify-email', methods=['GET'])
def verify_email():
    """Verify email with token."""
    token = request.args.get('token')
    if not token:
        return _error('Token required', status_code=400)
    verification = EmailVerification.query.filter_by(token=token, used=False).first()
    if not verification:
        return _error('Invalid or used token', status_code=400)
    if verification.is_expired():
        return _error('Token expired', status_code=400)
    user = User.query.get(verification.user_id)
    user.email_verified = True
    user.is_active = True
    verification.used = True
    db.session.commit()
    return _success({'message': 'Email verified successfully. You can now log in.'})
@auth_bp.route('/login', methods=['POST'])
def login():
    """User login."""
    data = request.get_json() or {}
    email = data.get('email', '').lower().strip()
    password = data.get('password')
    if not email or not password:
        return _error('Email and password required', status_code=400)
    if current_app.config.get('LOGIN_THROTTLE_ENABLED', True) and _ip_throttled(request.remote_addr or 'unknown'):
        return _error('Too many login attempts. Try again later.', status_code=429)
    user = User.query.filter_by(email=email).first()
    if user and _account_locked(user):
        record_audit_safely('login_blocked', org_id=None, user_id=user.id, resource_type='user',
                            resource_id=user.id, outcome='denied')
        minutes = int(LOGIN_WINDOW.total_seconds() // 60)
        return _error(f'Too many failed sign-in attempts. Try again in {minutes} minutes.', status_code=429)
    if not user or not user.check_password(password):
        _ip_throttled(request.remote_addr or 'unknown', record_failure=True)
        if user:  # unknown e-mails are not recorded (no account to attribute them to)
            record_audit_safely('login_failed', org_id=None, user_id=user.id, resource_type='user',
                                resource_id=user.id, outcome='failure')
        return _error('Invalid credentials', status_code=401)

    if DEMO_EMAIL_VERIFICATION_BYPASS and (not user.is_active or not user.email_verified):
        pass
    elif not user.is_active:
        return _error('Account not activated. Please verify your email.', status_code=403)

    # Create tokens
    access_token = create_access_token(identity=user.id)
    refresh_token = create_refresh_token(identity=user.id)
    
    active_org_id = user.organizations[0].organization_id if user.organizations else None
    # Module 12: a saved default organization is used for the new session when still valid.
    from app.utils.rbac import active_membership
    preferred = user.settings.default_organization_id if user.settings else None
    if preferred and active_membership(user.id, preferred) is not None:
        active_org_id = preferred
    user.last_login = datetime.utcnow()
    record_audit('login_succeeded', org_id=None, user_id=user.id, resource_type='user', resource_id=user.id)
    db.session.commit()

    payload = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': user.to_dict(),
        'active_org_id': active_org_id,
    }
    return _success(payload)

@auth_bp.route('/logout', methods=['DELETE'])
@jwt_required(refresh=True)
def logout():
    """Logout - revoke the refresh token and, when supplied, the current access token."""
    from flask_jwt_extended import decode_token
    user_id = get_jwt_identity()
    jti = get_jwt().get('jti')
    if jti and not TokenBlacklist.is_blacklisted(jti, 'refresh'):
        db.session.add(TokenBlacklist(jti=jti, token_type='refresh'))
    access_token = (request.get_json(silent=True) or {}).get('access_token')
    if access_token:
        try:
            claims = decode_token(access_token, allow_expired=True)
        except Exception:
            claims = None
        if claims and str(claims.get('sub')) == str(user_id) and claims.get('type') == 'access':
            if not TokenBlacklist.is_blacklisted(claims['jti'], 'access'):
                db.session.add(TokenBlacklist(jti=claims['jti'], token_type='access'))
    record_audit('logout', org_id=None, user_id=user_id, resource_type='user', resource_id=user_id)
    db.session.commit()
    return _success({'message': 'Logged out successfully'})

@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token."""
    user_id = get_jwt_identity()
    jti = get_jwt().get('jti')
    # Validate refresh token not blacklisted
    if jti and TokenBlacklist.is_blacklisted(jti, 'refresh'):
        return _error('Refresh token has been invalidated', status_code=401)
    access_token = create_access_token(identity=user_id)
    return _success({'access_token': access_token})
@auth_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Get user profile."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return _error('User not found', status_code=404)
    return _success({
        'user': user.to_dict(),
        'profile': {
            'phone': user.profile.phone if user.profile else None,
            'department': user.profile.department if user.profile else None,
            'job_title': user.profile.job_title if user.profile else None
        }
    })
@auth_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """Update user profile."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return _error('User not found', status_code=404)
    data = request.get_json() or {}
    if 'display_name' in data and data['display_name']:
        user.first_name = data['display_name']
    if 'first_name' in data:
        user.first_name = data['first_name']
    if 'last_name' in data:
        user.last_name = data['last_name']
    # Create UserProfile first before assigning profile fields
    if not user.profile:
        from app.models.user import UserProfile
        user.profile = UserProfile(user_id=user.id)
        db.session.add(user.profile)
        db.session.flush()
    if 'bio' in data:
        user.profile.bio = data['bio']
    if 'timezone' in data:
        user.profile.timezone = data['timezone']
    if 'phone' in data:
        user.profile.phone = data['phone']
    if 'department' in data:
        user.profile.department = data['department']
    if 'job_title' in data:
        user.profile.job_title = data['job_title']
    record_audit('profile_updated', org_id=None, user_id=user.id, resource_type='user', resource_id=user.id,
                 new_values={k: data[k] for k in ('first_name', 'last_name', 'department', 'job_title', 'timezone') if k in data})
    db.session.commit()
    return _success({
        'user': user.to_dict(),
        'profile': {
            'timezone': user.profile.timezone if user.profile else 'UTC',
            'phone': user.profile.phone if user.profile else None,
            'bio': user.profile.bio if user.profile else None,
        }
    }, status_code=200)
@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Request password reset."""
    payload = request.get_json() or {}
    email = payload.get('email')
    delivery_configured = _mail_delivery_configured()
    user = User.query.filter_by(email=email).first()
    if user and delivery_configured:
        # Generate reset token
        from app.models.user import EmailVerification
        reset = EmailVerification.create_token(user.id)
        db.session.add(reset)
        db.session.commit()
        # Send email
        try:
            msg = Message('Password Reset Request', recipients=[email])
            reset_url = _frontend_url(f"/reset-password?token={reset.token}")
            msg.body = f"Reset your password: {reset_url}"
            mail.send(msg)
        except:
            pass
    # Always return success to prevent email enumeration.
    message = (
        'If that email is registered and password reset email delivery is configured, reset instructions will be sent.'
        if delivery_configured
        else 'Password reset email delivery is not configured in this build.'
    )
    return _success({
        'message': message,
        'delivery_configured': delivery_configured,
    })
@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Reset password using a token from the forgot-password flow."""
    data = request.get_json() or {}
    token = data.get('token')
    new_password = data.get('new_password')
    if not token or not new_password:
        return _error('Token and new password required', status_code=400)
    from app.models.user import EmailVerification
    verification = EmailVerification.query.filter_by(token=token, used=False).first()
    if not verification:
        return _error('Invalid or expired reset token', status_code=400)
    if verification.is_expired():
        return _error('Reset token has expired. Request a new one.', status_code=400)
    valid, msg = is_valid_password(new_password)
    if not valid:
        return _error(msg, status_code=400)
    user = User.query.get(verification.user_id)
    if not user:
        return _error('User not found', status_code=404)
    user.set_password(new_password)
    verification.used = True
    record_audit('password_reset', org_id=None, user_id=user.id, resource_type='user', resource_id=user.id)
    db.session.commit()
    return _success({'message': 'Password reset successfully. You can now log in.'})

@auth_bp.route('/change-password', methods=['POST'])
@jwt_required()
def change_password():
    """Change password."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return _error('User not found', status_code=404)
    data = request.get_json() or {}
    if not user.check_password(data.get('current_password')):
        record_audit_safely('password_change_failed', org_id=None, user_id=user.id, resource_type='user',
                            resource_id=user.id, outcome='failure')
        return _error('Current password incorrect', status_code=400)
    valid, msg = is_valid_password(data.get('new_password'))
    if not valid:
        return _error(msg, status_code=400)
    user.set_password(data['new_password'])
    record_audit('password_changed', org_id=None, user_id=user.id, resource_type='user', resource_id=user.id)
    db.session.commit()
    return _success({'message': 'Password changed successfully'})
