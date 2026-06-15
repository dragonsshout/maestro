"""add_archived_to_orchestrator_descriptor

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-15 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orchestrator_descriptor", sa.Column("archived", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("orchestrator_descriptor", "archived")
