"""统一数据接口"""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class BaseDataProvider(ABC):
    """数据提供者基类"""

    name: str = ""

    @abstractmethod
    async def get_daily(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        pass

    @abstractmethod
    async def get_stock_list(self) -> Optional[pd.DataFrame]:
        pass

    async def get_money_flow(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """主力资金流向：返回 DataFrame 含 date, main_net_inflow, main_net_inflow_pct"""
        return None

    async def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """全市场每日基本指标（批量）：返回 DataFrame 含 ts_code, turnover_rate, pe, pb, total_mv, circ_mv"""
        return None

    async def get_fina_indicator(self, ts_code: str) -> Optional[pd.DataFrame]:
        """财务指标：返回 DataFrame 含 ts_code, end_date, roe, netprofit_yoy, eps"""
        return None

    async def get_sector_list(self, trade_date: str) -> Optional[pd.DataFrame]:
        """行业板块列表及当日涨幅：返回 DataFrame 含 sector_name, change_pct, rank"""
        return None

    async def get_stock_sector(self, ts_code: str) -> Optional[str]:
        """获取个股所属行业"""
        return None

    async def get_north_flow(self, trade_date: str) -> Optional[pd.DataFrame]:
        """北向资金流向：返回 DataFrame 含 date, north_net_inflow"""
        return None

    async def get_index_daily(
        self, index_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """指数日线：返回 DataFrame 含 date, open, high, low, close, volume"""
        return None
