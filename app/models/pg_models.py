"""
PostgreSQL ORM models for quant-platform-v8
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    Numeric,
    Text,
    DateTime,
    Date,
    Boolean,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Index,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Stock(Base):
    """Stock basic information"""

    __tablename__ = "stocks"

    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="Stock code (e.g. 000001.SZ)"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="Stock name")
    industry: Mapped[Optional[str]] = mapped_column(String(100), comment="Industry")
    area: Mapped[Optional[str]] = mapped_column(String(100), comment="Area")
    market: Mapped[Optional[str]] = mapped_column(
        String(20), comment="Market (主板/创业板/科创板)"
    )
    list_date: Mapped[Optional[datetime]] = mapped_column(Date, comment="List date")
    delist_date: Mapped[Optional[datetime]] = mapped_column(Date, comment="Delist date")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Is active"
    )

    # Indexes
    __table_args__ = (
        Index("idx_stock_industry", "industry"),
        Index("idx_stock_is_active", "is_active"),
    )


class DailyBar(Base):
    """Daily OHLCV bar data"""

    __tablename__ = "daily_bars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("stocks.ts_code"), nullable=False, comment="Stock code"
    )
    trade_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, comment="Trade date"
    )
    open: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 4), comment="Open price"
    )
    high: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 4), comment="High price"
    )
    low: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4), comment="Low price")
    close: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 4), comment="Close price"
    )
    volume: Mapped[Optional[int]] = mapped_column(Integer, comment="Volume")
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4), comment="Amount")
    turnover_rate: Mapped[Optional[float]] = mapped_column(
        Float, comment="Turnover rate"
    )

    # Indexes and constraints
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_daily_bar_ts_date"),
        Index("idx_daily_bar_ts_code", "ts_code"),
        Index("idx_daily_bar_trade_date", "trade_date"),
    )


class StrategySignal(Base):
    """Strategy trading signals"""

    __tablename__ = "strategy_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Stock code"
    )
    trade_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, comment="Trade date"
    )
    strategy_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Strategy name"
    )
    action: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="BUY/SELL/HOLD"
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Confidence score"
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, comment="Signal reason")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Indexes
    __table_args__ = (
        Index("idx_signal_ts_code", "ts_code"),
        Index("idx_signal_trade_date", "trade_date"),
        Index("idx_signal_strategy", "strategy_name"),
    )


class DailyRecommendation(Base):
    """Daily stock recommendations"""

    __tablename__ = "daily_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, comment="Trade date"
    )
    ts_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Stock code"
    )
    stock_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Stock name"
    )
    score: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Recommendation score"
    )
    strategies: Mapped[Optional[dict]] = mapped_column(JSON, comment="Strategy details")
    agent_summary: Mapped[Optional[str]] = mapped_column(
        Text, comment="AI agent summary"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Indexes
    __table_args__ = (
        Index("idx_recommendation_trade_date", "trade_date"),
        Index("idx_recommendation_ts_code", "ts_code"),
        Index("idx_recommendation_score", "score"),
    )


class PaperAccount(Base):
    """Paper trading account"""

    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, comment="User ID")
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="Account name"
    )
    initial_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Initial cash"
    )
    current_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Current cash"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Indexes
    __table_args__ = (Index("idx_paper_account_user_id", "user_id"),)


class PaperPosition(Base):
    """Paper trading position"""

    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_accounts.id"), nullable=False, comment="Account ID"
    )
    ts_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Stock code"
    )
    stock_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Stock name"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="Quantity")
    avg_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Average cost"
    )
    current_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Current price"
    )
    market_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Market value"
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Unrealized P&L"
    )
    unrealized_pnl_pct: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Unrealized P&L %"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Indexes
    __table_args__ = (
        Index("idx_paper_position_account_id", "account_id"),
        Index("idx_paper_position_ts_code", "ts_code"),
    )


class PaperOrder(Base):
    """Paper trading order"""

    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_accounts.id"), nullable=False, comment="Account ID"
    )
    ts_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Stock code"
    )
    stock_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Stock name"
    )
    direction: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="BUY/SELL"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="Quantity")
    price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Price"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Amount"
    )
    commission: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="Commission"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="FILLED/CANCELLED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="Filled time"
    )

    # Indexes
    __table_args__ = (
        Index("idx_paper_order_account_id", "account_id"),
        Index("idx_paper_order_ts_code", "ts_code"),
        Index("idx_paper_order_status", "status"),
    )


class StrategyHealth(Base):
    """Strategy health metrics"""

    __tablename__ = "strategy_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Strategy name"
    )
    period: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Period (e.g. 2024-W01)"
    )
    win_rate: Mapped[float] = mapped_column(Float, nullable=False, comment="Win rate")
    avg_return: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Average return"
    )
    sharpe_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Sharpe ratio"
    )
    max_drawdown: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Max drawdown"
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, comment="Health score")
    grade: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Core/Plus/Experimental/Problematic"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Indexes
    __table_args__ = (
        Index("idx_strategy_health_name", "strategy_name"),
        Index("idx_strategy_health_period", "period"),
        Index("idx_strategy_health_grade", "grade"),
    )


class MarketEmotion(Base):
    """Market emotion indicators"""

    __tablename__ = "market_emotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime] = mapped_column(
        Date, unique=True, nullable=False, comment="Trade date"
    )
    emotion_score: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Emotion score"
    )
    advance_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Advance count"
    )
    decline_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Decline count"
    )
    limit_up_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Limit up count"
    )
    limit_down_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Limit down count"
    )
    avg_change_pct: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Average change %"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Indexes
    __table_args__ = (Index("idx_market_emotion_trade_date", "trade_date"),)


class SystemConfig(Base):
    """System configuration"""

    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False, comment="Config key"
    )
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="Config value")
    category: Mapped[Optional[str]] = mapped_column(String(100), comment="Category")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="Description")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Indexes
    __table_args__ = (Index("idx_system_config_category", "category"),)


class T1Candidate(Base):
    """T+1隔夜策略候选股"""

    __tablename__ = "t1_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, comment="扫描日期"
    )
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False, comment="股票代码")
    stock_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="股票名称"
    )
    criterion: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="选股条件: limit_reopen/tail_surge/sector_leader",
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, comment="评分 0-1")
    close_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 4), comment="收盘价"
    )
    change_pct: Mapped[Optional[float]] = mapped_column(Float, comment="涨跌幅%")
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, comment="量比")
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, comment="换手率%")
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, comment="pending/bought/skipped"
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, comment="选股理由")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("idx_t1_candidate_scan_date", "scan_date"),
        Index("idx_t1_candidate_criterion", "criterion"),
        Index("idx_t1_candidate_status", "status"),
    )


class T1Position(Base):
    """T+1隔夜持仓"""

    __tablename__ = "t1_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False, comment="股票代码")
    stock_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="股票名称"
    )
    buy_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment="买入日期")
    buy_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="买入价格"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="买入数量")
    criterion: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="选股条件"
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("t1_candidates.id"), comment="关联候选股ID"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="holding", nullable=False, comment="holding/sold"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("idx_t1_position_ts_code", "ts_code"),
        Index("idx_t1_position_status", "status"),
        Index("idx_t1_position_buy_date", "buy_date"),
    )


class T1Trade(Base):
    """T+1已完成交易"""

    __tablename__ = "t1_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("t1_positions.id"), nullable=False, comment="关联持仓ID"
    )
    ts_code: Mapped[str] = mapped_column(String(20), nullable=False, comment="股票代码")
    stock_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="股票名称"
    )
    criterion: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="选股条件"
    )
    buy_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment="买入日期")
    buy_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="买入价格"
    )
    sell_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, comment="卖出日期"
    )
    sell_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="卖出价格"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="交易数量")
    sell_reason: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="take_profit/stop_loss/timeout_sell/manual"
    )
    pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, comment="盈亏金额"
    )
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=False, comment="盈亏百分比")
    is_win: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否盈利")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("idx_t1_trade_ts_code", "ts_code"),
        Index("idx_t1_trade_criterion", "criterion"),
        Index("idx_t1_trade_sell_date", "sell_date"),
        Index("idx_t1_trade_is_win", "is_win"),
    )


class T1CriteriaStats(Base):
    """T+1各条件胜率统计"""

    __tablename__ = "t1_criteria_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    criterion: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="选股条件"
    )
    period: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="统计周期 e.g. 2024-W01 / 2024-01 / all"
    )
    total_trades: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="总交易数"
    )
    win_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="盈利次数")
    win_rate: Mapped[float] = mapped_column(Float, nullable=False, comment="胜率")
    avg_pnl_pct: Mapped[float] = mapped_column(
        Float, nullable=False, comment="平均盈亏%"
    )
    max_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, comment="最大盈利%")
    min_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, comment="最大亏损%")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("criterion", "period", name="uq_t1_stats_criterion_period"),
        Index("idx_t1_stats_criterion", "criterion"),
    )
