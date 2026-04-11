"""add v4 score detail fields to t1_candidates

Revision ID: 20260412a
Revises: 20260224_add_t1_tables
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260412a"
down_revision = "20260224_add_t1_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "t1_candidates",
        sa.Column("tech_score", sa.Float(), nullable=True, comment="技术面评分 0-30"),
    )
    op.add_column(
        "t1_candidates",
        sa.Column("capital_score", sa.Float(), nullable=True, comment="资金面评分 0-25"),
    )
    op.add_column(
        "t1_candidates",
        sa.Column(
            "fundamental_score", sa.Float(), nullable=True, comment="基本面评分 0-15"
        ),
    )
    op.add_column(
        "t1_candidates",
        sa.Column("sector_score", sa.Float(), nullable=True, comment="板块面评分 0-15"),
    )
    op.add_column(
        "t1_candidates",
        sa.Column("market_score", sa.Float(), nullable=True, comment="市场面评分 0-15"),
    )
    op.add_column(
        "t1_candidates",
        sa.Column("score_details", sa.JSON(), nullable=True, comment="评分子项明细"),
    )


def downgrade() -> None:
    op.drop_column("t1_candidates", "score_details")
    op.drop_column("t1_candidates", "market_score")
    op.drop_column("t1_candidates", "sector_score")
    op.drop_column("t1_candidates", "fundamental_score")
    op.drop_column("t1_candidates", "capital_score")
    op.drop_column("t1_candidates", "tech_score")
