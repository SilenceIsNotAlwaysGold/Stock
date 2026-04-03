"""add t1 overnight strategy tables

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "0403e842becc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "t1_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_date", sa.Date(), nullable=False, comment="扫描日期"),
        sa.Column("ts_code", sa.String(20), nullable=False, comment="股票代码"),
        sa.Column("stock_name", sa.String(100), nullable=False, comment="股票名称"),
        sa.Column("criterion", sa.String(50), nullable=False, comment="选股条件"),
        sa.Column("score", sa.Float(), nullable=False, comment="评分"),
        sa.Column("close_price", sa.Numeric(20, 4), comment="收盘价"),
        sa.Column("change_pct", sa.Float(), comment="涨跌幅%"),
        sa.Column("volume_ratio", sa.Float(), comment="量比"),
        sa.Column("turnover_rate", sa.Float(), comment="换手率%"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), comment="选股理由"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_t1_candidate_scan_date", "t1_candidates", ["scan_date"])
    op.create_index("idx_t1_candidate_criterion", "t1_candidates", ["criterion"])
    op.create_index("idx_t1_candidate_status", "t1_candidates", ["status"])

    op.create_table(
        "t1_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("stock_name", sa.String(100), nullable=False),
        sa.Column("buy_date", sa.Date(), nullable=False),
        sa.Column("buy_price", sa.Numeric(20, 4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("criterion", sa.String(50), nullable=False),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("t1_candidates.id")),
        sa.Column("status", sa.String(20), nullable=False, server_default="holding"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_t1_position_ts_code", "t1_positions", ["ts_code"])
    op.create_index("idx_t1_position_status", "t1_positions", ["status"])
    op.create_index("idx_t1_position_buy_date", "t1_positions", ["buy_date"])

    op.create_table(
        "t1_trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "position_id",
            sa.Integer(),
            sa.ForeignKey("t1_positions.id"),
            nullable=False,
        ),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("stock_name", sa.String(100), nullable=False),
        sa.Column("criterion", sa.String(50), nullable=False),
        sa.Column("buy_date", sa.Date(), nullable=False),
        sa.Column("buy_price", sa.Numeric(20, 4), nullable=False),
        sa.Column("sell_date", sa.Date(), nullable=False),
        sa.Column("sell_price", sa.Numeric(20, 4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("sell_reason", sa.String(30), nullable=False),
        sa.Column("pnl", sa.Numeric(20, 4), nullable=False),
        sa.Column("pnl_pct", sa.Float(), nullable=False),
        sa.Column("is_win", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_t1_trade_ts_code", "t1_trades", ["ts_code"])
    op.create_index("idx_t1_trade_criterion", "t1_trades", ["criterion"])
    op.create_index("idx_t1_trade_sell_date", "t1_trades", ["sell_date"])
    op.create_index("idx_t1_trade_is_win", "t1_trades", ["is_win"])

    op.create_table(
        "t1_criteria_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("criterion", sa.String(50), nullable=False),
        sa.Column("period", sa.String(50), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False),
        sa.Column("win_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("avg_pnl_pct", sa.Float(), nullable=False),
        sa.Column("max_pnl_pct", sa.Float()),
        sa.Column("min_pnl_pct", sa.Float()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("criterion", "period", name="uq_t1_stats_criterion_period"),
    )
    op.create_index("idx_t1_stats_criterion", "t1_criteria_stats", ["criterion"])


def downgrade() -> None:
    op.drop_table("t1_criteria_stats")
    op.drop_table("t1_trades")
    op.drop_table("t1_positions")
    op.drop_table("t1_candidates")
