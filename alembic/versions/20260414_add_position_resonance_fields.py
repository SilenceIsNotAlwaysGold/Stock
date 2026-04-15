"""add position management and resonance fields to t1_candidates

Revision ID: 20260414a
Revises: 20260412a
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260414a"
down_revision = "20260412a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 仓位建议字段
    op.add_column(
        "t1_candidates",
        sa.Column("suggested_pct", sa.Float(), nullable=True, comment="建议仓位比例 0-1"),
    )
    op.add_column(
        "t1_candidates",
        sa.Column("suggested_quantity", sa.Integer(), nullable=True, comment="建议买入股数"),
    )
    op.add_column(
        "t1_candidates",
        sa.Column(
            "position_reason",
            sa.String(200),
            nullable=True,
            comment="仓位决策原因",
        ),
    )
    # 共振字段
    op.add_column(
        "t1_candidates",
        sa.Column(
            "resonance_count",
            sa.Integer(),
            nullable=True,
            server_default="0",
            comment="共振策略数",
        ),
    )
    op.add_column(
        "t1_candidates",
        sa.Column(
            "resonance_bonus",
            sa.Float(),
            nullable=True,
            server_default="0",
            comment="共振加分",
        ),
    )
    op.add_column(
        "t1_candidates",
        sa.Column(
            "resonating_strategies",
            sa.Text(),
            nullable=True,
            comment="共振策略名列表(逗号分隔)",
        ),
    )


def downgrade() -> None:
    op.drop_column("t1_candidates", "resonating_strategies")
    op.drop_column("t1_candidates", "resonance_bonus")
    op.drop_column("t1_candidates", "resonance_count")
    op.drop_column("t1_candidates", "position_reason")
    op.drop_column("t1_candidates", "suggested_quantity")
    op.drop_column("t1_candidates", "suggested_pct")
