"""推荐系统 API"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.models.pg_models import DailyBar, Stock
from app.services import news_reco
from dataflows.source_manager import DataSourceManager
from dataflows.providers import TushareProvider, AKShareProvider, BaoStockProvider
from engine.registry import StrategyRegistry
from engine.signal_aggregator import SignalAggregator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/news-driven")
async def news_driven_recommendations(
    top_n: int = Query(15, ge=1, le=50),
    hours: int = Query(24, ge=1, le=72),
    db: AsyncSession = Depends(get_db),
):
    """
    消息面驱动推荐：财联社近 N 小时电报 → 热门板块 → 受影响个股
    （新闻热度 × 量化强度排序）。
    """
    return await news_reco.recommend_by_news(db, top_n=top_n, hours=hours)

_recommendations: Dict[str, List] = {}

# 常用 A 股名称映射
STOCK_NAMES: Dict[str, str] = {
    "000001.SZ": "平安银行",
    "000002.SZ": "万科A",
    "000333.SZ": "美的集团",
    "000651.SZ": "格力电器",
    "000858.SZ": "五粮液",
    "002594.SZ": "比亚迪",
    "600000.SH": "浦发银行",
    "600036.SH": "招商银行",
    "600519.SH": "贵州茅台",
    "601318.SH": "中国平安",
    "601398.SH": "工商银行",
    "600276.SH": "恒瑞医药",
    "300750.SZ": "宁德时代",
    "601012.SH": "隆基绿能",
    "600900.SH": "长江电力",
}


@router.get("/today")
async def today_recommendations(
    top_n: int = Query(20, ge=1, le=50),
    refresh: bool = Query(False, description="强制重算"),
    db: AsyncSession = Depends(get_db),
):
    """
    今日推荐（全市场 DB 多策略共振，0-100 评分，仅出可操作信号）。
    结果按日缓存；refresh=true 强制重算。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    as_of_row = await db.execute(select(func.max(DailyBar.trade_date)))
    as_of = as_of_row.scalar()
    as_of_s = str(as_of) if as_of else today

    if not refresh and today in _recommendations:
        return {"date": today, "as_of": as_of_s,
                "count": len(_recommendations[today]),
                "recommendations": _recommendations[today][:top_n]}

    recs = await _generate_recommendations_db(db)
    _recommendations[today] = recs
    return {"date": today, "as_of": as_of_s, "count": len(recs),
            "recommendations": recs[:top_n]}


@router.get("/history")
async def history_recommendations(
    date: str = Query("", description="查询日期 YYYY-MM-DD"),
):
    """获取历史推荐"""
    if date and date in _recommendations:
        return {"date": date, "recommendations": _recommendations[date]}
    return {"dates": list(_recommendations.keys())}


_EXCL_PREFIX = ("688", "300", "301", "8", "4", "920")


async def _generate_recommendations_db(db: AsyncSession) -> List:
    """
    全市场 DB 多策略共振推荐。
    流程：取在册可交易股 → 近 80 日列级日线 → 按流动性截取候选
         → SignalAggregator 多策略 → 0-100 评分 → 仅留可操作(偏多)信号。
    """
    import pandas as pd

    StrategyRegistry.auto_discover()
    aggregator = SignalAggregator()

    srows = await db.execute(
        select(Stock.ts_code, Stock.name)
        .where(Stock.is_active == True)
    )
    name_map = {}
    for r in srows.all():
        code = r.ts_code.split(".")[0]
        nm = r.name or ""
        if code.startswith(_EXCL_PREFIX) or "ST" in nm.upper():
            continue
        name_map[r.ts_code] = nm
    if not name_map:
        return []

    rows = await db.execute(
        select(DailyBar.ts_code, DailyBar.trade_date, DailyBar.open,
               DailyBar.high, DailyBar.low, DailyBar.close,
               DailyBar.volume, DailyBar.amount)
        .where(DailyBar.ts_code.in_(list(name_map.keys())))
        .order_by(DailyBar.ts_code, DailyBar.trade_date)
    )
    by_code: Dict[str, list] = defaultdict(list)
    for r in rows.all():
        by_code[r.ts_code].append(r)

    # 流动性预筛：按近 5 日平均成交额排序，取前 1500 只控制计算量
    liq = []
    for code, recs in by_code.items():
        if len(recs) < 30:
            continue
        amt5 = [float(x.amount or 0) for x in recs[-5:]]
        liq.append((code, sum(amt5) / max(len(amt5), 1)))
    liq.sort(key=lambda x: -x[1])
    candidates = [c for c, _ in liq[:1500]]

    results = []
    for code in candidates:
        recs = by_code[code][-80:]
        df = pd.DataFrame([{
            "date": str(x.trade_date).replace("-", ""),
            "open": float(x.open or 0), "high": float(x.high or 0),
            "low": float(x.low or 0), "close": float(x.close or 0),
            "volume": float(x.volume or 0), "amount": float(x.amount or 0),
        } for x in recs])
        if df["close"].iloc[-1] <= 0:
            continue
        try:
            agg = aggregator.aggregate(df)
        except Exception as e:
            logger.debug(f"aggregate {code} 失败: {e}")
            continue

        buy_c, sell_c = agg["buy_count"], agg["sell_count"]
        # 仅保留可操作（偏多）信号
        if not (agg["action"] == "BUY" or (buy_c >= 2 and buy_c > sell_c)):
            continue
        # 0-100 综合评分：基准50 + 共振方向强度 + 跨类别共振 + 净买入
        score100 = 50 + agg["score"] * 45 + \
            (8 if agg["resonance"]["buy_resonance"] else 0) + \
            (buy_c - sell_c) * 2.5
        score100 = round(max(0.0, min(100.0, score100)), 1)
        chg = 0.0
        if len(df) >= 2 and df["close"].iloc[-2] > 0:
            chg = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
        results.append({
            "ts_code": code, "name": name_map.get(code, ""),
            "score": score100, "action": agg["action"],
            "buy_count": buy_c, "sell_count": sell_c,
            "resonance": agg["resonance"]["buy_resonance"],
            "today_chg_pct": round(chg, 2),
            "signals": agg["signals"],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


async def _generate_recommendations(
    stock_codes: Optional[List[str]], top_n: int
) -> List:
    dm = DataSourceManager()
    if settings.TUSHARE_TOKEN and settings.TUSHARE_ENABLED:
        dm.register_provider("tushare", TushareProvider())
    dm.register_provider("akshare", AKShareProvider())
    dm.register_provider("baostock", BaoStockProvider())

    StrategyRegistry.auto_discover()
    aggregator = SignalAggregator()

    if not stock_codes:
        stock_codes = [
            "000001.SZ",
            "600519.SH",
            "000858.SZ",
            "601318.SH",
            "000333.SZ",
        ]

    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    results = []
    for code in stock_codes:
        try:
            df = await dm.get_daily_bars(code, start, today)
            agg = aggregator.aggregate(df)
            results.append(
                {
                    "ts_code": code,
                    "name": STOCK_NAMES.get(code, ""),
                    "score": agg["score"],
                    "action": agg["action"],
                    "buy_count": agg["buy_count"],
                    "sell_count": agg["sell_count"],
                    "resonance": agg["resonance"]["buy_resonance"],
                    "signals": agg["signals"],
                }
            )
        except Exception as e:
            logger.warning(f"Failed to analyze {code}: {e}")

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:top_n]

    _recommendations[today] = results
    return results
