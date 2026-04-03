"""
LangGraph 交易分析工作流 - 完整实现
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Optional

from langgraph.graph import StateGraph, END

from agents.graph.state import TradingState
from agents.analysts import (
    MarketAnalyst,
    FundamentalAnalyst,
    NewsAnalyst,
    SentimentAnalyst,
)
from agents.researchers import BullResearcher, BearResearcher
from agents.managers import ResearchManager
from agents.risk import RiskManager
from agents.llm.factory import create_llm
from dataflows.source_manager import DataSourceManager

logger = logging.getLogger(__name__)

# 进度回调存储
_progress_callbacks: Dict[str, list] = {}


def _make_analyst_node(analyst_cls, report_key: str, progress: float):
    """创建分析师节点函数"""

    async def node(state: TradingState) -> dict:
        llm = create_llm()
        dm = _get_shared_dm()
        analyst = analyst_cls(llm=llm, data_interface=dm)
        report = await analyst.analyze(state["stock_code"], state["analysis_date"])
        return {
            report_key: report,
            "current_node": analyst_cls.name,
            "progress": progress,
        }

    return node


_shared_dm: Optional[DataSourceManager] = None


def _get_shared_dm() -> DataSourceManager:
    global _shared_dm
    if _shared_dm is None:
        from app.config import settings
        from dataflows.providers import (
            TushareProvider,
            AKShareProvider,
            BaoStockProvider,
        )

        _shared_dm = DataSourceManager()
        if settings.TUSHARE_TOKEN and settings.TUSHARE_ENABLED:
            _shared_dm.register_provider("tushare", TushareProvider())
        _shared_dm.register_provider("akshare", AKShareProvider())
        _shared_dm.register_provider("baostock", BaoStockProvider())
    return _shared_dm


async def bull_researcher_node(state: TradingState) -> dict:
    llm = create_llm()
    researcher = BullResearcher(llm=llm)
    reports = {
        "market_report": state.get("market_report", ""),
        "fundamental_report": state.get("fundamental_report", ""),
        "news_report": state.get("news_report", ""),
        "sentiment_report": state.get("sentiment_report", ""),
    }
    result = await researcher.research(reports)
    return {
        "bull_argument": result,
        "current_node": "bull_researcher",
        "progress": 55,
    }


async def bear_researcher_node(state: TradingState) -> dict:
    llm = create_llm()
    researcher = BearResearcher(llm=llm)
    reports = {
        "market_report": state.get("market_report", ""),
        "fundamental_report": state.get("fundamental_report", ""),
        "news_report": state.get("news_report", ""),
        "sentiment_report": state.get("sentiment_report", ""),
    }
    result = await researcher.research(reports)
    return {
        "bear_argument": result,
        "current_node": "bear_researcher",
        "progress": 65,
    }


async def research_manager_node(state: TradingState) -> dict:
    llm = create_llm()
    manager = ResearchManager(llm=llm)
    conclusion = await manager.conclude(
        state.get("bull_argument", ""),
        state.get("bear_argument", ""),
    )
    return {
        "research_conclusion": conclusion,
        "current_node": "research_manager",
        "progress": 75,
    }


async def risk_assessment_node(state: TradingState) -> dict:
    llm = create_llm()
    risk_mgr = RiskManager(llm=llm)
    assessments = await risk_mgr.full_assessment(
        state.get("research_conclusion", ""),
        state.get("bull_argument", ""),
        state.get("bear_argument", ""),
    )
    return {
        "risk_assessments": assessments,
        "final_risk_verdict": assessments.get("final_verdict", ""),
        "current_node": "risk_assessment",
        "progress": 90,
    }


async def final_decision_node(state: TradingState) -> dict:
    """综合所有分析做出最终决策"""
    conclusion = state.get("research_conclusion", "")
    risk_verdict = state.get("final_risk_verdict", "")

    # 简单解析决策（从研究结论中提取）
    decision = "HOLD"
    confidence = 0.5
    if "买入" in conclusion:
        decision = "BUY"
        confidence = 0.7
    elif "卖出" in conclusion:
        decision = "SELL"
        confidence = 0.7

    # 风控降级
    if "极高" in risk_verdict or "高" in risk_verdict:
        if decision == "BUY":
            confidence *= 0.6

    return {
        "trading_decision": decision,
        "confidence": confidence,
        "current_node": "final_decision",
        "progress": 100,
    }


def build_trading_graph():
    """构建交易分析 LangGraph 工作流"""
    graph = StateGraph(TradingState)

    # 分析师节点
    graph.add_node(
        "market_analyst",
        _make_analyst_node(MarketAnalyst, "market_report", 10),
    )
    graph.add_node(
        "fundamental_analyst",
        _make_analyst_node(FundamentalAnalyst, "fundamental_report", 25),
    )
    graph.add_node(
        "news_analyst",
        _make_analyst_node(NewsAnalyst, "news_report", 35),
    )
    graph.add_node(
        "sentiment_analyst",
        _make_analyst_node(SentimentAnalyst, "sentiment_report", 45),
    )

    # 研究辩论节点
    graph.add_node("bull_researcher", bull_researcher_node)
    graph.add_node("bear_researcher", bear_researcher_node)
    graph.add_node("research_manager", research_manager_node)

    # 风控节点
    graph.add_node("risk_assessment", risk_assessment_node)
    graph.add_node("final_decision", final_decision_node)

    # 工作流连接
    graph.set_entry_point("market_analyst")
    graph.add_edge("market_analyst", "fundamental_analyst")
    graph.add_edge("fundamental_analyst", "news_analyst")
    graph.add_edge("news_analyst", "sentiment_analyst")
    graph.add_edge("sentiment_analyst", "bull_researcher")
    graph.add_edge("bull_researcher", "bear_researcher")
    graph.add_edge("bear_researcher", "research_manager")
    graph.add_edge("research_manager", "risk_assessment")
    graph.add_edge("risk_assessment", "final_decision")
    graph.add_edge("final_decision", END)

    return graph.compile()


async def run_analysis(
    stock_code: str,
    stock_name: str = "",
    analysis_date: str = "",
) -> Dict:
    """运行完整分析流程"""
    if not analysis_date:
        analysis_date = datetime.now().strftime("%Y-%m-%d")

    initial_state: TradingState = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "analysis_date": analysis_date,
        "market_report": "",
        "fundamental_report": "",
        "news_report": "",
        "sentiment_report": "",
        "bull_argument": "",
        "bear_argument": "",
        "debate_rounds": 1,
        "research_conclusion": "",
        "trading_decision": "",
        "confidence": 0.0,
        "target_price": None,
        "stop_loss": None,
        "risk_assessments": {},
        "final_risk_verdict": "",
        "current_node": "start",
        "progress": 0,
        "messages": [],
    }

    workflow = build_trading_graph()
    result = await workflow.ainvoke(initial_state)

    return {
        "id": str(uuid.uuid4()),
        "stock_code": stock_code,
        "stock_name": stock_name,
        "analysis_date": analysis_date,
        "analysts": {
            "market": result.get("market_report", ""),
            "fundamental": result.get("fundamental_report", ""),
            "news": result.get("news_report", ""),
            "sentiment": result.get("sentiment_report", ""),
        },
        "debate": {
            "bull": result.get("bull_argument", ""),
            "bear": result.get("bear_argument", ""),
            "conclusion": result.get("research_conclusion", ""),
        },
        "decision": {
            "action": result.get("trading_decision", "HOLD"),
            "confidence": result.get("confidence", 0),
        },
        "risk": result.get("risk_assessments", {}),
    }
