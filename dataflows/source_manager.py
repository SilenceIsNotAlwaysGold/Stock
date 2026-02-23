"""
数据源管理器 - 多源降级
"""

import logging
from typing import Dict, Optional

import pandas as pd

from app.core.exceptions import DataSourceError

logger = logging.getLogger(__name__)


class DataSourceManager:
    """数据源管理器 - 自动降级"""

    PROVIDER_PRIORITY = ["tushare", "akshare", "baostock"]

    def __init__(self):
        self.providers: Dict = {}

    def register_provider(self, name: str, provider):
        self.providers[name] = provider

    async def get_daily_bars(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取日线数据，自动降级"""
        for provider_name in self.PROVIDER_PRIORITY:
            if provider_name not in self.providers:
                continue
            try:
                provider = self.providers[provider_name]
                data = await provider.get_daily(stock_code, start_date, end_date)
                if data is not None and len(data) > 0:
                    logger.info(f"Got daily bars from {provider_name} for {stock_code}")
                    return data
            except Exception as e:
                logger.warning(f"{provider_name} failed for {stock_code}: {e}")
                continue
        raise DataSourceError(f"All providers failed for {stock_code}")

    async def get_stock_list(self) -> pd.DataFrame:
        """获取股票列表，自动降级"""
        for provider_name in self.PROVIDER_PRIORITY:
            if provider_name not in self.providers:
                continue
            try:
                provider = self.providers[provider_name]
                data = await provider.get_stock_list()
                if data is not None and len(data) > 0:
                    return data
            except Exception as e:
                logger.warning(f"{provider_name} stock list failed: {e}")
                continue
        raise DataSourceError("All providers failed for stock list")
