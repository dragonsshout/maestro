"""create release_step_execution

Revision ID: 77fa95ecd37b
Revises: 528447aa8a58
Create Date: 2026-05-23 11:48:56.663715

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77fa95ecd37b'
down_revision: Union[str, Sequence[str], None] = '5995f0803bff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('release_step_execution',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('release_execution_id', sa.Integer(), nullable=False),
    sa.Column('stage_id', sa.String(), nullable=False),
    sa.Column('step_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('job_execution_correlation_id', sa.Integer(), nullable=True),
    sa.Column('job_input_id', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['release_execution_id'], ['release_execution.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_release_step_execution_execution_stage_step', 'release_step_execution', ['release_execution_id', 'stage_id', 'step_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_release_step_execution_execution_stage_step', table_name='release_step_execution')
    op.drop_table('release_step_execution')
