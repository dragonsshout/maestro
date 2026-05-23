"""create_orchestrator_descriptor

Revision ID: 528447aa8a58
Revises: 
Create Date: 2026-05-23 10:35:25.138432

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '528447aa8a58'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'orchestrator_descriptor',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp_inclusao', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('yaml', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('orchestrator_descriptor')
