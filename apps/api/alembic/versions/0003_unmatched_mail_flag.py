"""mark mail that could not be read

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('cl_unmatched_mail', schema=None) as batch_op:
        batch_op.add_column(sa.Column('flag', sa.String(length=20), server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('cl_unmatched_mail', schema=None) as batch_op:
        batch_op.drop_column('flag')
