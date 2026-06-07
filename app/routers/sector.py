"""板块热度推荐 API"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from engine.sector_heat.heat_scorer import rank_sectors
from engine.sector_heat.llm_analyst import analyze_sectors
from engine.sector_heat.models import SectorRecommendation, SectorReport
from engine.sector_heat.news_fetcher import fetch_stock_news, fetch_telegraph_news
from engine.sector_heat.stock_picker import pick_stocks

logger = logging.getLogger(__name__)
router = APIRouter()


def _sector_score_to_dict(s) -> dict:
    return {
        "name": s.name,
        "code": s.code,
        "heat_score": s.heat_score,
        "score_breakdown": {
            "price_momentum": s.price_score,
            "fund_flow": s.fund_score,
            "heat_acceleration": s.momentum_score,
        },
        "stats": {
            "period_return_pct": s.period_return,
            "today_change_pct": s.today_change,
            "net_inflow_bn": s.net_inflow,
            "up_ratio": round(s.up_ratio, 3),
            "turnover_rate": s.turnover_rate,
            "limit_up_in_period": s.limit_up_in_period,
        },
        "trend": s.trend,
        "leader_stock": s.leader_stock,
        "leader_change_pct": s.leader_change,
        "stock_count": s.stock_count,
    }


def _stock_pick_to_dict(p) -> dict:
    return {
        "ts_code": p.ts_code,
        "name": p.name,
        "role": p.role,
        "score": p.score,
        "today_change_pct": p.today_change,
        "turnover_rate": p.turnover_rate,
        "reason": p.reason,
    }


def _llm_analysis_to_dict(a) -> Optional[dict]:
    if a is None:
        return None
    return {
        "catalyst": a.catalyst,
        "stage": a.stage,
        "pick_direction": a.pick_direction,
        "risks": a.risks,
        "summary": a.summary,
    }


@router.get("/recommend")
async def sector_recommend(
    window_days: int = Query(default=10, ge=3, le=30, description="滚动窗口天数"),
    top_n: int = Query(default=5, ge=1, le=10, description="返回板块数量"),
    stocks_per_sector: int = Query(default=3, ge=1, le=5, description="每板块推荐股票数"),
    with_llm: bool = Query(default=True, description="是否附带 LLM 解读"),
):
    """
    板块热度推荐

    基于近期价格动量 + 资金流向 + 热度加速，筛选出最具关注价值的板块，
    并在每个板块内推荐 2-3 只个股，可选附带 DeepSeek LLM 分析解读。
    """
    logger.info(f"sector_recommend: window={window_days}d top_n={top_n} llm={with_llm}")

    # 1. 板块评分排名
    top_sectors = await rank_sectors(window_days=window_days, top_n=top_n)
    if not top_sectors:
        return {"error": "数据获取失败，请稍后重试", "recommendations": []}

    # 2. 并发：板块内选股 + LLM 分析
    stock_tasks = [pick_stocks(s, top_n=stocks_per_sector) for s in top_sectors]
    llm_task = analyze_sectors(top_sectors, window_days) if with_llm else asyncio.sleep(0, result={})

    stock_results, llm_results = await asyncio.gather(
        asyncio.gather(*stock_tasks),
        llm_task,
    )

    # 3. 组装报告
    recommendations = []
    for sector, stocks in zip(top_sectors, stock_results):
        analysis = llm_results.get(sector.name) if isinstance(llm_results, dict) else None
        rec = SectorRecommendation(sector=sector, stocks=stocks, analysis=analysis)

        recommendations.append({
            "sector": _sector_score_to_dict(sector),
            "stocks": [_stock_pick_to_dict(p) for p in stocks],
            "analysis": _llm_analysis_to_dict(analysis),
        })

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "total_sectors": len(recommendations),
        "recommendations": recommendations,
    }


@router.get("/news/stock/{ts_code}")
async def stock_news(
    ts_code: str,
    days: int = Query(default=7, ge=1, le=30, description="近 N 天"),
    limit: int = Query(default=10, ge=1, le=30),
):
    """个股近 N 天新闻（来自东财）"""
    df = await fetch_stock_news(ts_code, days=days)
    if df is None or df.empty:
        return {"ts_code": ts_code, "items": []}
    items = []
    for _, row in df.head(limit).iterrows():
        items.append({
            "title": str(row.get("title", "")),
            "content": str(row.get("content", ""))[:400],
            "pub_time": str(row.get("timestamp", "")),
            "source": str(row.get("source", "")),
            "url": str(row.get("url", "")),
        })
    return {"ts_code": ts_code, "items": items}


@router.get("/news/telegraph")
async def market_telegraph(
    hours: int = Query(default=24, ge=1, le=72),
    limit: int = Query(default=20, ge=1, le=50),
):
    """财联社近 N 小时电报"""
    df = await fetch_telegraph_news(hours=hours)
    if df is None or df.empty:
        return {"items": []}
    df = df.sort_values("timestamp", ascending=False)
    items = []
    for _, row in df.head(limit).iterrows():
        items.append({
            "title": str(row.get("title", "")),
            "content": str(row.get("content", ""))[:300],
            "pub_time": str(row.get("timestamp", "")),
        })
    return {"items": items}
