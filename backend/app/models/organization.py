from datetime import datetime, timedelta
from app import db
import secrets
class Organization(db.Model):
    """Organization/Tenant model."""
    __tablename__ = 'organizations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    max_resources = db.Column(db.Integer, default=50)
    billing_email = db.Column(db.String(255))
    # Relationships
    members = db.relationship('OrganizationMember', back_populates='organization')
    resources = db.relationship('VirtualMachine', backref='organization')
    databases = db.relationship('Database', backref='organization')
    policies = db.relationship('Policy', backref='organization')
    budgets = db.relationship('Budget', backref='organization')
    def generate_slug(self):
        """Generate unique slug from name."""
        base = self.name.lower().replace(' ', '-')
        slug = base
        counter = 1
        while Organization.query.filter_by(slug=slug).first():
            slug = f"{base}-{counter}"
            counter += 1
        return slug
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'owner_id': self.owner_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active,
            'max_resources': self.max_resources,
            'member_count': len(self.members),
            'resource_count': len(self.resources) + len(self.databases)
        }
class OrganizationMember(db.Model):
    """Organization membership with roles."""
    __tablename__ = 'organization_members'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(50), default='member')  # owner, admin, member, viewer
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    invited_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    # Relationships
    organization = db.relationship('Organization', back_populates='members')
    user = db.relationship('User', back_populates='organizations', foreign_keys=[user_id])
    __table_args__ = (db.UniqueConstraint('organization_id', 'user_id'),)
    def to_dict(self):
        return {
            'id': self.id,
            'organization': self.organization.to_dict(),
            'role': self.role,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None
        }
class Invitation(db.Model):
    """Organization invitations."""
    __tablename__ = 'invitations'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    role = db.Column(db.String(50), default='member')
    invited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted = db.Column(db.Boolean, default=False)
    @staticmethod
    def create_invitation(organization_id, email, role, invited_by):
        """Create new invitation."""
        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(days=7)
        return Invitation(
            organization_id=organization_id,
            email=email,
            token=token,
            role=role,
            invited_by=invited_by,
            expires_at=expires
        )


def ensure_default_organization_membership(user):
    """Ensure a user has at least one organization membership.

    Returns a tuple of (organization, membership, created_new).
    This helper does not commit; callers control the transaction boundary.
    """
    existing_membership = (
        OrganizationMember.query
        .filter_by(user_id=user.id)
        .order_by(OrganizationMember.joined_at.asc(), OrganizationMember.id.asc())
        .first()
    )
    if existing_membership and existing_membership.organization:
        if not existing_membership.role:
            existing_membership.role = 'owner'
        return existing_membership.organization, existing_membership, False

    org_name = f"{(user.first_name or 'User').strip()}'s Cloud Workspace"
    organization = Organization(
        name=org_name,
        description='Personal cloud workspace for learning infrastructure management.',
        owner_id=user.id,
        billing_email=user.email,
        max_resources=100,
    )
    organization.slug = organization.generate_slug()
    db.session.add(organization)
    db.session.flush()

    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role='owner',
    )
    db.session.add(membership)
    from app.routes.resources import _ensure_default_security_groups
    _ensure_default_security_groups(organization.id)

    from app.models.resources import VPC, Subnet
    vpc = VPC(
        name='default-vpc',
        organization_id=organization.id,
        cidr_block='10.0.0.0/16',
        is_default=True,
    )
    db.session.add(vpc)
    db.session.flush()
    db.session.add(Subnet(
        name='public-subnet-1',
        vpc_id=vpc.id,
        organization_id=organization.id,
        cidr_block='10.0.1.0/24',
        subnet_type='public',
        availability_zone='us-east-1a',
    ))
    db.session.add(Subnet(
        name='private-subnet-1',
        vpc_id=vpc.id,
        organization_id=organization.id,
        cidr_block='10.0.2.0/24',
        subnet_type='private',
        availability_zone='us-east-1b',
    ))

    return organization, membership, True
