"""AKShare 数据源"""

import asyncio
import logging
from typing import Optional

import pandas as pd

from dataflows.interface import BaseDataProvider

logger = logging.getLogger(__name__)

# AKShare 中文列名映射
_DAILY_COL_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover_rate",
}


def _ts_code_to_symbol(ts_code: str) -> str:
    """000001.SZ -> 000001"""
    return ts_code.split(".")[0]


class AKShareProvider(BaseDataProvider):
    name = "akshare"

    async def get_daily(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        def _fetch():
            import akshare as ak

            symbol = _ts_code_to_symbol(stock_code)
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns=_DAILY_COL_MAP)
            df["date"] = pd.to_datetime(df["date"])
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
            import akshare as ak

            df = ak.stock_info_a_code_name()
            if df is None or df.empty:
                return None
            df = df.rename(columns={"code": "ts_code", "name": "name"})
            # AKShare 返回纯数字代码，补充后缀
            df["ts_code"] = df["ts_code"].apply(
                lambda x: f"{x}.SH" if str(x).startswith(("6", "9")) else f"{x}.SZ"
            )
            for c in ["industry", "area", "market", "list_date"]:
                if c not in df.columns:
                    df[c] = ""
            return df[["ts_code", "name", "industry", "area", "market", "list_date"]]

        return await asyncio.to_thread(_fetch)
