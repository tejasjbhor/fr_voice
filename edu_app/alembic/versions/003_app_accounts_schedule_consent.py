"""Account role, schedule flexibility, consent, test billing.

Revision ID: 003_app_accounts
Revises: 002_prompt_version
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_app_accounts"
down_revision: Union[str, None] = "002_prompt_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("account_role", sa.String(length=16), nullable=False, server_default="user"),
    )
    op.add_column("users", sa.Column("city", sa.String(length=80), nullable=True))
    op.add_column(
        "users",
        sa.Column("has_smartphone", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Kolkata"),
    )
    op.add_column(
        "users",
        sa.Column(
            "days_of_week",
            sa.String(length=32),
            nullable=False,
            server_default="1,2,3,4,5,6,7",
        ),
    )
    op.add_column("users", sa.Column("last_scheduled_on", sa.String(length=10), nullable=True))
    op.add_column("users", sa.Column("skip_on", sa.String(length=10), nullable=True))
    op.add_column(
        "users",
        sa.Column("consent_calls", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("consent_recording", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("consent_health", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("plan_status", sa.String(length=32), nullable=False, server_default="none"),
    )
    op.add_column("users", sa.Column("plan_activated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in (
        "plan_activated_at",
        "plan_status",
        "consent_at",
        "consent_health",
        "consent_recording",
        "consent_calls",
        "skip_on",
        "last_scheduled_on",
        "days_of_week",
        "timezone",
        "schedule_enabled",
        "has_smartphone",
        "city",
        "account_role",
    ):
        op.drop_column("users", col)
