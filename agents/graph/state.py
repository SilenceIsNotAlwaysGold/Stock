"""
TradingState - Agent 分析工作流状态定义
"""

from typing import TypedDict, Annotated, Dict, Optional, List
from langgraph.graph import add_messages


class TradingState(TypedDict):
    """LangGraph 状态模型"""

    # 输入
    stock_code: str
    stock_name: str
    analysis_date: str

    # 分析师报告
    market_report: str
    fundamental_report: str
    news_report: str
    sentiment_report: str

    # 研究辩论
    bull_argument: str
    bear_argument: str
    debate_rounds: int
    research_conclusion: str

    # 交易决策
    trading_decision: str  # BUY / SELL / HOLD
    confidence: float  # 0-1
    target_price: Optional[float]
    stop_loss: Optional[float]

    # 风险评估
    risk_assessments: Dict[str, str]
    final_risk_verdict: str

    # 进度追踪
    current_node: str
    progress: float  # 0-100
    messages: Annotated[list, add_messages]
