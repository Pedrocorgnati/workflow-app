"""add effort_level to template_commands

Revision ID: t053_effort
Revises: 0001
Create Date: 2026-04-13 00:00:00.000000

Adds the `effort_level` column to `template_commands`, mirroring the UI-level
`EffortLevel` enum introduced in T-053 (low / medium / high / max). Default is
"medium" so all pre-existing rows remain valid without a data backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "t053_effort"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "template_commands",
        sa.Column(
            "effort_level",
            sa.String(20),
            nullable=False,
            server_default="medium",
        ),
    )


def downgrade() -> None:
    op.drop_column("template_commands", "effort_level")
