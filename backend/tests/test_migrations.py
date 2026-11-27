"""Alembic migration verification (PostgreSQL only; each test uses its own throwaway database)."""

import os
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate, downgrade, upgrade
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

import importlib
import pkgutil

from app import db
import app.models

for _module in pkgutil.iter_modules(app.models.__path__):  # register every table on db.metadata
    importlib.import_module(f'app.models.{_module.name}')
from app.utils.migrations import BASELINE, MIGRATIONS_DIR, migrate_on_start

BASE_URL = os.environ.get('TEST_DATABASE_URL', '')
pytestmark = pytest.mark.skipif(not BASE_URL.startswith('postgresql'), reason='migrations target PostgreSQL')
HEAD = '0002_auth_hardening'


@pytest.fixture()
def scratch_db():
    """An empty database that is dropped afterwards, plus a minimal app bound to it."""
    name = f'mig_{uuid.uuid4().hex[:10]}'
    admin = create_engine(make_url(BASE_URL).set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(BASE_URL).set(database=name).render_as_string(hide_password=False)
    flask_app = Flask(__name__)
    flask_app.config.update(SQLALCHEMY_DATABASE_URI=url, SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(flask_app)
    Migrate(flask_app, db)
    try:
        with flask_app.app_context():
            yield flask_app
            db.session.remove()
            db.engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _version():
    with db.engine.connect() as conn:
        return conn.execute(text('SELECT version_num FROM alembic_version')).scalar()


def _columns(table):
    return {c['name'] for c in inspect(db.engine).get_columns(table)}


def _schema_diff():
    with db.engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), db.metadata)


def test_fresh_database_is_built_by_migrations_and_matches_the_models(scratch_db):
    upgrade(directory=MIGRATIONS_DIR)
    assert _version() == HEAD
    assert len(set(inspect(db.engine).get_table_names()) - {'alembic_version'}) == 30
    assert _schema_diff() == []  # models and migration history agree exactly


def test_existing_unversioned_database_is_adopted_and_data_kept(scratch_db):
    upgrade(directory=MIGRATIONS_DIR, revision=BASELINE)
    with db.engine.begin() as conn:  # look like a database built by db.create_all() earlier
        conn.execute(text('DROP TABLE alembic_version'))
        conn.execute(text("INSERT INTO users (email, password_hash, first_name, last_name, is_active, email_verified) "
                          "VALUES ('keep@t.io', 'x', 'K', 'P', true, true)"))
        user_id = conn.execute(text("SELECT id FROM users WHERE email='keep@t.io'")).scalar()
        conn.execute(text("INSERT INTO organizations (name, slug, owner_id, is_active) VALUES ('Keep', 'keep', :u, true)"),
                     {'u': user_id})
    migrate_on_start(db)
    migrate_on_start(db)  # second start is a no-op
    assert _version() == HEAD
    assert {'password_changed_at'} <= _columns('users') and {'purpose'} <= _columns('email_verifications')
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users WHERE email='keep@t.io'")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM organizations WHERE slug='keep'")).scalar() == 1


def test_downgrade_then_upgrade_is_reproducible(scratch_db):
    upgrade(directory=MIGRATIONS_DIR)
    downgrade(directory=MIGRATIONS_DIR, revision=BASELINE)
    assert _version() == BASELINE and 'password_changed_at' not in _columns('users')
    upgrade(directory=MIGRATIONS_DIR)
    assert _version() == HEAD and _schema_diff() == []


def test_failed_migration_rolls_back_completely(scratch_db):
    upgrade(directory=MIGRATIONS_DIR, revision=BASELINE)
    with db.engine.begin() as conn:  # make the data step of 0002 fail
        conn.execute(text("CREATE FUNCTION refuse() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$ "
                          "LANGUAGE plpgsql"))
        conn.execute(text('CREATE TRIGGER refuse BEFORE UPDATE ON email_verifications '
                          'FOR EACH STATEMENT EXECUTE FUNCTION refuse()'))
    with pytest.raises(Exception):
        upgrade(directory=MIGRATIONS_DIR)
    db.session.rollback()
    assert _version() == BASELINE  # still at the previous version
    assert 'password_changed_at' not in _columns('users')  # the earlier step of 0002 was undone too
