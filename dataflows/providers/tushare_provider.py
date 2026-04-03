"""Tushare 数据源"""

import asyncio
import logging
from typing import Optional

import pandas as pd

from app.config import settings
from dataflows.interface import BaseDataProvider

logger = logging.getLogger(__name__)


class TushareProvider(BaseDataProvider):
    name = "tushare"

    def __init__(self):
        self._api = None

    def _get_api(self):
        if self._api is None:
            import tushare as ts

            ts.set_token(settings.TUSHARE_TOKEN)
            self._api = ts.pro_api()
        return self._api

    async def get_daily(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        def _fetch():
            import tushare as ts

            api = self._get_api()
            df = ts.pro_bar(
                ts_code=stock_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adj="qfq",
            )
            if df is None or df.empty:
                return None
            df = df.rename(
                columns={
                    "trade_date": "date",
                    "vol": "volume",
                    "amount": "amount",
                    "turnover_rate": "turnover_rate",
                }
            )
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            cols = [
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "turnover_rate",
            ]
            for c in cols:
                if c not in df.columns:
                    df[c] = 0.0
            return df[cols].sort_values("date").reset_index(drop=True)

        return await asyncio.to_thread(_fetch)

    async def get_stock_list(self) -> Optional[pd.DataFrame]:
        def _fetch():
            api = self._get_api()
            df = api.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,name,industry,area,market,list_date",
            )
            return df if df is not None and not df.empty else None

        return await asyncio.to_thread(_fetch)
