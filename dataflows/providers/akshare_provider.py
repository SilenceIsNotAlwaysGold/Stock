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

# 资金流向中文列名映射
_MONEY_FLOW_COL_MAP = {
    "日期": "date",
    "主力净流入-净额": "main_net_inflow",
    "主力净流入-净占比": "main_net_inflow_pct",
}

# 全市场行情中文列名映射（stock_zh_a_spot_em）
_SPOT_COL_MAP = {
    "代码": "ts_code",
    "换手率": "turnover_rate",
    "市盈率-动态": "pe",
    "市净率": "pb",
    "总市值": "total_mv",
    "流通市值": "circ_mv",
}

# 行业板块列名映射（stock_board_industry_name_em）
_SECTOR_COL_MAP = {
    "板块名称": "sector_name",
    "涨跌幅": "change_pct",
    "排名": "rank",
}

# 北向资金列名映射
_NORTH_FLOW_COL_MAP = {
    "日期": "date",
    "当日成交净买额": "north_net_inflow",
}

# 指数日线列名映射
_INDEX_DAILY_COL_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
}


def _ts_code_to_symbol(ts_code: str) -> str:
    """000001.SZ -> 000001"""
    return ts_code.split(".")[0]


def _ts_code_to_index_symbol(ts_code: str) -> str:
    """000001.SH -> sh000001，399001.SZ -> sz399001"""
    code, market = ts_code.split(".")
    return f"{market.lower()}{code}"


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

    async def get_money_flow(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """主力资金流向"""

        def _fetch():
            try:
                import akshare as ak

                symbol = _ts_code_to_symbol(stock_code)
                # 判断市场：SH->sh，SZ->sz
                market = "sh" if stock_code.endswith(".SH") else "sz"
                df = ak.stock_individual_fund_flow(stock=symbol, market=market)
                if df is None or df.empty:
                    return None
                df = df.rename(columns=_MONEY_FLOW_COL_MAP)
                if "date" not in df.columns:
                    return None
                df["date"] = pd.to_datetime(df["date"])
                # 过滤日期范围
                s = pd.to_datetime(start_date)
                e = pd.to_datetime(end_date)
                df = df[(df["date"] >= s) & (df["date"] <= e)]
                if df.empty:
                    return None
                cols = ["date", "main_net_inflow", "main_net_inflow_pct"]
                for c in cols:
                    if c not in df.columns:
                        df[c] = 0.0
                return df[cols].sort_values("date").reset_index(drop=True)
            except Exception as exc:
                logger.warning(f"AKShare get_money_flow failed for {stock_code}: {exc}")
                return None

        return await asyncio.to_thread(_fetch)

    async def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """全市场每日基本指标（实时行情快照）"""

        def _fetch():
            try:
                import akshare as ak

                df = ak.stock_zh_a_spot_em()
                if df is None or df.empty:
                    return None
                df = df.rename(columns=_SPOT_COL_MAP)
                # 补充后缀：6/9开头 -> SH，其余 -> SZ
                if "ts_code" in df.columns:
                    df["ts_code"] = df["ts_code"].apply(
                        lambda x: f"{x}.SH"
                        if str(x).startswith(("6", "9"))
                        else f"{x}.SZ"
                    )
                cols = ["ts_code", "turnover_rate", "pe", "pb", "total_mv", "circ_mv"]
                for c in cols:
                    if c not in df.columns:
                        df[c] = None
                return df[cols].reset_index(drop=True)
            except Exception as exc:
                logger.warning(f"AKShare get_daily_basic failed: {exc}")
                return None

        return await asyncio.to_thread(_fetch)

    async def get_fina_indicator(self, ts_code: str) -> Optional[pd.DataFrame]:
        """财务指标"""

        def _fetch():
            try:
                import akshare as ak

                symbol = _ts_code_to_symbol(ts_code)
                df = ak.stock_financial_analysis_indicator(symbol=symbol)
                if df is None or df.empty:
                    return None
                # 尝试通用列名映射（AKShare 列名可能随版本变动）
                col_map = {}
                for col in df.columns:
                    if "净资产收益率" in col or "ROE" in col.upper():
                        col_map[col] = "roe"
                    elif "净利润增长率" in col or "净利润同比" in col:
                        col_map[col] = "netprofit_yoy"
                    elif "每股收益" in col or "EPS" in col.upper():
                        col_map[col] = "eps"
                    elif "报告期" in col or "日期" in col:
                        col_map[col] = "end_date"
                df = df.rename(columns=col_map)
                df["ts_code"] = ts_code
                cols = ["ts_code", "end_date", "roe", "netprofit_yoy", "eps"]
                for c in cols:
                    if c not in df.columns:
                        df[c] = None
                return df[cols].reset_index(drop=True)
            except Exception as exc:
                logger.warning(f"AKShare get_fina_indicator failed for {ts_code}: {exc}")
                return None

        return await asyncio.to_thread(_fetch)

    async def get_sector_list(self, trade_date: str) -> Optional[pd.DataFrame]:
        """行业板块列表及当日涨幅"""

        def _fetch():
            try:
                import akshare as ak

                df = ak.stock_board_industry_name_em()
                if df is None or df.empty:
                    return None
                df = df.rename(columns=_SECTOR_COL_MAP)
                cols = ["sector_name", "change_pct", "rank"]
                for c in cols:
                    if c not in df.columns:
                        df[c] = None
                # 如果没有 rank 列，按涨跌幅排序生成
                if df["rank"].isnull().all():
                    df = df.sort_values("change_pct", ascending=False).reset_index(
                        drop=True
                    )
                    df["rank"] = df.index + 1
                return df[cols].reset_index(drop=True)
            except Exception as exc:
                logger.warning(f"AKShare get_sector_list failed: {exc}")
                return None

        return await asyncio.to_thread(_fetch)

    async def get_stock_sector(self, ts_code: str) -> Optional[str]:
        """获取个股所属行业（从板块列表中查找）"""

        def _fetch():
            try:
                import akshare as ak

                symbol = _ts_code_to_symbol(ts_code)
                df = ak.stock_board_industry_cons_em(symbol=symbol)
                if df is None or df.empty:
                    return None
                # 返回第一个匹配的板块名
                for col in df.columns:
                    if "板块" in col or "行业" in col or "名称" in col:
                        vals = df[col].dropna().tolist()
                        if vals:
                            return str(vals[0])
                return None
            except Exception as exc:
                logger.warning(
                    f"AKShare get_stock_sector failed for {ts_code}: {exc}"
                )
                return None

        return await asyncio.to_thread(_fetch)

    async def get_north_flow(self, trade_date: str) -> Optional[pd.DataFrame]:
        """北向资金流向"""

        def _fetch():
            try:
                import akshare as ak

                df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
                if df is None or df.empty:
                    return None
                df = df.rename(columns=_NORTH_FLOW_COL_MAP)
                if "date" not in df.columns:
                    return None
                df["date"] = pd.to_datetime(df["date"])
                # 过滤到指定日期
                target = pd.to_datetime(trade_date)
                df = df[df["date"] == target]
                if df.empty:
                    return None
                cols = ["date", "north_net_inflow"]
                for c in cols:
                    if c not in df.columns:
                        df[c] = 0.0
                return df[cols].reset_index(drop=True)
            except Exception as exc:
                logger.warning(f"AKShare get_north_flow failed: {exc}")
                return None

        return await asyncio.to_thread(_fetch)

    async def get_index_daily(
        self, index_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """指数日线"""

        def _fetch():
            try:
                import akshare as ak

                symbol = _ts_code_to_index_symbol(index_code)
                df = ak.stock_zh_index_daily(symbol=symbol)
                if df is None or df.empty:
                    return None
                df = df.rename(columns=_INDEX_DAILY_COL_MAP)
                if "date" not in df.columns:
                    return None
                df["date"] = pd.to_datetime(df["date"])
                s = pd.to_datetime(start_date)
                e = pd.to_datetime(end_date)
                df = df[(df["date"] >= s) & (df["date"] <= e)]
                if df.empty:
                    return None
                cols = ["date", "open", "high", "low", "close", "volume"]
                for c in cols:
                    if c not in df.columns:
                        df[c] = 0.0
                return df[cols].sort_values("date").reset_index(drop=True)
            except Exception as exc:
                logger.warning(
                    f"AKShare get_index_daily failed for {index_code}: {exc}"
                )
                return None

        return await asyncio.to_thread(_fetch)
