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
