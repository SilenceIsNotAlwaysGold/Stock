"""
MongoDB document models using Pydantic
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Analyst(BaseModel):
    """Analyst reports for a stock"""

    market_report: Optional[str] = None
    fundamental_report: Optional[str] = None
    news_report: Optional[str] = None
    sentiment_report: Optional[str] = None


class Debate(BaseModel):
    """Bull vs Bear debate"""

    bull_argument: Optional[str] = None
    bear_argument: Optional[str] = None
    research_conclusion: Optional[str] = None


class Decision(BaseModel):
    """Trading decision"""

    action: str  # buy/sell/hold
    confidence: float  # 0-1
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None


class Risk(BaseModel):
    """Risk assessment"""

    assessments: List[str] = Field(default_factory=list)
    final_verdict: Optional[str] = None


class AnalysisReport(BaseModel):
    """Analysis report document for analysis_reports collection"""

    stock_code: str
    stock_name: str
    analysis_date: datetime
    analysts: Analyst
    debate: Debate
    decision: Decision
    risk: Risk
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyAdjustment(BaseModel):
    """Strategy weight adjustment"""

    strategy: str
    old_weight: float
    new_weight: float
    reason: str


class AESEMetrics(BaseModel):
    """AESE performance metrics"""

    avg_win_rate: float
    avg_return: float
    avg_sharpe: float


class AESEHistory(BaseModel):
    """AESE history document for aese_history collection"""

    period: str  # e.g., "2024-Q1"
    strategy_name: str
    adjustments: List[StrategyAdjustment] = Field(default_factory=list)
    metrics: AESEMetrics
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OperationLog(BaseModel):
    """Operation log document for operation_logs collection"""

    user: str
    action: str
    resource: str
    details: Dict[str, Any] = Field(default_factory=dict)
    ip_address: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
