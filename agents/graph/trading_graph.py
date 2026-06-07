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


import asyncio as _asyncio
import time as _time

# 单步软超时（秒）：分析师含实时数据 fetch + LLM 较慢，给足时间避免误降级；
# 4 阶段并发编排，最坏 wall-time 仍受控（<300s 端点预算内）
_STEP_TIMEOUT = 95


async def _safe(coro, label: str, fallback: str):
    """带软超时的 LLM 步骤；超时/异常 → 降级占位文本，不中断整链。"""
    t0 = _time.perf_counter()
    try:
        r = await _asyncio.wait_for(coro, timeout=_STEP_TIMEOUT)
        logger.info(f"[多Agent] {label} OK ({_time.perf_counter()-t0:.1f}s)")
        return r
    except _asyncio.TimeoutError:
        logger.warning(f"[多Agent] {label} 超时 >{_STEP_TIMEOUT}s → 降级")
        return f"（{label}：LLM 响应超时，本环节降级跳过）"
    except Exception as e:
        logger.warning(f"[多Agent] {label} 失败 → 降级：{e}")
        return f"（{label}：分析失败 {str(e)[:80]}）"


async def run_analysis(
    stock_code: str,
    stock_name: str = "",
    analysis_date: str = "",
) -> Dict:
    """
    运行完整多 Agent 分析（并发编排版）。

    优化：原 LangGraph 9 节点全串行(~8 次 LLM)必然超时；
    现改为 4 分析师并发 → 多空并发 → 经理 → 风控 → 决策，
    每步软超时降级，整链 wall-time 大幅下降。
    """
    if not analysis_date:
        analysis_date = datetime.now().strftime("%Y-%m-%d")

    dm = _get_shared_dm()
    _g0 = _time.perf_counter()
    logger.info(f"[多Agent] {stock_code} 开始：4 分析师并发…")

    # ── 阶段1：4 分析师并发 ──
    async def _run_analyst(cls):
        a = cls(llm=create_llm(), data_interface=dm)
        return await a.analyze(stock_code, analysis_date)

    market, fundamental, news, sentiment = await _asyncio.gather(
        _safe(_run_analyst(MarketAnalyst), "市场分析师", "（市场面分析降级）"),
        _safe(_run_analyst(FundamentalAnalyst), "基本面分析师", "（基本面分析降级）"),
        _safe(_run_analyst(NewsAnalyst), "新闻分析师", "（消息面分析降级）"),
        _safe(_run_analyst(SentimentAnalyst), "情绪分析师", "（情绪面分析降级）"),
    )
    reports = {
        "market_report": market, "fundamental_report": fundamental,
        "news_report": news, "sentiment_report": sentiment,
    }
    logger.info(f"[多Agent] {stock_code} 分析师完成 "
                f"({_time.perf_counter()-_g0:.1f}s)；多空辩论并发…")

    # ── 阶段2：多空研究员并发 ──
    bull, bear = await _asyncio.gather(
        _safe(BullResearcher(llm=create_llm()).research(reports),
              "多头研究员", "（多头观点降级）"),
        _safe(BearResearcher(llm=create_llm()).research(reports),
              "空头研究员", "（空头观点降级）"),
    )

    # ── 阶段3：研究经理总结 ──
    conclusion = await _safe(
        ResearchManager(llm=create_llm()).conclude(bull, bear),
        "研究经理", "（结论降级：多空分歧，建议观望）")

    # ── 阶段4：风控评估 ──
    risk = await _safe(
        RiskManager(llm=create_llm()).full_assessment(conclusion, bull, bear),
        "风控经理", {})
    if not isinstance(risk, dict):
        risk = {"final_verdict": str(risk)}
    risk_verdict = risk.get("final_verdict", "") if isinstance(risk, dict) else ""

    # ── 阶段5：最终决策（规则，无 LLM）──
    decision, confidence = "HOLD", 0.5
    if "买入" in conclusion:
        decision, confidence = "BUY", 0.7
    elif "卖出" in conclusion:
        decision, confidence = "SELL", 0.7
    if ("极高" in risk_verdict or "高" in risk_verdict) and decision == "BUY":
        confidence *= 0.6
    logger.info(f"[多Agent] {stock_code} 完成 {decision} "
                f"| 总 {_time.perf_counter()-_g0:.1f}s")

    return {
        "id": str(uuid.uuid4()),
        "stock_code": stock_code,
        "stock_name": stock_name,
        "analysis_date": analysis_date,
        "status": "completed",
        "analysts": {
            "market": market, "fundamental": fundamental,
            "news": news, "sentiment": sentiment,
        },
        "debate": {
            "bull": bull, "bear": bear, "conclusion": conclusion,
        },
        "decision": {
            "action": decision,
            "confidence": confidence,
        },
        "risk": risk,
    }
