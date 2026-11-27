"""Auth hardening: end sessions on password change; purpose-bound e-mail tokens.

Revision ID: 0002_auth_hardening
Revises: 0001_baseline
Create Date: 2026-11-27

- users.password_changed_at: access/refresh tokens issued before it are rejected.
- email_verifications.purpose: 'verify' or 'reset'; existing rows were verification tokens,
  except unused password-reset rows, which cannot be told apart and are therefore marked used
  (a user simply requests a new reset link).
Constant defaults: on PostgreSQL >= 11 adding these columns does not rewrite the tables.
"""
import sqlalchemy as sa
from alembic import op

revision = '0002_auth_hardening'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def _has_column(table, column):
    return column in {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    # Guards: a database built by create_all() from current models already has these columns.
    if not _has_column('users', 'password_changed_at'):
        with op.batch_alter_table('users') as batch_op:
            batch_op.add_column(sa.Column('password_changed_at', sa.DateTime(), nullable=True))
    if not _has_column('email_verifications', 'purpose'):
        with op.batch_alter_table('email_verifications') as batch_op:
            batch_op.add_column(sa.Column('purpose', sa.String(length=20), server_default='verify', nullable=False))
    # Old tokens had no purpose; invalidate unused ones so none can be used for a reset.
    op.execute("UPDATE email_verifications SET used = true WHERE used = false")


def downgrade():
    with op.batch_alter_table('email_verifications') as batch_op:
        batch_op.drop_column('purpose')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('password_changed_at')
