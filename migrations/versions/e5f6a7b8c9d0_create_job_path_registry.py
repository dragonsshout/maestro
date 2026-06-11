"""create_job_path_registry

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-10 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_path_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False, server_default="jenkins"),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository", "environment", name="uq_job_path_registry_repository_environment"),
    )


def downgrade() -> None:
    op.drop_table("job_path_registry")
