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

    async def get_money_flow(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """主力资金流向：大单 + 特大单净流入"""

        def _fetch():
            api = self._get_api()
            df = api.moneyflow(
                ts_code=stock_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={"trade_date": "date"})
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            # 主力净流入 = 特大单买 + 大单买 - 特大单卖 - 大单卖（万元）
            df["main_net_inflow"] = (
                df.get("buy_elg_amount", 0)
                + df.get("buy_lg_amount", 0)
                - df.get("sell_elg_amount", 0)
                - df.get("sell_lg_amount", 0)
            )
            # 主力净流入占比
            total_col = "total_net_amount" if "total_net_amount" in df.columns else None
            if total_col and df[total_col].abs().sum() > 0:
                df["main_net_inflow_pct"] = df["main_net_inflow"] / df[total_col].abs()
            else:
                df["main_net_inflow_pct"] = 0.0
            cols = ["date", "main_net_inflow", "main_net_inflow_pct"]
            return df[cols].sort_values("date").reset_index(drop=True)

        return await asyncio.to_thread(_fetch)

    async def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """全市场每日基本指标（批量）"""

        def _fetch():
            api = self._get_api()
            df = api.daily_basic(
                trade_date=trade_date.replace("-", ""),
                fields="ts_code,turnover_rate,pe,pb,total_mv,circ_mv",
            )
            if df is None or df.empty:
                return None
            return df[
                ["ts_code", "turnover_rate", "pe", "pb", "total_mv", "circ_mv"]
            ].reset_index(drop=True)

        return await asyncio.to_thread(_fetch)

    async def get_fina_indicator(self, ts_code: str) -> Optional[pd.DataFrame]:
        """财务指标"""

        def _fetch():
            api = self._get_api()
            df = api.fina_indicator(
                ts_code=ts_code,
                fields="ts_code,end_date,roe,netprofit_yoy,eps",
            )
            if df is None or df.empty:
                return None
            return df[
                ["ts_code", "end_date", "roe", "netprofit_yoy", "eps"]
            ].reset_index(drop=True)

        return await asyncio.to_thread(_fetch)

    async def get_north_flow(self, trade_date: str) -> Optional[pd.DataFrame]:
        """北向资金流向"""

        def _fetch():
            api = self._get_api()
            df = api.moneyflow_hsgt(trade_date=trade_date.replace("-", ""))
            if df is None or df.empty:
                return None
            df = df.rename(
                columns={"trade_date": "date", "north_money": "north_net_inflow"}
            )
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            cols = ["date", "north_net_inflow"]
            for c in cols:
                if c not in df.columns:
                    df[c] = 0.0
            return df[cols].reset_index(drop=True)

        return await asyncio.to_thread(_fetch)

    async def get_index_daily(
        self, index_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """指数日线"""

        def _fetch():
            import tushare as ts

            df = ts.pro_bar(
                ts_code=index_code,
                asset="I",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={"trade_date": "date", "vol": "volume"})
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            cols = ["date", "open", "high", "low", "close", "volume"]
            for c in cols:
                if c not in df.columns:
                    df[c] = 0.0
            return df[cols].sort_values("date").reset_index(drop=True)

        return await asyncio.to_thread(_fetch)

    # get_sector_list 和 get_stock_sector 降级到 AKShare，此处返回 None
    async def get_sector_list(self, trade_date: str) -> None:
        return None

    async def get_stock_sector(self, ts_code: str) -> None:
        return None
