"""create_scheduled_release

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scheduled_release',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('orchestrator_descriptor_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('release_execution_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['orchestrator_descriptor_id'], ['orchestrator_descriptor.id']),
        sa.ForeignKeyConstraint(['release_execution_id'], ['release_execution.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_scheduled_release_name_status',
        'scheduled_release',
        ['name', 'status'],
    )


def downgrade() -> None:
    op.drop_index('ix_scheduled_release_name_status', table_name='scheduled_release')
    op.drop_table('scheduled_release')
