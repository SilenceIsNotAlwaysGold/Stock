"""
LangGraph 交易分析工作流
"""

from langgraph.graph import StateGraph, END
from agents.graph.state import TradingState


def build_trading_graph():
    """构建交易分析 LangGraph 工作流"""
    graph = StateGraph(TradingState)

    # TODO: T-010 实现完整节点函数
    # 占位节点 - 后续任务中实现
    async def placeholder_node(state: TradingState) -> dict:
        return {"current_node": "placeholder", "progress": 0}

    graph.add_node("market_analyst", placeholder_node)
    graph.add_node("fundamental_analyst", placeholder_node)
    graph.add_node("news_analyst", placeholder_node)
    graph.add_node("sentiment_analyst", placeholder_node)
    graph.add_node("bull_researcher", placeholder_node)
    graph.add_node("bear_researcher", placeholder_node)
    graph.add_node("research_manager", placeholder_node)
    graph.add_node("risk_assessment", placeholder_node)
    graph.add_node("final_decision", placeholder_node)

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
