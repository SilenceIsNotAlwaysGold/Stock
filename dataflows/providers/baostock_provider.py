"""BaoStock 数据源"""

import asyncio
import logging
from typing import Optional

import pandas as pd

from dataflows.interface import BaseDataProvider

logger = logging.getLogger(__name__)


def _to_baostock_code(ts_code: str) -> str:
    """000001.SZ -> sz.000001"""
    parts = ts_code.split(".")
    if len(parts) == 2:
        code, market = parts
        return f"{market.lower()}.{code}"
    return ts_code


def _safe_float(val, default=0.0):
    try:
        return float(val) if val and val != "" else default
    except (ValueError, TypeError):
        return default


class BaoStockProvider(BaseDataProvider):
    name = "baostock"

    async def get_daily(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        def _fetch():
            import baostock as bs

            bs.login()
            try:
                bs_code = _to_baostock_code(stock_code)
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume,amount,turn",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2",  # 前复权
                )
                rows = []
                while (rs.error_code == "0") and rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    return None
                df = pd.DataFrame(
                    rows,
                    columns=[
                        "date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "turnover_rate",
                    ],
                )
                for c in [
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "turnover_rate",
                ]:
                    df[c] = df[c].apply(_safe_float)
                df["date"] = pd.to_datetime(df["date"])
                return df.sort_values("date").reset_index(drop=True)
            finally:
                bs.logout()

        return await asyncio.to_thread(_fetch)

    async def get_stock_list(self) -> Optional[pd.DataFrame]:
        def _fetch():
            import baostock as bs

            bs.login()
            try:
                rs = bs.query_stock_basic()
                rows = []
                while (rs.error_code == "0") and rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    return None
                df = pd.DataFrame(rows, columns=rs.fields)
                # 过滤 A 股
                df = df[df["type"] == "1"].copy()
                # 转换代码格式: sz.000001 -> 000001.SZ
                df["ts_code"] = df["code"].apply(
                    lambda x: f"{x[3:]}.{x[:2].upper()}" if "." in x else x
                )
                df = df.rename(
                    columns={
                        "code_name": "name",
                    }
                )
                for c in ["industry", "area", "market", "list_date"]:
                    if c not in df.columns:
                        df[c] = ""
                return df[
                    ["ts_code", "name", "industry", "area", "market", "list_date"]
                ]
            finally:
                bs.logout()

        return await asyncio.to_thread(_fetch)
