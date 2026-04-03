"""市场情绪指标 API"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List

from fastapi import APIRouter, Query

from app.config import settings
from dataflows.source_manager import DataSourceManager
from dataflows.providers import TushareProvider, AKShareProvider, BaoStockProvider

logger = logging.getLogger(__name__)
router = APIRouter()

_emotion_cache: Dict[str, Dict] = {}


@router.get("/today")
async def today_emotion():
    """获取今日市场情绪"""
    today = datetime.now().strftime("%Y-%m-%d")
    if today in _emotion_cache:
        return _emotion_cache[today]

    emotion = await _calculate_emotion()
    _emotion_cache[today] = emotion
    return emotion


@router.get("/history")
async def emotion_history(days: int = Query(30, ge=1, le=365)):
    """获取历史情绪数据"""
    return list(_emotion_cache.values())[-days:]


async def _calculate_emotion() -> Dict:
    """计算市场情绪指标"""
    dm = DataSourceManager()
    if settings.TUSHARE_TOKEN and settings.TUSHARE_ENABLED:
        dm.register_provider("tushare", TushareProvider())
    dm.register_provider("akshare", AKShareProvider())
    dm.register_provider("baostock", BaoStockProvider())

    # 用几只代表性股票计算市场情绪
    sample_codes = [
        "000001.SZ",
        "600519.SH",
        "000858.SZ",
        "601318.SH",
        "000333.SZ",
        "600036.SH",
        "601166.SH",
        "000651.SZ",
        "600276.SH",
        "601888.SH",
    ]

    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

    up_count = 0
    down_count = 0
    total_change = 0.0
    avg_volume_ratio = 0.0
    valid = 0

    for code in sample_codes:
        try:
            df = await dm.get_daily_bars(code, start, today)
            if df is None or len(df) < 2:
                continue
            last = float(df.iloc[-1]["close"])
            prev = float(df.iloc[-2]["close"])
            change = (last - prev) / prev
            total_change += change

            if change > 0:
                up_count += 1
            else:
                down_count += 1

            vol_today = float(df.iloc[-1]["volume"])
            vol_avg = float(df["volume"].mean())
            avg_volume_ratio += vol_today / max(vol_avg, 1)
            valid += 1
        except Exception as e:
            logger.warning(f"Emotion calc failed for {code}: {e}")

    if valid == 0:
        return {"date": today, "score": 50, "status": "unknown"}

    avg_change = total_change / valid * 100
    avg_volume_ratio = avg_volume_ratio / valid
    up_ratio = (
        up_count / (up_count + down_count) if (up_count + down_count) > 0 else 0.5
    )

    # 情绪评分 0-100
    score = 50 + avg_change * 10 + (up_ratio - 0.5) * 40
    score = max(0, min(100, score))

    if score >= 80:
        status = "狂热"
    elif score >= 65:
        status = "乐观"
    elif score >= 45:
        status = "中性"
    elif score >= 30:
        status = "谨慎"
    else:
        status = "恐慌"

    return {
        "date": today,
        "score": round(score, 1),
        "status": status,
        "up_count": up_count,
        "down_count": down_count,
        "avg_change_pct": round(avg_change, 2),
        "volume_ratio": round(avg_volume_ratio, 2),
        "sample_size": valid,
    }
