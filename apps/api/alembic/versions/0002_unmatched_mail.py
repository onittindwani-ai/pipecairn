"""keep mail from addresses that are not leads

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
import sendora_core.db


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('cl_unmatched_mail',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('external_id', sa.String(length=120), nullable=False),
    sa.Column('from_addr', sa.String(length=254), nullable=False),
    sa.Column('to_addr', sa.String(length=254), nullable=False),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('snippet', sa.Text(), nullable=False),
    sa.Column('handled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sendora_core.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('cl_unmatched_mail', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cl_unmatched_mail_external_id'), ['external_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('cl_unmatched_mail', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cl_unmatched_mail_external_id'))

    op.drop_table('cl_unmatched_mail')
