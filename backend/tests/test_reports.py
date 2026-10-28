import csv
import io
from datetime import date, datetime, timedelta

import pytest

from app import db
from app.models.cost import CostRecord
from app.models.security import SecurityLog, ThreatDetection, ThreatSeverity, ThreatType
from app.routes import reports
from tests.conftest import make_vm

R = '/api/reports'


def add_cost(org_id, day, amount, resource_id='i-a'):
    db.session.add(CostRecord(
        organization_id=org_id, resource_id=resource_id, resource_type='vm', date=day, hour=1,
        compute_cost=amount, total_cost=amount,
    ))
    db.session.commit()


def add_threat(org_id, when, status='active'):
    db.session.add(ThreatDetection(
        organization_id=org_id, detected_at=when, threat_type=ThreatType.DDoS,
        severity=ThreatSeverity.HIGH, confidence_score=0.9, status=status,
        affected_resources=['i-a', 'i-b'], detection_pattern='=cmd|pattern',
    ))
    db.session.commit()


def rows(response):
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


@pytest.fixture()
def captured(monkeypatch):
    """Capture the sections handed to the PDF builder so content can be asserted."""
    seen = {}
    original = reports._build_pdf_document

    def spy(title, sections, subtitle=None):
        seen['title'], seen['sections'], seen['subtitle'] = title, sections, subtitle
        return original(title, sections, subtitle)

    monkeypatch.setattr(reports, '_build_pdf_document', spy)
    return seen


def flat(sections):
    return ' | '.join(str(cell) for _, _, rws, _ in sections for row in rws for cell in row)


@pytest.mark.parametrize('name', ['summary', 'cost', 'security', 'governance'])
def test_pdfs_are_valid_and_scoped(client, world, name):  # TC-M9-01..03, TC-M9-08
    r = client.get(f"{R}/{name}.pdf?organization_id={world['org_a']}", headers=world['viewer'])
    assert r.status_code == 200 and r.mimetype == 'application/pdf'
    assert r.data.startswith(b'%PDF') and r.data.rstrip().endswith(b'%%EOF')
    assert 'attachment' in r.headers['Content-Disposition']
    assert client.get(f"{R}/{name}.pdf?organization_id={world['org_a']}", headers=world['other']).status_code == 403
    assert client.get(f'{R}/{name}.pdf', headers=world['viewer']).status_code == 403  # no org given


def test_cost_csv_filters_and_isolation(client, world):  # TC-M9-04, TC-M9-06
    today = date.today()
    add_cost(world['org_a'], today, 3.0, 'i-new')
    add_cost(world['org_a'], today - timedelta(days=20), 4.0, 'i-old')
    add_cost(world['org_b'], today, 99.0, 'i-other-tenant')
    base = f"{R}/cost.csv?organization_id={world['org_a']}"
    allrows = rows(client.get(base, headers=world['viewer']))
    assert allrows[0][:4] == ['date', 'hour', 'resource_id', 'resource_type']
    assert {r[2] for r in allrows[1:]} == {'i-new', 'i-old'}
    recent = rows(client.get(f"{base}&start_date={(today - timedelta(days=5)).isoformat()}", headers=world['viewer']))
    assert [r[2] for r in recent[1:]] == ['i-new']
    old = rows(client.get(f"{base}&end_date={(today - timedelta(days=10)).isoformat()}", headers=world['viewer']))
    assert [r[2] for r in old[1:]] == ['i-old']


def test_invalid_dates_rejected(client, world):  # TC-M9-09
    for qs in ('start_date=bad', 'end_date=2024-13-40', 'start_date=2025-02-01&end_date=2025-01-01'):
        for path in ('cost.csv', 'security.csv', 'cost.pdf', 'security.pdf', 'summary.pdf'):
            r = client.get(f"{R}/{path}?organization_id={world['org_a']}&{qs}", headers=world['viewer'])
            assert r.status_code == 400, (path, qs)
    r = client.post(f'{R}/generate', json={'organization_id': world['org_a'], 'start_date': 'x'}, headers=world['viewer'])
    assert r.status_code == 400


def test_security_csv_and_summary(client, world, captured):  # TC-M9-05, TC-M9-07
    now = datetime.utcnow()
    add_threat(world['org_a'], now)
    add_threat(world['org_a'], now - timedelta(days=30), status='resolved')
    add_threat(world['org_b'], now)
    db.session.add(SecurityLog(organization_id=world['org_a'], event_type='login_failed', description='x', timestamp=now))
    db.session.commit()

    out = rows(client.get(f"{R}/security.csv?organization_id={world['org_a']}", headers=world['viewer']))
    assert len(out) == 3 and out[1][5] == 'i-a|i-b'
    assert out[1][6].startswith("'=")  # formula-injection guard

    window = f"start_date={(now - timedelta(days=2)).date().isoformat()}"
    out = rows(client.get(f"{R}/security.csv?organization_id={world['org_a']}&{window}", headers=world['viewer']))
    assert len(out) == 2

    client.get(f"{R}/security.pdf?organization_id={world['org_a']}&{window}", headers=world['viewer'])
    text = flat(captured['sections'])
    assert 'Threat detections | 1' in text and 'ddos' in text
    assert captured['subtitle'][0].isoformat() == (now - timedelta(days=2)).date().isoformat()


def test_cost_pdf_content(client, world, captured):  # TC-M9-06
    add_cost(world['org_a'], date.today(), 12.5, 'i-a')
    client.get(f"{R}/cost.pdf?organization_id={world['org_a']}", headers=world['viewer'])
    text = flat(captured['sections'])
    assert 'Lifetime spend | $12.50' in text and 'i-a' in text


def test_governance_report_and_summary_section(client, world, captured):  # TC-M9-01, TC-M9-02
    make_vm(world['org_a'], 'hot', cpu_utilization=95.0)
    client.post('/api/governance/policies', headers=world['admin'], json={
        'organization_id': world['org_a'], 'name': 'CPU cap',
        'policy_rule': 'resource_type=vm; max_cpu=70; severity=high'})
    client.post('/api/governance/compliance/check', json={'organization_id': world['org_a']}, headers=world['admin'])

    out = rows(client.get(f"{R}/governance.csv?organization_id={world['org_a']}", headers=world['viewer']))
    assert out[0][:3] == ['checked_at', 'policy', 'severity'] and len(out) == 2
    assert out[1][1] == 'CPU cap' and 'CPU utilization exceeds' in out[1][5]
    legacy = rows(client.get(f"{R}/export/csv?type=governance&organization_id={world['org_a']}", headers=world['viewer']))
    assert legacy == out

    client.get(f"{R}/governance.pdf?organization_id={world['org_a']}", headers=world['viewer'])
    assert 'CPU cap' in flat(captured['sections']) and '0.0 / 100' in flat(captured['sections'])

    client.get(f"{R}/summary.pdf?organization_id={world['org_a']}", headers=world['viewer'])
    text = flat(captured['sections'])
    assert 'Governance Score | 0.0 / 100' in text and 'Open Policy Violations | 1' in text


def test_generate_endpoint_and_legacy_csv(client, world):
    for kind in ('summary', 'cost', 'security', 'governance'):
        r = client.post(f'{R}/generate', json={'organization_id': world['org_a'], 'report_type': kind}, headers=world['viewer'])
        assert r.status_code == 200 and r.data.startswith(b'%PDF'), kind
    assert client.post(f'{R}/generate', json={'organization_id': world['org_a'], 'report_type': 'nope'},
                       headers=world['viewer']).status_code == 400
    assert client.post(f'{R}/generate', json={'organization_id': world['org_a']}, headers=world['other']).status_code == 403
    assert client.get(f"{R}/export/csv?type=bogus&organization_id={world['org_a']}", headers=world['viewer']).status_code == 400
    assert client.get(f"{R}/export/csv?type=costs&organization_id={world['org_a']}", headers=world['other']).status_code == 403
