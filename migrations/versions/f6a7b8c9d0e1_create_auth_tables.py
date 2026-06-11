"""create_auth_tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-15 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from passlib.context import CryptContext

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def upgrade() -> None:
    # Create user table
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
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
        sa.UniqueConstraint("username"),
    )

    # Create group table
    op.create_table(
        "group",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Create user_group_association table
    op.create_table(
        "user_group_association",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["group.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "group_id", name="uq_user_group_association_user_group"),
    )

    # Seed groups
    groups_table = sa.table(
        "group",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
    )

    op.bulk_insert(
        groups_table,
        [
            {"id": 1, "name": "Administrators", "description": "Full control, can do everything"},
            {"id": 2, "name": "Viewers", "description": "View only, can browse and navigate but take no actions"},
            {"id": 3, "name": "Approver", "description": "Viewers + can Approve/Deny releases"},
            {"id": 4, "name": "Operators", "description": "Full control on releases page, Viewers for everything else"},
            {"id": 5, "name": "Developers", "description": "Viewers for now"},
        ],
    )

    # Seed admin user
    users_table = sa.table(
        "user",
        sa.column("id", sa.Integer),
        sa.column("username", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("full_name", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    hashed_password = pwd_context.hash("chang3m3")

    op.bulk_insert(
        users_table,
        [
            {
                "id": 1,
                "username": "admin",
                "password_hash": hashed_password,
                "full_name": "Administrator",
                "is_active": True,
            },
        ],
    )

    # Assign admin to Administrators group
    association_table = sa.table(
        "user_group_association",
        sa.column("id", sa.Integer),
        sa.column("user_id", sa.Integer),
        sa.column("group_id", sa.Integer),
    )

    op.bulk_insert(
        association_table,
        [
            {"id": 1, "user_id": 1, "group_id": 1},
        ],
    )


def downgrade() -> None:
    op.drop_table("user_group_association")
    op.drop_table("group")
    op.drop_table("user")
