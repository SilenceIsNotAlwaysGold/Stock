"""股票数据 API"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models.schemas import StockInfo, DailyBarData
from dataflows.source_manager import DataSourceManager
from dataflows.providers import TushareProvider, AKShareProvider, BaoStockProvider

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_data_manager() -> DataSourceManager:
    mgr = DataSourceManager()
    if settings.TUSHARE_TOKEN and settings.TUSHARE_ENABLED:
        mgr.register_provider("tushare", TushareProvider())
    mgr.register_provider("akshare", AKShareProvider())
    mgr.register_provider("baostock", BaoStockProvider())
    return mgr


_dm: Optional[DataSourceManager] = None


def get_dm() -> DataSourceManager:
    global _dm
    if _dm is None:
        _dm = _get_data_manager()
    return _dm


@router.get("/list", response_model=List[StockInfo])
async def stock_list(
    keyword: str = Query("", description="搜索关键词"),
    limit: int = Query(50, ge=1, le=500),
):
    """获取股票列表"""
    try:
        dm = get_dm()
        df = await dm.get_stock_list()
        if keyword:
            mask = df["ts_code"].str.contains(keyword, case=False) | df[
                "name"
            ].str.contains(keyword, case=False)
            df = df[mask]
        df = df.head(limit)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"Failed to get stock list: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/daily", response_model=List[DailyBarData])
async def stock_daily(
    code: str,
    start_date: str = Query("", description="开始日期 YYYY-MM-DD"),
    end_date: str = Query("", description="结束日期 YYYY-MM-DD"),
):
    """获取日线数据"""
    try:
        dm = get_dm()
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        df = await dm.get_daily_bars(code, start_date, end_date)
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "trade_date": str(row["date"])[:10],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "amount": float(row.get("amount", 0)),
                }
            )
        return records
    except Exception as e:
        logger.error(f"Failed to get daily bars for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def stock_sync():
    """触发数据同步（占位，后续实现批量同步）"""
    return {"status": "started", "message": "Data sync triggered"}


@router.get("/{code}/completeness")
async def stock_completeness(
    code: str,
    start_date: str = Query("", description="开始日期"),
    end_date: str = Query("", description="结束日期"),
):
    """检查数据完整性"""
    dm = get_dm()
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    result = await dm.check_data_completeness(code, start_date, end_date)
    return result
