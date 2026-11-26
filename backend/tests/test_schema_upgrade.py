"""Migration verification for utils/schema_upgrade.py (PostgreSQL only).

Recreates the pre-Module-10 shape of the two evolved tables on the test database, runs the
upgrade twice and checks: missing columns are added, relaxed NOT NULL constraints, IPv6 width,
indexes, the tenant back-fill of legacy remediation rows, and that existing rows are kept.
"""

import pytest
from sqlalchemy import inspect, text

from app import db
from app.models.security import ThreatDetection, ThreatSeverity, ThreatType
from app.utils.schema_upgrade import upgrade_schema


@pytest.fixture()
def legacy_schema(app, world):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('schema upgrade targets PostgreSQL')
    threat = ThreatDetection(organization_id=world['org_a'], threat_type=ThreatType.DDoS,
                             severity=ThreatSeverity.HIGH, confidence_score=0.9)
    db.session.add(threat)
    db.session.commit()
    with db.engine.begin() as conn:
        for column in ('category', 'outcome'):
            conn.execute(text(f'ALTER TABLE audit_logs DROP COLUMN {column}'))
        conn.execute(text('ALTER TABLE audit_logs ALTER COLUMN ip_address TYPE VARCHAR(15)'))
        conn.execute(text('ALTER TABLE audit_logs ALTER COLUMN organization_id SET NOT NULL'))
        for column in ('organization_id', 'issue_type', 'issue_key', 'resource_type', 'resource_id', 'assigned_to'):
            conn.execute(text(f'ALTER TABLE remediation_actions DROP COLUMN {column}'))
        conn.execute(text('ALTER TABLE remediation_actions ALTER COLUMN threat_id SET NOT NULL'))
        conn.execute(text('DROP INDEX IF EXISTS ix_audit_logs_org_ts'))
        # A legacy row written by the old simulator (no tenant column yet).
        conn.execute(text("INSERT INTO remediation_actions (threat_id, action_type, executed_by, status, requires_approval) "
                          "VALUES (:t, 'isolate_resource', 'system', 'success', false)"), {'t': threat.id})
        conn.execute(text("INSERT INTO audit_logs (organization_id, action, timestamp) VALUES (:o, 'vm_created', now())"),
                     {'o': world['org_a']})
    return world['org_a']


def _columns(table):
    return {c['name']: c for c in inspect(db.engine).get_columns(table)}


def test_upgrade_restores_schema_idempotently_and_keeps_data(legacy_schema):
    org_id = legacy_schema
    upgrade_schema(db)
    upgrade_schema(db)  # second run must be a no-op, not an error

    audit, remediation = _columns('audit_logs'), _columns('remediation_actions')
    assert {'category', 'outcome'} <= set(audit)
    assert audit['organization_id']['nullable'] is True
    assert audit['ip_address']['type'].length == 45
    assert {'organization_id', 'issue_type', 'issue_key', 'resource_type', 'resource_id', 'assigned_to'} <= set(remediation)
    assert remediation['threat_id']['nullable'] is True
    indexes = {i['name'] for i in inspect(db.engine).get_indexes('audit_logs')}
    assert 'ix_audit_logs_org_ts' in indexes

    with db.engine.connect() as conn:
        legacy = conn.execute(text("SELECT organization_id, status FROM remediation_actions WHERE executed_by = 'system'")).one()
        assert legacy == (org_id, 'success')  # tenant back-filled, nothing else rewritten
        assert conn.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'vm_created'")).scalar() == 1
