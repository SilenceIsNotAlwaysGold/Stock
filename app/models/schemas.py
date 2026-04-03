"""
Pydantic 请求/响应模型
"""

from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# --- Analysis ---
class AnalyzeRequest(BaseModel):
    stock_code: str = Field(..., description="股票代码, e.g. 000001.SZ")
    stock_name: str = ""


class AnalysisProgress(BaseModel):
    task_id: str
    status: str  # pending / running / completed / failed
    progress: float = 0
    current_node: str = ""
    message: str = ""


class AnalysisReport(BaseModel):
    id: str
    stock_code: str
    stock_name: str
    analysis_date: str
    analysts: Dict[str, str] = {}
    debate: Dict[str, str] = {}
    decision: Dict = {}
    risk: Dict = {}
    created_at: Optional[datetime] = None


# --- Stocks ---
class StockInfo(BaseModel):
    ts_code: str
    name: str
    industry: str = ""
    area: str = ""
    market: str = ""
    list_date: str = ""


class DailyBarData(BaseModel):
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0


# --- Strategy ---
class StrategySignalResponse(BaseModel):
    strategy_name: str
    action: str
    confidence: float
    reason: str = ""


class RecommendationResponse(BaseModel):
    trade_date: str
    ts_code: str
    stock_name: str
    score: float
    strategies: List[str] = []
    agent_summary: str = ""


# --- Paper Trading ---
class PaperOrderRequest(BaseModel):
    ts_code: str
    stock_name: str = ""
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)


class PaperAccountResponse(BaseModel):
    id: int
    name: str
    initial_cash: float
    current_cash: float
    total_market_value: float = 0
    total_pnl: float = 0
    total_pnl_pct: float = 0


class PaperPositionResponse(BaseModel):
    ts_code: str
    stock_name: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


# --- Config ---
class ConfigItem(BaseModel):
    key: str
    value: str
    category: str = ""
    description: str = ""


# --- T+1 隔夜策略 ---
class T1CandidateResponse(BaseModel):
    id: int
    scan_date: str
    ts_code: str
    stock_name: str
    criterion: str
    score: float
    close_price: Optional[float] = None
    change_pct: Optional[float] = None
    volume_ratio: Optional[float] = None
    turnover_rate: Optional[float] = None
    status: str
    reason: str = ""


class T1BuyRequest(BaseModel):
    candidate_id: int = Field(..., description="候选股ID")
    quantity: int = Field(100, gt=0, description="买入数量（股）")


class T1PositionResponse(BaseModel):
    id: int
    ts_code: str
    stock_name: str
    buy_date: str
    buy_price: float
    quantity: int
    criterion: str
    status: str


class T1TradeResponse(BaseModel):
    id: int
    ts_code: str
    stock_name: str
    criterion: str
    buy_date: str
    buy_price: float
    sell_date: str
    sell_price: float
    quantity: int
    sell_reason: str
    pnl: float
    pnl_pct: float
    is_win: bool


class T1StatsResponse(BaseModel):
    criterion: str
    period: str
    total_trades: int
    win_count: int
    win_rate: float
    avg_pnl_pct: float
    max_pnl_pct: Optional[float] = None
    min_pnl_pct: Optional[float] = None


class T1BacktestRequest(BaseModel):
    start_date: str = Field(..., description="回测开始日期 YYYYMMDD")
    end_date: str = Field(..., description="回测结束日期 YYYYMMDD")
    criteria: List[str] = Field(
        default=["limit_reopen", "tail_surge", "sector_leader"],
        description="回测的选股条件列表",
    )
    initial_cash: float = Field(100000, description="初始资金")
