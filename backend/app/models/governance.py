from datetime import datetime
from enum import Enum
from sqlalchemy import event

from app import db
class PolicyStatus(Enum):
    DRAFT = 'draft'
    ACTIVE = 'active'
    DISABLED = 'disabled'
class Policy(db.Model):
    """Governance policies."""
    __tablename__ = 'policies'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    # Policy content
    natural_language_rule = db.Column(db.Text, nullable=False)  # Stored rule expression / legacy field name
    compiled_rule = db.Column(db.JSON)  # Machine-readable version
    policy_type = db.Column(db.String(50))  # naming, tagging, security, cost, compliance
    # Enforcement
    auto_remediate = db.Column(db.Boolean, default=False)
    severity = db.Column(db.String(20), default='warning')  # info, warning, critical
    status = db.Column(
        db.Enum(PolicyStatus, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=PolicyStatus.DRAFT
    )
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    def to_dict(self):
        return {
            'id': self.id,
            'org_id': self.organization_id,
            'organization_id': self.organization_id,
            'name': self.name,
            'description': self.description,
            'policy_rule': self.natural_language_rule,
            'natural_language_rule': self.natural_language_rule,
            'compiled_rule': self.compiled_rule,
            'policy_type': self.policy_type,
            'auto_remediate': self.auto_remediate,
            'severity': self.severity,
            'status': self.status.value if self.status else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
class ComplianceCheck(db.Model):
    """Policy compliance check results."""
    __tablename__ = 'compliance_checks'
    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey('policies.id'), nullable=False)
    resource_id = db.Column(db.String(50), nullable=False)
    resource_type = db.Column(db.String(20), nullable=False)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_compliant = db.Column(db.Boolean, default=False)
    violation_details = db.Column(db.JSON)
    remediation_applied = db.Column(db.Boolean, default=False)
    remediation_details = db.Column(db.JSON)
    policy = db.relationship('Policy', backref='checks')

    def to_dict(self):
        return {
            'id': self.id,
            'policy_id': self.policy_id,
            'policy_name': self.policy.name if self.policy else None,
            'org_id': self.policy.organization_id if self.policy else None,
            'organization_id': self.policy.organization_id if self.policy else None,
            'resource_id': self.resource_id,
            'resource_type': self.resource_type,
            'checked_at': self.checked_at.isoformat() if self.checked_at else None,
            'is_compliant': self.is_compliant,
            'violation_details': self.violation_details,
            'remediation_applied': self.remediation_applied,
            'remediation_details': self.remediation_details,
        }
class AuditLog(db.Model):
    """Append-only audit trail (Module 11).

    Rows are written only through ``app.services.audit_service.record_audit``.
    Updates and deletes through the ORM are rejected by the listeners below; no API
    route edits or deletes audit rows. ``organization_id`` is NULL for account-level
    events (login, password change, settings) that do not belong to one tenant.
    """
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    action = db.Column(db.String(100), nullable=False)  # e.g. vm_created, login_succeeded
    category = db.Column(db.String(30), index=True)  # auth, organization, resource, security, ...
    outcome = db.Column(db.String(20), default='success')  # success, failure, denied
    resource_type = db.Column(db.String(50))  # vm, database, policy, etc.
    resource_id = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # Details
    old_values = db.Column(db.JSON)
    new_values = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    session_id = db.Column(db.String(255))
    # Compliance
    compliance_relevant = db.Column(db.Boolean, default=False)
    retention_until = db.Column(db.DateTime)

    actor = db.relationship('User', foreign_keys=[user_id], lazy='joined')
    # The organization timeline is filtered by organization and ordered by time; this composite
    # index also serves organization-only lookups (leftmost column).
    __table_args__ = (db.Index('ix_audit_logs_org_ts', 'organization_id', 'timestamp'),)

    def to_dict(self):
        actor = self.actor
        return {
            'id': self.id,
            'org_id': self.organization_id,
            'organization_id': self.organization_id,
            'user_id': self.user_id,
            'actor': (
                {'id': actor.id, 'name': f'{actor.first_name} {actor.last_name}'.strip()}
                if actor else None
            ),
            'action': self.action,
            'category': self.category,
            'outcome': self.outcome or 'success',
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'ip_address': self.ip_address,
            'compliance_relevant': self.compliance_relevant,
            'changes': {
                'old': self.old_values,
                'new': self.new_values
            }
        }


@event.listens_for(AuditLog, 'before_update')
def _audit_log_is_immutable(mapper, connection, target):
    raise ValueError('Audit log entries are append-only and cannot be modified')


@event.listens_for(AuditLog, 'before_delete')
def _audit_log_is_undeletable(mapper, connection, target):
    raise ValueError('Audit log entries are append-only and cannot be deleted')
