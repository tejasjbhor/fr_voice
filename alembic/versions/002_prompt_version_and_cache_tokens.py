"""prompt_version and cache token accounting

Adds the two things needed before any prompt change can be evaluated:

  conversations.language / .prompt_version
      Which pack and which version of its prompt produced this turn. Recorded
      on the row because users.language is mutable — deriving it at read time
      relabels a caller's whole history the day they switch language.

  api_costs.llm_cache_write_tokens / .llm_cache_read_tokens
      Whether the persona prompt cache actually engaged. llm_tokens alone
      cannot tell a working cache from a silently inert cache_control marker.

All four are nullable / default 0: rows written before this migration honestly
do not know, and backfilling them from today's users.language would invent data.

Revision ID: 002_prompt_version
Revises: 001_initial
Create Date: 2026-08-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_prompt_version"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("language", sa.String(length=16), nullable=True))
    op.add_column("conversations", sa.Column("prompt_version", sa.String(length=32), nullable=True))
    op.create_index("ix_conversations_language", "conversations", ["language"])
    op.create_index("ix_conversations_prompt_version", "conversations", ["prompt_version"])

    op.add_column(
        "api_costs",
        sa.Column("llm_cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "api_costs",
        sa.Column("llm_cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("api_costs", "llm_cache_read_tokens")
    op.drop_column("api_costs", "llm_cache_write_tokens")
    op.drop_index("ix_conversations_prompt_version", table_name="conversations")
    op.drop_index("ix_conversations_language", table_name="conversations")
    op.drop_column("conversations", "prompt_version")
    op.drop_column("conversations", "language")
