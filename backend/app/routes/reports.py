import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from app.models.cost import CostRecord
from app.models.organization import Organization, OrganizationMember
from app.models.security import SecurityLog, ThreatDetection

reports_bp = Blueprint('reports', __name__)


def _resolve_org_id_from_request(payload=None):
    if isinstance(payload, dict):
        return payload.get('organization_id') or payload.get('org_id')
    return request.args.get('organization_id', type=int) or request.args.get('org_id', type=int)


def _require_org_membership(user_id, org_id):
    if org_id is None:
        return None
    return OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()


def _infer_plan(max_resources):
    if max_resources is None:
        return 'starter'
    if max_resources >= 200:
        return 'enterprise'
    if max_resources >= 100:
        return 'pro'
    return 'starter'


def _cost_records_for_org(org_id):
    return (
        CostRecord.query
        .filter_by(organization_id=org_id)
        .order_by(CostRecord.date.asc(), CostRecord.hour.asc(), CostRecord.id.asc())
        .all()
    )


def _threats_for_org(org_id):
    return (
        ThreatDetection.query
        .filter_by(organization_id=org_id)
        .order_by(ThreatDetection.detected_at.desc(), ThreatDetection.id.desc())
        .all()
    )


def _security_logs_for_org(org_id):
    return (
        SecurityLog.query
        .filter_by(organization_id=org_id)
        .order_by(SecurityLog.timestamp.desc(), SecurityLog.id.desc())
        .all()
    )


def _cost_trend_summary(cost_records):
    today = datetime.utcnow().date()
    current_start = today - timedelta(days=6)
    previous_start = current_start - timedelta(days=7)
    previous_end = current_start - timedelta(days=1)

    current_total = sum(record.total_cost for record in cost_records if current_start <= record.date <= today)
    previous_total = sum(record.total_cost for record in cost_records if previous_start <= record.date <= previous_end)

    delta = round(current_total - previous_total, 2)
    return {
        'current_period_label': f'{current_start.isoformat()} to {today.isoformat()}',
        'previous_period_label': f'{previous_start.isoformat()} to {previous_end.isoformat()}',
        'current_total': round(current_total, 2),
        'previous_total': round(previous_total, 2),
        'delta': delta,
    }


def _security_trend_summary(threats):
    today = datetime.utcnow().date()
    current_start = today - timedelta(days=6)
    previous_start = current_start - timedelta(days=7)
    previous_end = current_start - timedelta(days=1)

    current_total = sum(1 for threat in threats if threat.detected_at and current_start <= threat.detected_at.date() <= today)
    previous_total = sum(1 for threat in threats if threat.detected_at and previous_start <= threat.detected_at.date() <= previous_end)

    return {
        'current_period_label': f'{current_start.isoformat()} to {today.isoformat()}',
        'previous_period_label': f'{previous_start.isoformat()} to {previous_end.isoformat()}',
        'current_total': current_total,
        'previous_total': previous_total,
        'delta': current_total - previous_total,
    }


def _build_summary_pdf(org_id):
    org = Organization.query.get(org_id)
    cost_records = _cost_records_for_org(org_id)
    threats = _threats_for_org(org_id)
    logs = _security_logs_for_org(org_id)

    total_spend = round(sum(record.total_cost for record in cost_records), 2)
    active_threats = sum(1 for threat in threats if threat.status == 'active')
    cost_trend = _cost_trend_summary(cost_records)
    security_trend = _security_trend_summary(threats)

    rows = [
        ['Organization', org.name if org else f'Organization #{org_id}'],
        ['Plan', _infer_plan(org.max_resources) if org else 'starter'],
        ['Resources', str((len(org.resources) + len(org.databases)) if org else 0)],
        ['Members', str(len(org.members)) if org else 0],
        ['Lifetime Cost Records', str(len(cost_records))],
        ['Lifetime Spend', f'${total_spend:.2f}'],
        ['Threat Detections', str(len(threats))],
        ['Active Threats', str(active_threats)],
        ['Security Logs', str(len(logs))],
        ['Cost Trend (7d)', f'${cost_trend["current_total"]:.2f} vs ${cost_trend["previous_total"]:.2f}'],
        ['Threat Trend (7d)', f'{security_trend["current_total"]} vs {security_trend["previous_total"]}'],
    ]
    return _build_pdf_document(
        f'Organization Summary Report - {org.name if org else f"Org {org_id}"}',
        [
            ('Summary', ['Metric', 'Value'], rows, colors.grey),
            (
                'Notes',
                ['Topic', 'Details'],
                [[
                    'Report scope',
                    'This PDF uses persisted organization, cost, threat, and security log data only.',
                ]],
                colors.lightgrey,
            ),
        ],
    )


def _build_cost_pdf(org_id):
    org = Organization.query.get(org_id)
    cost_records = _cost_records_for_org(org_id)
    total_spend = round(sum(record.total_cost for record in cost_records), 2)
    by_service = defaultdict(float)
    for record in cost_records:
        by_service[record.resource_type] += float(record.total_cost or 0.0)

    trend = _cost_trend_summary(cost_records)
    summary_rows = [
        ['Organization', org.name if org else f'Organization #{org_id}'],
        ['Cost records', str(len(cost_records))],
        ['Lifetime spend', f'${total_spend:.2f}'],
        ['Current 7-day spend', f'${trend["current_total"]:.2f}'],
        ['Previous 7-day spend', f'${trend["previous_total"]:.2f}'],
        ['Trend delta', f'${trend["delta"]:.2f}'],
    ]
    service_rows = [[service, f'${round(amount, 2):.2f}'] for service, amount in sorted(by_service.items())]
    if not service_rows:
        service_rows = [['No cost records', '$0.00']]

    record_rows = [[
        record.date.isoformat() if record.date else '',
        str(record.hour) if record.hour is not None else '',
        record.resource_id,
        record.resource_type,
        f'${float(record.total_cost or 0.0):.2f}',
    ] for record in cost_records[-25:]]
    if not record_rows:
        record_rows = [['', '', 'No cost records', '', '$0.00']]

    return _build_pdf_document(
        f'Cost Summary Report - {org.name if org else f"Org {org_id}"}',
        [
            ('Summary', ['Metric', 'Value'], summary_rows, colors.grey),
            ('By Service', ['Service', 'Spend'], service_rows, colors.lightblue),
            ('Recent Records', ['Date', 'Hour', 'Resource ID', 'Type', 'Total Cost'], record_rows, colors.lightgrey),
        ],
    )


def _build_security_pdf(org_id):
    org = Organization.query.get(org_id)
    threats = _threats_for_org(org_id)
    logs = _security_logs_for_org(org_id)
    trend = _security_trend_summary(threats)
    active_threats = sum(1 for threat in threats if threat.status == 'active')

    summary_rows = [
        ['Organization', org.name if org else f'Organization #{org_id}'],
        ['Threat detections', str(len(threats))],
        ['Active threats', str(active_threats)],
        ['Security logs', str(len(logs))],
        ['Current 7-day detections', str(trend['current_total'])],
        ['Previous 7-day detections', str(trend['previous_total'])],
        ['Trend delta', str(trend['delta'])],
    ]

    threat_rows = [[
        threat.detected_at.strftime('%Y-%m-%d %H:%M') if threat.detected_at else '',
        threat.threat_type.value if threat.threat_type else 'unknown',
        threat.severity.value if threat.severity else 'unknown',
        threat.status,
        f'{float(threat.confidence_score or 0.0):.2f}',
    ] for threat in threats[:25]]
    if not threat_rows:
        threat_rows = [['', 'No detected threats', '', '', '']]

    log_rows = [[
        log.timestamp.strftime('%Y-%m-%d %H:%M') if log.timestamp else '',
        log.event_type,
        log.severity.value if log.severity else 'low',
        log.description or '',
    ] for log in logs[:25]]
    if not log_rows:
        log_rows = [['', 'No security logs', '', '']]

    return _build_pdf_document(
        f'Security Summary Report - {org.name if org else f"Org {org_id}"}',
        [
            ('Summary', ['Metric', 'Value'], summary_rows, colors.red),
            ('Recent Threats', ['Detected At', 'Type', 'Severity', 'Status', 'Confidence'], threat_rows, colors.salmon),
            ('Recent Security Logs', ['Timestamp', 'Event', 'Severity', 'Description'], log_rows, colors.lightgrey),
        ],
    )


def _build_pdf_document(title_text, sections):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(title_text, styles['Heading1']),
        Spacer(1, 12),
        Paragraph(f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}', styles['Normal']),
        Spacer(1, 12),
    ]

    for section_title, headers, rows, header_color in sections:
        story.append(Paragraph(section_title, styles['Heading2']))
        story.append(Spacer(1, 6))
        table = Table([headers] + rows)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), header_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _csv_response(filename, headers, rows):
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)

    payload = BytesIO(csv_buffer.getvalue().encode('utf-8'))
    payload.seek(0)
    return send_file(
        payload,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )


@reports_bp.route('/summary.pdf', methods=['GET'])
@jwt_required()
def summary_pdf():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id_from_request()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403

    return send_file(
        _build_summary_pdf(org_id),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'summary_report_{datetime.utcnow().strftime("%Y%m%d")}.pdf',
    )


@reports_bp.route('/cost.pdf', methods=['GET'])
@jwt_required()
def cost_pdf():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id_from_request()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403

    return send_file(
        _build_cost_pdf(org_id),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'cost_report_{datetime.utcnow().strftime("%Y%m%d")}.pdf',
    )


@reports_bp.route('/security.pdf', methods=['GET'])
@jwt_required()
def security_pdf():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id_from_request()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403

    return send_file(
        _build_security_pdf(org_id),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'security_report_{datetime.utcnow().strftime("%Y%m%d")}.pdf',
    )


@reports_bp.route('/cost.csv', methods=['GET'])
@jwt_required()
def cost_csv():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id_from_request()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403

    cost_records = _cost_records_for_org(org_id)
    rows = [[
        record.date.isoformat() if record.date else '',
        record.hour if record.hour is not None else '',
        record.resource_id,
        record.resource_type,
        record.compute_cost or 0.0,
        record.storage_cost or 0.0,
        record.network_cost or 0.0,
        record.total_cost or 0.0,
        record.cpu_avg or 0.0,
        record.memory_avg or 0.0,
    ] for record in cost_records]

    return _csv_response(
        f'cost_export_{datetime.utcnow().strftime("%Y%m%d")}.csv',
        [
            'date',
            'hour',
            'resource_id',
            'resource_type',
            'compute_cost',
            'storage_cost',
            'network_cost',
            'total_cost',
            'cpu_avg',
            'memory_avg',
        ],
        rows,
    )


@reports_bp.route('/security.csv', methods=['GET'])
@jwt_required()
def security_csv():
    user_id = get_jwt_identity()
    org_id = _resolve_org_id_from_request()
    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403

    threats = _threats_for_org(org_id)
    rows = [[
        threat.detected_at.isoformat() if threat.detected_at else '',
        threat.threat_type.value if threat.threat_type else '',
        threat.severity.value if threat.severity else '',
        threat.confidence_score or 0.0,
        threat.status,
        '|'.join(threat.affected_resources or []),
        threat.detection_pattern or '',
    ] for threat in threats]

    return _csv_response(
        f'security_export_{datetime.utcnow().strftime("%Y%m%d")}.csv',
        [
            'detected_at',
            'threat_type',
            'severity',
            'confidence_score',
            'status',
            'affected_resources',
            'detection_pattern',
        ],
        rows,
    )


@reports_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_report():
    """Legacy PDF generation endpoint kept for existing frontend wiring."""
    payload = request.get_json() or {}
    report_type = (payload.get('report_type') or 'summary').strip().lower()
    org_id = _resolve_org_id_from_request(payload)
    user_id = get_jwt_identity()

    member = _require_org_membership(user_id, org_id)
    if not member:
        return jsonify({'error': 'Access denied'}), 403

    if report_type == 'cost':
        buffer = _build_cost_pdf(org_id)
    elif report_type == 'security':
        buffer = _build_security_pdf(org_id)
    else:
        buffer = _build_summary_pdf(org_id)

    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{report_type}_report_{datetime.utcnow().strftime("%Y%m%d")}.pdf',
    )


@reports_bp.route('/export/csv', methods=['GET'])
@jwt_required()
def export_csv():
    """Legacy CSV endpoint kept for existing frontend wiring."""
    export_type = (request.args.get('type') or 'costs').strip().lower()
    if export_type == 'security':
        return security_csv()
    if export_type in {'cost', 'costs'}:
        return cost_csv()
    return jsonify({'error': 'Invalid export type'}), 400
