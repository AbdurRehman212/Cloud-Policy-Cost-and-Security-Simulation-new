"""Version-controlled schema migrations (Alembic via Flask-Migrate), applied on start.

- Empty database: ``upgrade`` builds the whole schema from ``migrations/versions``.
- Database created earlier by ``db.create_all()`` (no ``alembic_version`` table): the additive
  ``schema_upgrade`` brings it to the baseline shape, it is stamped at ``0001_baseline``, then
  upgraded. No table is dropped and no row is rewritten.
- Already versioned database: ``upgrade`` applies only newer revisions.

PostgreSQL runs each migration in a transaction, so a failing revision leaves the database at
the previous version.
"""

import logging
import os

from flask_migrate import stamp, upgrade
from sqlalchemy import inspect

BASELINE = '0001_baseline'
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'migrations')
logger = logging.getLogger(__name__)


def migrate_on_start(db):
    tables = set(inspect(db.engine).get_table_names())
    if 'alembic_version' not in tables and 'users' in tables:
        from app.utils.schema_upgrade import upgrade_schema
        upgrade_schema(db)
        stamp(directory=MIGRATIONS_DIR, revision=BASELINE)
        logger.info('existing database adopted at migration %s', BASELINE)
    upgrade(directory=MIGRATIONS_DIR)
