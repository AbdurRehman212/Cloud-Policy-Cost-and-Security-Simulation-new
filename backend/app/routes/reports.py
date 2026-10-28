import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from app.utils.rbac import active_membership
from app.models.cost import CostRecord
from app.models.governance import Policy
from app.models.organization import Organization, OrganizationMember
from app.models.security import SecurityLog, ThreatDetection
from app.services.governance_engine import governance_engine

reports_bp = Blueprint('reports', __name__)


def _resolve_org_id_from_request(payload=None):
    if isinstance(payload, dict):
        return payload.get('organization_id') or payload.get('org_id')
    return request.args.get('organization_id', type=int) or request.args.get('org_id', type=int)


def _require_org_membership(user_id, org_id):
    if org_id is None:
        return None
    return active_membership(user_id, org_id)


def _infer_plan(max_resources):
    if max_resources is None:
        return 'starter'
    if max_resources >= 200:
        return 'enterprise'
    if max_resources >= 100:
        return 'pro'
    return 'starter'


def _parse_range(source):
    """Read optional start_date/end_date (YYYY-MM-DD). Returns ((start, end), error)."""
    parsed = []
    for key in ('start_date', 'end_date'):
        raw = source.get(key)
        if not raw:
            parsed.append(None)
            continue
        try:
            parsed.append(datetime.strptime(str(raw), '%Y-%m-%d').date())
        except ValueError:
            return (None, None), f'{key} must be YYYY-MM-DD'
    if parsed[0] and parsed[1] and parsed[0] > parsed[1]:
        return (None, None), 'start_date must not be after end_date'
    return tuple(parsed), None


def _range_label(date_range):
    start, end = date_range or (None, None)
    if not start and not end:
        return 'All available data'
    return f'{start.isoformat() if start else "beginning"} to {end.isoformat() if end else "today"}'


def _day_bounds(date_range):
    start, end = date_range or (None, None)
    lo = datetime.combine(start, datetime.min.time()) if start else None
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time()) if end else None
    return lo, hi


def _cost_records_for_org(org_id, date_range=None):
    query = CostRecord.query.filter_by(organization_id=org_id)
    start, end = date_range or (None, None)
    if start:
        query = query.filter(CostRecord.date >= start)
    if end:
        query = query.filter(CostRecord.date <= end)
    return query.order_by(CostRecord.date.asc(), CostRecord.hour.asc(), CostRecord.id.asc()).all()


def _threats_for_org(org_id, date_range=None):
    query = ThreatDetection.query.filter_by(organization_id=org_id)
    lo, hi = _day_bounds(date_range)
    if lo:
        query = query.filter(ThreatDetection.detected_at >= lo)
    if hi:
        query = query.filter(ThreatDetection.detected_at < hi)
    return query.order_by(ThreatDetection.detected_at.desc(), ThreatDetection.id.desc()).all()


def _security_logs_for_org(org_id, date_range=None):
    query = SecurityLog.query.filter_by(organization_id=org_id)
    lo, hi = _day_bounds(date_range)
    if lo:
        query = query.filter(SecurityLog.timestamp >= lo)
    if hi:
        query = query.filter(SecurityLog.timestamp < hi)
    return query.order_by(SecurityLog.timestamp.desc(), SecurityLog.id.desc()).all()


def _governance_pdf_sections(org_id):
    state = governance_engine.get_latest_state(org_id)
    score = state['governance_score']
    policies = Policy.query.filter_by(organization_id=org_id).order_by(Policy.id.asc()).all()
    summary_rows = [
        ['Policies (total / active)', f'{len(policies)} / {sum(1 for p in policies if p.status and p.status.value == "active")}'],
        ['Last compliance run', state['last_checked_at'] or 'No compliance check has been run'],
        ['Governance score', f'{score["score"]:.1f} / 100' if state['evaluated'] else 'Not evaluated'],
        ['Open violations', str(len(state['violations']))],
        ['Score formula', score['formula']],
    ]
    breakdown_rows = [[
        item['policy_name'], str(item['severity']), str(item['weight']),
        str(item['resources_evaluated']), str(item['violations']), str(item['penalty_points']),
    ] for item in score['breakdown']] or [['No active policies', '', '', '', '', '']]
    violation_rows = [[
        v['policy_name'], str(v['severity']), f'{v["resource_type"]} {v["resource_id"]}', '; '.join(v['violations']),
    ] for v in state['violations'][:40]] or [['No open violations', '', '', '']]
    return [
        ('Governance Summary', ['Metric', 'Value'], summary_rows, colors.darkgreen),
        ('Score Breakdown', ['Policy', 'Severity', 'Weight', 'Checks', 'Violations', 'Penalty'], breakdown_rows, colors.grey),
        ('Open Violations', ['Policy', 'Severity', 'Resource', 'Details'], violation_rows, colors.salmon),
    ]


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


def _build_summary_pdf(org_id, date_range=None):
    org = Organization.query.get(org_id)
    cost_records = _cost_records_for_org(org_id, date_range)
    threats = _threats_for_org(org_id, date_range)
    logs = _security_logs_for_org(org_id, date_range)
    governance = governance_engine.get_latest_state(org_id)

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
        ['Governance Score', f'{governance["governance_score"]["score"]:.1f} / 100' if governance['evaluated'] else 'Not evaluated'],
        ['Open Policy Violations', str(len(governance['violations']))],
    ]
    return _build_pdf_document(
        f'Organization Summary Report - {org.name if org else f"Org {org_id}"}',
        subtitle=date_range,
        sections=[
            ('Summary', ['Metric', 'Value'], rows, colors.grey),
            (
                'Notes',
                ['Topic', 'Details'],
                [[
                    'Report scope',
                    'This PDF uses persisted organization, cost, threat, security log and governance data only.',
                ]],
                colors.lightgrey,
            ),
        ],
    )


def _build_cost_pdf(org_id, date_range=None):
    org = Organization.query.get(org_id)
    cost_records = _cost_records_for_org(org_id, date_range)
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
        subtitle=date_range,
        sections=[
            ('Summary', ['Metric', 'Value'], summary_rows, colors.grey),
            ('By Service', ['Service', 'Spend'], service_rows, colors.lightblue),
            ('Recent Records', ['Date', 'Hour', 'Resource ID', 'Type', 'Total Cost'], record_rows, colors.lightgrey),
        ],
    )


def _build_security_pdf(org_id, date_range=None):
    org = Organization.query.get(org_id)
    threats = _threats_for_org(org_id, date_range)
    logs = _security_logs_for_org(org_id, date_range)
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
        subtitle=date_range,
        sections=[
            ('Summary', ['Metric', 'Value'], summary_rows, colors.red),
            ('Recent Threats', ['Detected At', 'Type', 'Severity', 'Status', 'Confidence'], threat_rows, colors.salmon),
            ('Recent Security Logs', ['Timestamp', 'Event', 'Severity', 'Description'], log_rows, colors.lightgrey),
        ],
    )


def _build_governance_pdf(org_id):
    org = Organization.query.get(org_id)
    return _build_pdf_document(
        f'Governance Report - {org.name if org else f"Org {org_id}"}',
        subtitle=None,
        sections=_governance_pdf_sections(org_id),
    )


def _build_pdf_document(title_text, sections, subtitle=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(escape(title_text), styles['Heading1']),
        Spacer(1, 12),
        Paragraph(f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}', styles['Normal']),
        Paragraph(f'Period: {_range_label(subtitle)}', styles['Normal']),
        Paragraph('All figures come from simulated cloud resources and are not real cloud billing.', styles['Italic']),
        Spacer(1, 12),
    ]

    for section_title, headers, rows, header_color in sections:
        story.append(Paragraph(section_title, styles['Heading2']))
        story.append(Spacer(1, 6))
        header_cells = [
            Paragraph(f'<font color="white"><b>{escape(str(c))}</b></font>', styles['BodyText'])
            for c in headers
        ]
        body_rows = [[Paragraph(escape(str(c)), styles['BodyText']) for c in row] for row in rows]
        table = Table([header_cells] + body_rows, repeatRows=1)
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


def _csv_safe(cell):
    """Prefix text that a spreadsheet would execute as a formula."""
    if isinstance(cell, str) and cell[:1] in ('=', '+', '-', '@'):
        return "'" + cell
    return cell


def _csv_response(filename, headers, rows):
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_csv_safe(cell) for cell in row])

    payload = BytesIO(csv_buffer.getvalue().encode('utf-8'))
    payload.seek(0)
    return send_file(
        payload,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )


def _authorize():
    """Return (org_id, date_range, error_response)."""
    org_id = _resolve_org_id_from_request()
    if not _require_org_membership(get_jwt_identity(), org_id):
        return None, None, (jsonify({'error': 'Access denied'}), 403)
    date_range, error = _parse_range(request.args)
    if error:
        return None, None, (jsonify({'error': error}), 400)
    return org_id, date_range, None


def _pdf_response(buffer, name):
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{name}_report_{datetime.utcnow().strftime("%Y%m%d")}.pdf',
    )


@reports_bp.route('/summary.pdf', methods=['GET'])
@jwt_required()
def summary_pdf():
    org_id, date_range, error = _authorize()
    if error:
        return error
    return _pdf_response(_build_summary_pdf(org_id, date_range), 'summary')


@reports_bp.route('/cost.pdf', methods=['GET'])
@jwt_required()
def cost_pdf():
    org_id, date_range, error = _authorize()
    if error:
        return error
    return _pdf_response(_build_cost_pdf(org_id, date_range), 'cost')


@reports_bp.route('/security.pdf', methods=['GET'])
@jwt_required()
def security_pdf():
    org_id, date_range, error = _authorize()
    if error:
        return error
    return _pdf_response(_build_security_pdf(org_id, date_range), 'security')


@reports_bp.route('/governance.pdf', methods=['GET'])
@jwt_required()
def governance_pdf():
    org_id, _, error = _authorize()
    if error:
        return error
    return _pdf_response(_build_governance_pdf(org_id), 'governance')


@reports_bp.route('/cost.csv', methods=['GET'])
@jwt_required()
def cost_csv():
    org_id, date_range, error = _authorize()
    if error:
        return error

    cost_records = _cost_records_for_org(org_id, date_range)
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
            'date', 'hour', 'resource_id', 'resource_type', 'compute_cost',
            'storage_cost', 'network_cost', 'total_cost', 'cpu_avg', 'memory_avg',
        ],
        rows,
    )


@reports_bp.route('/security.csv', methods=['GET'])
@jwt_required()
def security_csv():
    org_id, date_range, error = _authorize()
    if error:
        return error

    threats = _threats_for_org(org_id, date_range)
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
            'detected_at', 'threat_type', 'severity', 'confidence_score',
            'status', 'affected_resources', 'detection_pattern',
        ],
        rows,
    )


@reports_bp.route('/governance.csv', methods=['GET'])
@jwt_required()
def governance_csv():
    org_id, _, error = _authorize()
    if error:
        return error

    state = governance_engine.get_latest_state(org_id)
    rows = [[
        v['checked_at'], v['policy_name'], v['severity'], v['resource_type'],
        v['resource_id'], '; '.join(v['violations']),
    ] for v in state['violations']]
    return _csv_response(
        f'governance_export_{datetime.utcnow().strftime("%Y%m%d")}.csv',
        ['checked_at', 'policy', 'severity', 'resource_type', 'resource_id', 'violations'],
        rows,
    )


@reports_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_report():
    """Legacy PDF generation endpoint kept for existing frontend wiring."""
    payload = request.get_json(silent=True) or {}
    report_type = (payload.get('report_type') or 'summary').strip().lower()
    org_id = _resolve_org_id_from_request(payload)

    if not _require_org_membership(get_jwt_identity(), org_id):
        return jsonify({'error': 'Access denied'}), 403
    date_range, error = _parse_range(payload)
    if error:
        return jsonify({'error': error}), 400

    if report_type == 'cost':
        buffer = _build_cost_pdf(org_id, date_range)
    elif report_type == 'security':
        buffer = _build_security_pdf(org_id, date_range)
    elif report_type == 'governance':
        buffer = _build_governance_pdf(org_id)
    elif report_type == 'summary':
        buffer = _build_summary_pdf(org_id, date_range)
    else:
        return jsonify({'error': 'Invalid report type'}), 400
    return _pdf_response(buffer, report_type)


@reports_bp.route('/export/csv', methods=['GET'])
@jwt_required()
def export_csv():
    """Legacy CSV endpoint kept for existing frontend wiring."""
    export_type = (request.args.get('type') or 'costs').strip().lower()
    if export_type == 'security':
        return security_csv()
    if export_type == 'governance':
        return governance_csv()
    if export_type in {'cost', 'costs'}:
        return cost_csv()
    return jsonify({'error': 'Invalid export type'}), 400
