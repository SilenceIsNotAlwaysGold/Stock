"""
数据源管理器 - 多源降级 + 缓存集成
"""

import logging
from typing import Dict, Optional

import pandas as pd

from app.core.cache import CacheManager
from app.core.exceptions import DataSourceError
from dataflows.interface import BaseDataProvider

logger = logging.getLogger(__name__)


class DataSourceManager:
    """数据源管理器 - 自动降级 + 多级缓存"""

    PROVIDER_PRIORITY = ["tushare", "akshare", "baostock"]

    def __init__(self, cache: Optional[CacheManager] = None):
        self.providers: Dict[str, BaseDataProvider] = {}
        self.cache = cache

    def register_provider(self, name: str, provider: BaseDataProvider):
        self.providers[name] = provider

    def _cache_key(self, prefix: str, *args) -> str:
        return f"ds:{prefix}:{':'.join(str(a) for a in args)}"

    async def get_daily_bars(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取日线数据，缓存 → 多源降级"""
        # 查缓存
        if self.cache:
            key = self._cache_key("daily", stock_code, start_date, end_date)
            cached = await self.cache.get(key)
            if cached is not None:
                return pd.DataFrame(cached)

        # 多源降级
        for provider_name in self.PROVIDER_PRIORITY:
            if provider_name not in self.providers:
                continue
            try:
                provider = self.providers[provider_name]
                data = await provider.get_daily(stock_code, start_date, end_date)
                if data is not None and len(data) > 0:
                    logger.info(
                        f"Got daily bars from {provider_name} " f"for {stock_code}"
                    )
                    # 写缓存
                    if self.cache:
                        await self.cache.set(key, data.to_dict(orient="records"))
                    return data
            except Exception as e:
                logger.warning(f"{provider_name} failed for {stock_code}: {e}")
                continue
        raise DataSourceError(f"All providers failed for {stock_code}")

    async def get_stock_list(self) -> pd.DataFrame:
        """获取股票列表，缓存 → 多源降级"""
        if self.cache:
            key = self._cache_key("stock_list")
            cached = await self.cache.get(key)
            if cached is not None:
                return pd.DataFrame(cached)

        for provider_name in self.PROVIDER_PRIORITY:
            if provider_name not in self.providers:
                continue
            try:
                provider = self.providers[provider_name]
                data = await provider.get_stock_list()
                if data is not None and len(data) > 0:
                    logger.info(f"Got stock list from {provider_name}")
                    if self.cache:
                        await self.cache.set(key, data.to_dict(orient="records"))
                    return data
            except Exception as e:
                logger.warning(f"{provider_name} stock list failed: {e}")
                continue
        raise DataSourceError("All providers failed for stock list")

    async def check_data_completeness(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Dict:
        """检查数据完整性"""
        try:
            df = await self.get_daily_bars(stock_code, start_date, end_date)
            trading_days = pd.bdate_range(start_date, end_date)
            actual_days = len(df)
            expected_days = len(trading_days)
            return {
                "stock_code": stock_code,
                "actual_days": actual_days,
                "expected_days": expected_days,
                "completeness": (
                    actual_days / expected_days if expected_days > 0 else 0
                ),
                "missing_dates": expected_days - actual_days,
            }
        except DataSourceError:
            return {
                "stock_code": stock_code,
                "actual_days": 0,
                "expected_days": 0,
                "completeness": 0,
                "missing_dates": -1,
            }
