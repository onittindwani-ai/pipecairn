"""count a mailbox's bounce rate from its last resume

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('cl_mailbox', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sent_base', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('bounce_base', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('cl_mailbox', schema=None) as batch_op:
        batch_op.drop_column('bounce_base')
        batch_op.drop_column('sent_base')
