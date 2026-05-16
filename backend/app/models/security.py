from datetime import datetime
from enum import Enum
from app import db
class ThreatSeverity(Enum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'
class ThreatType(Enum):
    DDoS = 'ddos'
    BRUTE_FORCE = 'brute_force'
    PORT_SCAN = 'port_scan'
    SQL_INJECTION = 'sql_injection'
    XSS = 'xss'
    MALWARE = 'malware'
    UNAUTHORIZED_ACCESS = 'unauthorized_access'
    PRIVILEGE_ESCALATION = 'privilege_escalation'
    DATA_EXFILTRATION = 'data_exfiltration'
    SUSPICIOUS_BEHAVIOR = 'suspicious_behavior'
class SecurityLog(db.Model):
    """Security event logs."""
    __tablename__ = 'security_logs'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    event_type = db.Column(db.String(100), nullable=False)
    severity = db.Column(
        db.Enum(ThreatSeverity, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=ThreatSeverity.LOW
    )
    source_ip = db.Column(db.String(15))
    destination_ip = db.Column(db.String(15))
    resource_id = db.Column(db.String(50))  # VM or DB ID
    description = db.Column(db.Text)
    raw_data = db.Column(db.JSON)  # Full log data
    acknowledged = db.Column(db.Boolean, default=False)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    acknowledged_at = db.Column(db.DateTime)
    def to_dict(self):
        raw_data = self.raw_data if isinstance(self.raw_data, dict) else {}
        return {
            'id': self.id,
            'org_id': self.organization_id,
            'organization_id': self.organization_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'event_type': self.event_type,
            'severity': self.severity.value if self.severity else None,
            'source_ip': self.source_ip,
            'destination_ip': self.destination_ip,
            'resource_id': self.resource_id,
            'description': self.description,
            'acknowledged': self.acknowledged,
            'simulation': bool(raw_data.get('simulation')),
            'model_source': raw_data.get('model_source') or raw_data.get('source'),
            'alert_rule_id': raw_data.get('alert_rule_id'),
            'alert_rule_name': raw_data.get('alert_rule_name'),
            'action_type': raw_data.get('action_type'),
            'action_status': raw_data.get('action_status'),
            'action_result': raw_data.get('action_result'),
            'threat_id': raw_data.get('threat_id'),
        }
class ThreatDetection(db.Model):
    """AI-detected threats."""
    __tablename__ = 'threat_detections'
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    detected_at = db.Column(db.DateTime, default=datetime.utcnow)
    threat_type = db.Column(
        db.Enum(ThreatType, values_callable=lambda x: [e.value for e in x], native_enum=False),
        nullable=False
    )
    severity = db.Column(
        db.Enum(ThreatSeverity, values_callable=lambda x: [e.value for e in x], native_enum=False),
        nullable=False
    )
    confidence_score = db.Column(db.Float, nullable=False)  # 0.0 to 1.0
    affected_resources = db.Column(db.JSON)  # List of resource IDs
    attack_vectors = db.Column(db.JSON)  # Details of attack
    network_traffic_snapshot = db.Column(db.JSON)  # Traffic data at detection
    # ML Model info
    model_version = db.Column(db.String(20))
    detection_pattern = db.Column(db.Text)  # What pattern triggered detection
    # Status
    status = db.Column(db.String(20), default='active')  # active, contained, resolved, false_positive
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    def to_dict(self):
        return {
            'id': self.id,
            'org_id': self.organization_id,
            'organization_id': self.organization_id,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'threat_type': self.threat_type.value if self.threat_type else None,
            'severity': self.severity.value if self.severity else None,
            'confidence_score': round(self.confidence_score, 4),
            'affected_resources': self.affected_resources,
            'status': self.status,
            'attack_vectors': self.attack_vectors,
            'model_version': self.model_version,
            'detection_pattern': self.detection_pattern,
        }
class RemediationAction(db.Model):
    """Automated remediation actions."""
    __tablename__ = 'remediation_actions'
    id = db.Column(db.Integer, primary_key=True)
    threat_id = db.Column(db.Integer, db.ForeignKey('threat_detections.id'), nullable=False)
    action_type = db.Column(db.String(100), nullable=False)  # block_ip, isolate_resource, scale_up, etc.
    executed_at = db.Column(db.DateTime, default=datetime.utcnow)
    executed_by = db.Column(db.String(50))  # 'system' or user_id
    status = db.Column(db.String(20), default='pending')  # pending, success, failed
    details = db.Column(db.JSON)  # Action parameters
    result = db.Column(db.Text)  # Outcome description
    requires_approval = db.Column(db.Boolean, default=False)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    threat = db.relationship('ThreatDetection', backref='remediations')
    def to_dict(self):
        return {
            'id': self.id,
            'action_type': self.action_type,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'status': self.status,
            'details': self.details,
            'result': self.result,
            'requires_approval': self.requires_approval
        }


class AlertRule(db.Model):
    """Org-scoped alert rules applied to newly persisted threats."""

    __tablename__ = 'alert_rules'

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    condition_field = db.Column(db.String(50), nullable=False)
    condition_operator = db.Column(db.String(50), nullable=False)
    condition_value = db.Column(db.String(255), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    trigger_count = db.Column(db.Integer, default=0, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'organization_id': self.organization_id,
            'org_id': self.organization_id,
            'name': self.name,
            'description': self.description,
            'condition': {
                'field': self.condition_field,
                'operator': self.condition_operator,
                'value': self.condition_value,
            },
            'action_type': self.action_type,
            'is_active': self.is_active,
            'trigger_count': self.trigger_count,
            'created_by': self.created_by,
            'updated_by': self.updated_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
