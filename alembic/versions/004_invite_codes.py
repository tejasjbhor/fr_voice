"""Invite codes so subscribers can share a join link with elders.

Revision ID: 004_invite_codes
Revises: 003_app_accounts
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_invite_codes"
down_revision: Union[str, None] = "003_app_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("invite_code", sa.String(length=16), nullable=True))
    op.create_index("ix_users_invite_code", "users", ["invite_code"], unique=True)
    op.add_column(
        "users",
        sa.Column("invite_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "invite_accepted_at")
    op.drop_index("ix_users_invite_code", table_name="users")
    op.drop_column("users", "invite_code")
