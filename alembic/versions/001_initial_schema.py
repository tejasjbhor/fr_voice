"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-08-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="mr-IN"),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("family_contact", sa.String(length=32), nullable=True),
        sa.Column("family_name", sa.String(length=120), nullable=True),
        sa.Column("call_time", sa.String(length=8), nullable=False, server_default="09:00"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_phone", "users", ["phone"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("audio_duration", sa.Float(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_session_id", "conversations", ["session_id"])

    op.create_table(
        "health_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("bp_systolic", sa.Integer(), nullable=True),
        sa.Column("bp_diastolic", sa.Integer(), nullable=True),
        sa.Column("sugar_fasting", sa.Integer(), nullable=True),
        sa.Column("sugar_pp", sa.Integer(), nullable=True),
        sa.Column("pulse", sa.Integer(), nullable=True),
        sa.Column("sleep_quality", sa.String(length=32), nullable=True),
        sa.Column("food_intake", sa.String(length=32), nullable=True),
        sa.Column("water_intake", sa.String(length=32), nullable=True),
        sa.Column("energy_level", sa.String(length=32), nullable=True),
        sa.Column("mood", sa.String(length=32), nullable=True),
        sa.Column("headache", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dizziness", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("chest_discomfort", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("breathing_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("body_pain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_records_user_id", "health_records", ["user_id"])
    op.create_index("ix_health_records_recorded_at", "health_records", ["recorded_at"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("alert_level", sa.String(length=32), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("sent_to", sa.String(length=64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])

    op.create_table(
        "api_costs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("stt_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stt_cost_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tts_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tts_cost_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_cost_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_cost_inr", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_costs_user_id", "api_costs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_api_costs_user_id", table_name="api_costs")
    op.drop_table("api_costs")
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_health_records_recorded_at", table_name="health_records")
    op.drop_index("ix_health_records_user_id", table_name="health_records")
    op.drop_table("health_records")
    op.drop_index("ix_conversations_session_id", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_table("users")
