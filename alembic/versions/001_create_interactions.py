"""Crear tabla interactions para trazabilidad del pipeline.

Revision ID: 001
Revises: None
Create Date: 2025-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True, default=0),
        sa.Column("latency_ms", sa.Integer(), nullable=True, default=0),
        sa.Column("was_corrected", sa.Boolean(), nullable=True, default=False),
        sa.Column("fiscalization_ok", sa.Boolean(), nullable=True, default=True),
        sa.Column("issues", sa.Text(), nullable=True, default="[]"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interactions_session_id", "interactions", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_interactions_session_id", table_name="interactions")
    op.drop_table("interactions")
