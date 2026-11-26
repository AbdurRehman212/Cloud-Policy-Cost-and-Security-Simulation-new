"""Idempotent, additive schema evolution for databases created by ``db.create_all()``.

``create_all`` creates missing tables but never alters existing ones, and the existing
development/production databases have no Alembic baseline (see ENGINEERING_QUALITY_REPORT).
Each step below is additive or relaxes a constraint, is safe to run on every start, and
never drops or rewrites user data. SQLite (tests) is skipped: its schema is always fresh.
"""

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

# (table, column, DDL type) — added when missing.
ADDED_COLUMNS = [
    ('audit_logs', 'category', 'VARCHAR(30)'),
    ('audit_logs', 'outcome', "VARCHAR(20) DEFAULT 'success'"),
    ('remediation_actions', 'organization_id', 'INTEGER REFERENCES organizations(id)'),
    ('remediation_actions', 'issue_type', 'VARCHAR(20)'),
    ('remediation_actions', 'issue_key', 'VARCHAR(100)'),
    ('remediation_actions', 'resource_type', 'VARCHAR(20)'),
    ('remediation_actions', 'resource_id', 'INTEGER'),
    ('remediation_actions', 'assigned_to', 'INTEGER REFERENCES users(id)'),
]

RELAXED_NOT_NULL = [
    ('audit_logs', 'organization_id'),  # account-level events have no tenant
    ('remediation_actions', 'threat_id'),  # governance/idle remediations have no threat
]

STATEMENTS = [
    'ALTER TABLE audit_logs ALTER COLUMN ip_address TYPE VARCHAR(45)',  # IPv6
    'CREATE INDEX IF NOT EXISTS ix_audit_logs_org_ts ON audit_logs (organization_id, timestamp)',
    'CREATE INDEX IF NOT EXISTS ix_audit_logs_category ON audit_logs (category)',
    'CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs (user_id)',
    'CREATE INDEX IF NOT EXISTS ix_remediation_actions_issue_key ON remediation_actions (issue_key)',
    'CREATE INDEX IF NOT EXISTS ix_remediation_actions_organization_id ON remediation_actions (organization_id)',
    # Back-fill the tenant of legacy remediation rows from their threat (no other values change).
    '''UPDATE remediation_actions ra SET organization_id = td.organization_id
       FROM threat_detections td WHERE ra.threat_id = td.id AND ra.organization_id IS NULL''',
]


def upgrade_schema(db):
    engine = db.engine
    if engine.dialect.name != 'postgresql':
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table in tables:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}'))
        for table, column in RELAXED_NOT_NULL:
            if table in tables:
                conn.execute(text(f'ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL'))
        for statement in STATEMENTS:
            conn.execute(text(statement))
    logger.info('schema upgrade checked (%d additive columns)', len(ADDED_COLUMNS))
