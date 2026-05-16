from datetime import datetime, timedelta
from app import db
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
class User(db.Model):
    """User account model."""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    email_verified = db.Column(db.Boolean, default=False)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(255))
    # Relationships
    profile = db.relationship('UserProfile', backref='user', uselist=False)
    organizations = db.relationship(
        'OrganizationMember',
        back_populates='user',
        foreign_keys='OrganizationMember.user_id'
    )
    owned_organizations = db.relationship(
        'Organization',
        backref='owner',
        foreign_keys='Organization.owner_id'
    )
    settings = db.relationship('UserSettings', backref='user', uselist=False)
    def set_password(self, password):
        """Hash and set user password."""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256:100000')
    def check_password(self, password):
        """Verify password against hash."""
        return check_password_hash(self.password_hash, password)
    def generate_verification_token(self):
        """Generate email verification token."""
        return secrets.token_urlsafe(32)
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'is_active': self.is_active,
            'email_verified': self.email_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
class UserProfile(db.Model):
    """Extended user profile information."""
    __tablename__ = 'user_profiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    avatar_url = db.Column(db.String(500))
    phone = db.Column(db.String(20))
    department = db.Column(db.String(100))
    job_title = db.Column(db.String(100))
    timezone = db.Column(db.String(50), default='UTC')
    bio = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class EmailVerification(db.Model):
    """Email verification tokens."""
    __tablename__ = 'email_verifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    def is_expired(self):
        return datetime.utcnow() > self.expires_at
    @staticmethod
    def create_token(user_id):
        """Create new verification token."""
        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(hours=24)
        return EmailVerification(
            user_id=user_id,
            token=token,
            expires_at=expires
        )


class TokenBlacklist(db.Model):
    """Blacklisted JWT tokens for logout/invalidation."""
    __tablename__ = 'token_blacklist'
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(255), unique=True, nullable=False, index=True)
    token_type = db.Column(db.String(20), default='refresh')
    blacklisted_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def is_blacklisted(jti, token_type='refresh'):
        return TokenBlacklist.query.filter_by(jti=jti, token_type=token_type).first() is not None
