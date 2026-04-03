"""推荐系统 API"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Query

from app.config import settings
from dataflows.source_manager import DataSourceManager
from dataflows.providers import TushareProvider, AKShareProvider, BaoStockProvider
from engine.registry import StrategyRegistry
from engine.signal_aggregator import SignalAggregator

logger = logging.getLogger(__name__)
router = APIRouter()

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
    top_n: int = Query(10, ge=1, le=50),
    stock_codes: Optional[List[str]] = Query(None),
):
    """获取今日推荐"""
    today = datetime.now().strftime("%Y-%m-%d")
    if today in _recommendations:
        return {"date": today, "recommendations": _recommendations[today][:top_n]}

    # 生成推荐
    recs = await _generate_recommendations(stock_codes, top_n)
    return {"date": today, "recommendations": recs}


@router.get("/history")
async def history_recommendations(
    date: str = Query("", description="查询日期 YYYY-MM-DD"),
):
    """获取历史推荐"""
    if date and date in _recommendations:
        return {"date": date, "recommendations": _recommendations[date]}
    return {"dates": list(_recommendations.keys())}


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
