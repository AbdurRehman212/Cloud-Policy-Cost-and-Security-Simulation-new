from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db, socketio
from app.models.security import SecurityLog, ThreatDetection, RemediationAction, ThreatType, ThreatSeverity
from app.models.organization import OrganizationMember
from datetime import datetime, timedelta

try:
    from app.ai_models.threat_detector import threat_detector
except ImportError:
    threat_detector = None

try:
    from app.ai_models.remediation_agent import remediation_agent
except ImportError:
    remediation_agent = None

security_bp = Blueprint('security', __name__)


THREAT_TYPE_MAP = {
    'ddos': ThreatType.DDoS,
    'brute_force': ThreatType.BRUTE_FORCE,
    'port_scan': ThreatType.PORT_SCAN,
    'sql_injection': ThreatType.SQL_INJECTION,
    'xss': ThreatType.XSS,
    'malware': ThreatType.MALWARE,
    'unauthorized_access': ThreatType.UNAUTHORIZED_ACCESS,
    'privilege_escalation': ThreatType.PRIVILEGE_ESCALATION,
    'data_exfiltration': ThreatType.DATA_EXFILTRATION,
    'suspicious_behavior': ThreatType.SUSPICIOUS_BEHAVIOR,
}


def basic_threat_analysis(metrics):
    """Fallback threat scoring for the P1 mid structure."""
    requests_per_minute = metrics.get('requests_per_minute', 0)
    error_rate = metrics.get('error_rate', 0)
    avg_latency_ms = metrics.get('avg_latency_ms', 0)

    is_threat = (
        requests_per_minute > 5000
        or error_rate > 0.15
        or avg_latency_ms > 300
    )
    threat_type = 'ddos' if requests_per_minute > 5000 else 'brute_force'
    confidence = 0.9 if is_threat else 0.2

    return {
        'is_threat': is_threat,
        'threat_type': threat_type,
        'confidence': confidence,
        'source': 'heuristic_fallback',
    }


def resolve_threat_type(threat_name):
    """Map string threat labels to ThreatType enum members safely."""
    normalized = (threat_name or '').strip().lower()
    return THREAT_TYPE_MAP.get(normalized, ThreatType.SUSPICIOUS_BEHAVIOR)


def build_attack_scenario(attack_type, intensity='medium'):
    """Build a realistic attack scenario without fabricating a training dataset."""
    attack_type = (attack_type or 'ddos').strip().lower()
    intensity = (intensity or 'medium').strip().lower()

    if attack_type == 'brute_force':
        base = {
            'requests_per_minute': 1100,
            'avg_latency_ms': 180,
            'error_rate': 0.09,
            'bytes_in': 420000,
            'bytes_out': 760000,
            'active_connections': 120,
            'auth_failures': 18,
        }
        increments = [
            {'requests_per_minute': 0, 'avg_latency_ms': 0, 'error_rate': 0.0, 'auth_failures': 0},
            {'requests_per_minute': 180, 'avg_latency_ms': 20, 'error_rate': 0.01, 'auth_failures': 6},
            {'requests_per_minute': 320, 'avg_latency_ms': 35, 'error_rate': 0.015, 'auth_failures': 10},
        ]
    else:
        scale = {'low': 1.0, 'medium': 1.5, 'high': 2.2}.get(intensity, 1.5)
        base = {
            'requests_per_minute': int(4200 * scale),
            'avg_latency_ms': int(240 * scale),
            'error_rate': round(0.12 * scale, 4),
            'bytes_in': int(2_400_000 * scale),
            'bytes_out': int(6_500_000 * scale),
            'active_connections': int(180 * scale),
            'auth_failures': 4,
        }
        increments = [
            {'requests_per_minute': 0, 'avg_latency_ms': 0, 'error_rate': 0.0, 'auth_failures': 0},
            {'requests_per_minute': 900, 'avg_latency_ms': 40, 'error_rate': 0.01, 'auth_failures': 1},
            {'requests_per_minute': 1700, 'avg_latency_ms': 70, 'error_rate': 0.02, 'auth_failures': 2},
        ]

    scenario = []
    for step in increments:
        snapshot = base.copy()
        for key, value in step.items():
            snapshot[key] = snapshot.get(key, 0) + value
        scenario.append(snapshot)
    return scenario
@security_bp.route('/logs', methods=['GET'])
@jwt_required()
def get_security_logs():
    """Get security logs for organization."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    # Filters
    severity = request.args.get('severity')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    query = SecurityLog.query.filter_by(organization_id=org_id)
    if severity:
        query = query.filter_by(severity=severity)
    if start_date:
        try:
            query = query.filter(SecurityLog.timestamp >= datetime.fromisoformat(start_date))
        except ValueError:
            return jsonify({'error': 'Invalid start_date format'}), 400
    if end_date:
        try:
            query = query.filter(SecurityLog.timestamp <= datetime.fromisoformat(end_date))
        except ValueError:
            return jsonify({'error': 'Invalid end_date format'}), 400
    logs = query.order_by(SecurityLog.timestamp.desc()).limit(1000).all()
    return jsonify({
        'logs': [log.to_dict() for log in logs],
        'total': len(logs)
    }), 200
@security_bp.route('/threats', methods=['GET'])
@jwt_required()
def get_threats():
    """Get detected threats."""
    user_id = get_jwt_identity()
    org_id = request.args.get('organization_id', type=int)
    if org_id is None:
        org_id = request.args.get('org_id', type=int)
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    status = (request.args.get('status') or 'all').strip().lower()
    query = ThreatDetection.query.filter_by(organization_id=org_id)
    if status not in {'all', 'any', '*'}:
        query = query.filter_by(status=status)
    threats = query.order_by(ThreatDetection.detected_at.desc()).all()
    return jsonify({
        'threats': [t.to_dict() for t in threats],
        'summary': {
            'total_active': len([t for t in threats if t.status == 'active']),
            'by_severity': {
                'critical': len([t for t in threats if t.severity == ThreatSeverity.CRITICAL]),
                'high': len([t for t in threats if t.severity == ThreatSeverity.HIGH])
            }
        }
    }), 200
@security_bp.route('/analyze', methods=['POST'])
@jwt_required()
def analyze_traffic():
    """Analyze traffic for threats (simulated)."""
    user_id = get_jwt_identity()
    data = request.get_json()
    org_id = data.get('organization_id')
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    # Simulate current metrics
    current_metrics = {
        'requests_per_minute': data.get('requests_per_minute', 1000),
        'avg_latency_ms': data.get('avg_latency_ms', 50),
        'error_rate': data.get('error_rate', 0.01),
        'bytes_in': data.get('bytes_in', 1500000),
        'bytes_out': data.get('bytes_out', 8000000),
        'active_connections': data.get('active_connections', 100)
    }
    # Get prediction
    if threat_detector:
        result = threat_detector.real_time_monitor(current_metrics)
    else:
        result = basic_threat_analysis(current_metrics)
    # If threat detected, create record
    if result.get('is_threat'):
        threat = ThreatDetection(
            organization_id=org_id,
            threat_type=resolve_threat_type(result['threat_type']),
            severity=ThreatSeverity.HIGH if result['confidence'] > 0.8 else ThreatSeverity.MEDIUM,
            confidence_score=result['confidence'],
            affected_resources=data.get('resource_ids', []),
            attack_vectors={'metrics': current_metrics},
            network_traffic_snapshot=current_metrics
        )
        db.session.add(threat)
        db.session.commit()
        # Trigger remediation if auto-remediation enabled
        if data.get('auto_remediate'):
            from app.models.resources import VirtualMachine
            resource = VirtualMachine.query.filter_by(
                instance_id=data.get('resource_id')
            ).first()
            if resource and remediation_agent:
                remediation_result = remediation_agent.remediate(
                    {
                        'type': result['threat_type'],
                        'severity': 'high',
                        'confidence': result['confidence']
                    },
                    resource.to_dict()
                )
                # Create remediation record
                for action in remediation_result['results']:
                    rem = RemediationAction(
                        threat_id=threat.id,
                        action_type=action['action'],
                        executed_by='system',
                        status=action['status'],
                        details=action['details'],
                        requires_approval=remediation_result['requires_approval']
                    )
                    db.session.add(rem)
                db.session.commit()
                result['remediation'] = remediation_result
    return jsonify(result), 200
@security_bp.route('/threats/<int:threat_id>/resolve', methods=['POST'])
@jwt_required()
def resolve_threat(threat_id):
    """Mark threat as resolved."""
    user_id = get_jwt_identity()
    threat = ThreatDetection.query.get_or_404(threat_id)
    member = OrganizationMember.query.filter_by(
        organization_id=threat.organization_id,
        user_id=user_id
    ).first()
    if not member or member.role not in ['admin', 'owner']:
        return jsonify({'error': 'Insufficient permissions'}), 403
    threat.status = 'resolved'
    threat.resolved_at = datetime.utcnow()
    threat.resolved_by = user_id
    db.session.commit()
    return jsonify({'message': 'Threat marked as resolved'}), 200
@security_bp.route('/simulate', methods=['POST'])
@security_bp.route('/simulate-attack', methods=['POST'])
@jwt_required()
def simulate_attack():
    """Simulate attack for training purposes."""
    user_id = get_jwt_identity()
    data = request.get_json()
    org_id = data.get('organization_id') or data.get('org_id')
    member = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    attack_type = data.get('attack_type', 'ddos')
    target_resource = data.get('target_resource')
    attack_scenario = build_attack_scenario(attack_type, data.get('intensity', 'medium'))
    predictions = []
    for row in attack_scenario:
        if threat_detector:
            pred = threat_detector.real_time_monitor(row)
        else:
            pred = basic_threat_analysis(row)
        predictions.append(pred)
    # Create threat record
    threat = ThreatDetection(
        organization_id=org_id,
        threat_type=resolve_threat_type(attack_type),
        severity=ThreatSeverity.HIGH,
        confidence_score=0.95,
        affected_resources=[target_resource] if target_resource else [],
        attack_vectors={'scenario': attack_scenario, 'attack_type': attack_type},
        network_traffic_snapshot={'predictions': predictions[:5]},
        status='contained'  # Auto-contained in simulation
    )
    db.session.add(threat)
    db.session.commit()

    # Emit socket event so Security.jsx table updates in real time
    socketio.emit(
        'threats:update',
        {'threat': threat.to_dict()},
        room=f'org_{org_id}',
        namespace='/metrics',
    )

    return jsonify({
        'message': f'{attack_type.upper()} attack simulated',
        'threat_id': threat.id,
        'attack_data_points': len(attack_scenario),
        'detections': len([p for p in predictions if p.get('is_threat')])
    }), 201
