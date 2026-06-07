"""统一数据源适配层 — Tushare/AKShare/Sina/Tencent 多源容灾"""
from engine.data_source.unified import (
    fetch_realtime_quote,
    fetch_daily_bars,
    fetch_market_overview,
    DataSourceError,
)

__all__ = [
    "fetch_realtime_quote",
    "fetch_daily_bars",
    "fetch_market_overview",
    "DataSourceError",
]
