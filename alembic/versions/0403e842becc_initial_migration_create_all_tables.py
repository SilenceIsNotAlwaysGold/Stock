"""Initial migration: create all tables

Revision ID: 0403e842becc
Revises:
Create Date: 2026-02-23 07:39:35.532146

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0403e842becc"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create stocks table
    op.create_table(
        "stocks",
        sa.Column(
            "ts_code",
            sa.String(20),
            primary_key=True,
            comment="Stock code (e.g. 000001.SZ)",
        ),
        sa.Column("name", sa.String(100), nullable=False, comment="Stock name"),
        sa.Column("industry", sa.String(100), nullable=True, comment="Industry"),
        sa.Column("area", sa.String(100), nullable=True, comment="Area"),
        sa.Column(
            "market",
            sa.String(20),
            nullable=True,
            comment="Market (主板/创业板/科创板)",
        ),
        sa.Column("list_date", sa.Date(), nullable=True, comment="List date"),
        sa.Column("delist_date", sa.Date(), nullable=True, comment="Delist date"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Is active",
        ),
    )
    op.create_index("idx_stock_industry", "stocks", ["industry"])
    op.create_index("idx_stock_is_active", "stocks", ["is_active"])

    # Create daily_bars table
    op.create_table(
        "daily_bars",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts_code",
            sa.String(20),
            sa.ForeignKey("stocks.ts_code"),
            nullable=False,
            comment="Stock code",
        ),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="Trade date"),
        sa.Column("open", sa.Numeric(20, 4), nullable=True, comment="Open price"),
        sa.Column("high", sa.Numeric(20, 4), nullable=True, comment="High price"),
        sa.Column("low", sa.Numeric(20, 4), nullable=True, comment="Low price"),
        sa.Column("close", sa.Numeric(20, 4), nullable=True, comment="Close price"),
        sa.Column("volume", sa.Integer(), nullable=True, comment="Volume"),
        sa.Column("amount", sa.Numeric(20, 4), nullable=True, comment="Amount"),
        sa.Column("turnover_rate", sa.Float(), nullable=True, comment="Turnover rate"),
        sa.UniqueConstraint("ts_code", "trade_date", name="uq_daily_bar_ts_date"),
    )
    op.create_index("idx_daily_bar_ts_code", "daily_bars", ["ts_code"])
    op.create_index("idx_daily_bar_trade_date", "daily_bars", ["trade_date"])

    # Create strategy_signals table
    op.create_table(
        "strategy_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts_code", sa.String(20), nullable=False, comment="Stock code"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="Trade date"),
        sa.Column(
            "strategy_name", sa.String(100), nullable=False, comment="Strategy name"
        ),
        sa.Column("action", sa.String(10), nullable=False, comment="BUY/SELL/HOLD"),
        sa.Column("confidence", sa.Float(), nullable=False, comment="Confidence score"),
        sa.Column("reason", sa.Text(), nullable=True, comment="Signal reason"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_signal_ts_code", "strategy_signals", ["ts_code"])
    op.create_index("idx_signal_trade_date", "strategy_signals", ["trade_date"])
    op.create_index("idx_signal_strategy", "strategy_signals", ["strategy_name"])

    # Create daily_recommendations table
    op.create_table(
        "daily_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="Trade date"),
        sa.Column("ts_code", sa.String(20), nullable=False, comment="Stock code"),
        sa.Column("stock_name", sa.String(100), nullable=False, comment="Stock name"),
        sa.Column("score", sa.Float(), nullable=False, comment="Recommendation score"),
        sa.Column("strategies", sa.JSON(), nullable=True, comment="Strategy details"),
        sa.Column(
            "agent_summary", sa.Text(), nullable=True, comment="AI agent summary"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "idx_recommendation_trade_date", "daily_recommendations", ["trade_date"]
    )
    op.create_index("idx_recommendation_ts_code", "daily_recommendations", ["ts_code"])
    op.create_index("idx_recommendation_score", "daily_recommendations", ["score"])

    # Create paper_accounts table
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(100), nullable=False, comment="User ID"),
        sa.Column("name", sa.String(200), nullable=False, comment="Account name"),
        sa.Column(
            "initial_cash", sa.Numeric(20, 4), nullable=False, comment="Initial cash"
        ),
        sa.Column(
            "current_cash", sa.Numeric(20, 4), nullable=False, comment="Current cash"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_paper_account_user_id", "paper_accounts", ["user_id"])

    # Create paper_positions table
    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("paper_accounts.id"),
            nullable=False,
            comment="Account ID",
        ),
        sa.Column("ts_code", sa.String(20), nullable=False, comment="Stock code"),
        sa.Column("stock_name", sa.String(100), nullable=False, comment="Stock name"),
        sa.Column("quantity", sa.Integer(), nullable=False, comment="Quantity"),
        sa.Column(
            "avg_cost", sa.Numeric(20, 4), nullable=False, comment="Average cost"
        ),
        sa.Column(
            "current_price", sa.Numeric(20, 4), nullable=False, comment="Current price"
        ),
        sa.Column(
            "market_value", sa.Numeric(20, 4), nullable=False, comment="Market value"
        ),
        sa.Column(
            "unrealized_pnl",
            sa.Numeric(20, 4),
            nullable=False,
            comment="Unrealized P&L",
        ),
        sa.Column(
            "unrealized_pnl_pct",
            sa.Numeric(20, 4),
            nullable=False,
            comment="Unrealized P&L %",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_paper_position_account_id", "paper_positions", ["account_id"])
    op.create_index("idx_paper_position_ts_code", "paper_positions", ["ts_code"])

    # Create paper_orders table
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("paper_accounts.id"),
            nullable=False,
            comment="Account ID",
        ),
        sa.Column("ts_code", sa.String(20), nullable=False, comment="Stock code"),
        sa.Column("stock_name", sa.String(100), nullable=False, comment="Stock name"),
        sa.Column("direction", sa.String(10), nullable=False, comment="BUY/SELL"),
        sa.Column("quantity", sa.Integer(), nullable=False, comment="Quantity"),
        sa.Column("price", sa.Numeric(20, 4), nullable=False, comment="Price"),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False, comment="Amount"),
        sa.Column(
            "commission", sa.Numeric(20, 4), nullable=False, comment="Commission"
        ),
        sa.Column("status", sa.String(20), nullable=False, comment="FILLED/CANCELLED"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("filled_at", sa.DateTime(), nullable=True, comment="Filled time"),
    )
    op.create_index("idx_paper_order_account_id", "paper_orders", ["account_id"])
    op.create_index("idx_paper_order_ts_code", "paper_orders", ["ts_code"])
    op.create_index("idx_paper_order_status", "paper_orders", ["status"])

    # Create strategy_health table
    op.create_table(
        "strategy_health",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "strategy_name", sa.String(100), nullable=False, comment="Strategy name"
        ),
        sa.Column(
            "period", sa.String(50), nullable=False, comment="Period (e.g. 2024-W01)"
        ),
        sa.Column("win_rate", sa.Float(), nullable=False, comment="Win rate"),
        sa.Column("avg_return", sa.Float(), nullable=False, comment="Average return"),
        sa.Column("sharpe_ratio", sa.Float(), nullable=False, comment="Sharpe ratio"),
        sa.Column("max_drawdown", sa.Float(), nullable=False, comment="Max drawdown"),
        sa.Column("score", sa.Float(), nullable=False, comment="Health score"),
        sa.Column(
            "grade",
            sa.String(50),
            nullable=False,
            comment="Core/Plus/Experimental/Problematic",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_strategy_health_name", "strategy_health", ["strategy_name"])
    op.create_index("idx_strategy_health_period", "strategy_health", ["period"])
    op.create_index("idx_strategy_health_grade", "strategy_health", ["grade"])

    # Create market_emotions table
    op.create_table(
        "market_emotions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trade_date", sa.Date(), unique=True, nullable=False, comment="Trade date"
        ),
        sa.Column("emotion_score", sa.Float(), nullable=False, comment="Emotion score"),
        sa.Column(
            "advance_count", sa.Integer(), nullable=False, comment="Advance count"
        ),
        sa.Column(
            "decline_count", sa.Integer(), nullable=False, comment="Decline count"
        ),
        sa.Column(
            "limit_up_count", sa.Integer(), nullable=False, comment="Limit up count"
        ),
        sa.Column(
            "limit_down_count", sa.Integer(), nullable=False, comment="Limit down count"
        ),
        sa.Column(
            "avg_change_pct", sa.Float(), nullable=False, comment="Average change %"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_market_emotion_trade_date", "market_emotions", ["trade_date"])

    # Create system_configs table
    op.create_table(
        "system_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "key", sa.String(200), unique=True, nullable=False, comment="Config key"
        ),
        sa.Column("value", sa.Text(), nullable=False, comment="Config value"),
        sa.Column("category", sa.String(100), nullable=True, comment="Category"),
        sa.Column("description", sa.Text(), nullable=True, comment="Description"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_system_config_category", "system_configs", ["category"])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop tables in reverse order (respecting foreign key constraints)
    op.drop_index("idx_system_config_category", "system_configs")
    op.drop_table("system_configs")

    op.drop_index("idx_market_emotion_trade_date", "market_emotions")
    op.drop_table("market_emotions")

    op.drop_index("idx_strategy_health_grade", "strategy_health")
    op.drop_index("idx_strategy_health_period", "strategy_health")
    op.drop_index("idx_strategy_health_name", "strategy_health")
    op.drop_table("strategy_health")

    op.drop_index("idx_paper_order_status", "paper_orders")
    op.drop_index("idx_paper_order_ts_code", "paper_orders")
    op.drop_index("idx_paper_order_account_id", "paper_orders")
    op.drop_table("paper_orders")

    op.drop_index("idx_paper_position_ts_code", "paper_positions")
    op.drop_index("idx_paper_position_account_id", "paper_positions")
    op.drop_table("paper_positions")

    op.drop_index("idx_paper_account_user_id", "paper_accounts")
    op.drop_table("paper_accounts")

    op.drop_index("idx_recommendation_score", "daily_recommendations")
    op.drop_index("idx_recommendation_ts_code", "daily_recommendations")
    op.drop_index("idx_recommendation_trade_date", "daily_recommendations")
    op.drop_table("daily_recommendations")

    op.drop_index("idx_signal_strategy", "strategy_signals")
    op.drop_index("idx_signal_trade_date", "strategy_signals")
    op.drop_index("idx_signal_ts_code", "strategy_signals")
    op.drop_table("strategy_signals")

    op.drop_index("idx_daily_bar_trade_date", "daily_bars")
    op.drop_index("idx_daily_bar_ts_code", "daily_bars")
    op.drop_table("daily_bars")

    op.drop_index("idx_stock_is_active", "stocks")
    op.drop_index("idx_stock_industry", "stocks")
    op.drop_table("stocks")
