"""create_step_event

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-31 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'step_event',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_execution_correlation_id', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_step_event_correlation_id', 'step_event', ['job_execution_correlation_id'])


def downgrade() -> None:
    op.drop_index('ix_step_event_correlation_id', table_name='step_event')
    op.drop_table('step_event')
