# Legacy Alembic revisions (not run)

`ef53ad265c44` and `aff400a45750` were written against an early SQLite schema and were never
applied to any PostgreSQL database (no database had an `alembic_version` table). They only
alter tables and cannot build a fresh database, so they are kept here for history.

The migration history starts at `migrations/versions/0001_baseline.py` (full schema as of the
Modules 1–12 release). Databases created earlier with `db.create_all()` are brought to that
shape by `app/utils/schema_upgrade.py` and stamped automatically on start (see
`app/utils/migrations.py`).
