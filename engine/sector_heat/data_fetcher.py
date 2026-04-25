"""
AKShare 数据采集层 — 概念板块快照 / 资金流 / 历史行情 / 成分股

数据源选择策略（按可用性）：
  快照主数据   → 同花顺 stock_fund_flow_concept (稳定)
  历史价格     → 同花顺 stock_board_concept_index_ths (稳定)
  成分股       → 东财 stock_board_concept_cons_em (偶发超时，有 fallback)
  板块代码映射 → 同花顺 stock_board_concept_name_ths (稳定)

东财 push2.eastmoney.com 系列接口在部分网络环境下不可达，已规避使用。
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# 避免系统代理干扰（同花顺/东财直连）
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

_CACHE: Dict[str, Tuple[float, object]] = {}
_CACHE_TTL = 300  # 5 分钟


def _get_cache(key: str):
    entry = _CACHE.get(key)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _set_cache(key: str, value):
    _CACHE[key] = (time.time(), value)


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _date_n_days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n + 5)).strftime("%Y%m%d")


# ---------- 同步采集函数 ----------

def _fetch_concept_fund_flow_sync() -> pd.DataFrame:
    """
    同花顺概念资金流（即时）
    返回列：name, today_change, net_inflow, inflow, outflow, stock_count,
            leader_stock, leader_change
    净额单位：亿元
    """
    import akshare as ak
    df = ak.stock_fund_flow_concept(symbol="即时")
    df = df.rename(columns={
        "序号": "rank",
        "行业": "name",
        "行业指数": "index_val",
        "行业-涨跌幅": "today_change",
        "流入资金": "inflow",
        "流出资金": "outflow",
        "净额": "net_inflow",
        "公司家数": "stock_count",
        "领涨股": "leader_stock",
        "领涨股-涨跌幅": "leader_change",
        "当前价": "price",
    })
    for col in ["inflow", "outflow", "net_inflow", "today_change", "stock_count"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def _fetch_concept_names_sync() -> pd.DataFrame:
    """同花顺概念板块名称+代码列表"""
    import akshare as ak
    df = ak.stock_board_concept_name_ths()
    return df  # columns: name, code


def _fetch_concept_history_sync(name: str, window_days: int) -> Optional[pd.DataFrame]:
    """
    同花顺概念指数历史行情（稳定可用）
    返回列：date, open, high, low, close, volume, amount, change_pct
    """
    import akshare as ak
    start = _date_n_days_ago(window_days)
    end = _today()
    df = ak.stock_board_concept_index_ths(
        symbol=name,
        start_date=start,
        end_date=end,
    )
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "日期": "date", "开盘价": "open", "最高价": "high",
        "最低价": "low", "收盘价": "close", "成交量": "volume", "成交额": "amount",
    })
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").tail(window_days)
    # 计算涨跌幅
    df["change_pct"] = df["close"].pct_change() * 100
    for col in ["close", "change_pct", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _fetch_concept_stocks_sync(name: str) -> Optional[pd.DataFrame]:
    """
    东财概念板块成分股（偶发超时，调用方需处理 None）
    返回列：ts_code, name, today_change, turnover_rate, [main_net_inflow]
    """
    import akshare as ak
    df = ak.stock_board_concept_cons_em(symbol=name)
    if df is None or df.empty:
        return None
    col_map = {
        "代码": "ts_code", "名称": "name",
        "涨跌幅": "today_change", "换手率": "turnover_rate",
        "最新价": "price", "成交额": "amount",
        "主力净流入": "main_net_inflow",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    for col in ["today_change", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "main_net_inflow" in df.columns:
        df["main_net_inflow"] = pd.to_numeric(df["main_net_inflow"], errors="coerce")

    # 格式化 ts_code
    if "ts_code" in df.columns:
        def _fmt(code):
            code = str(code).zfill(6)
            if code.startswith("6"):
                return f"{code}.SH"
            elif code.startswith(("4", "8")):
                return f"{code}.BJ"
            return f"{code}.SZ"
        df["ts_code"] = df["ts_code"].apply(_fmt)
    return df


# ---------- 重试包装 ----------

async def _with_retry(fn, *args, retries: int = 3, delay: float = 1.5, **kwargs):
    last_err = None
    for attempt in range(retries):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                wait = delay * (2 ** attempt)
                logger.warning(
                    f"{fn.__name__} attempt {attempt+1} failed: {type(e).__name__}. retry in {wait:.1f}s"
                )
                await asyncio.sleep(wait)
    logger.error(f"{fn.__name__} failed after {retries} retries: {last_err}")
    return None


# ---------- 公开异步接口 ----------

async def fetch_concept_fund_flow() -> Optional[pd.DataFrame]:
    """今日概念资金流主数据（同花顺，稳定）"""
    key = f"fund_flow:{_today()}"
    cached = _get_cache(key)
    if cached is not None:
        return cached
    df = await _with_retry(_fetch_concept_fund_flow_sync)
    if df is not None:
        _set_cache(key, df)
    return df


async def fetch_concept_names() -> Optional[pd.DataFrame]:
    """概念板块名称+代码映射（同花顺，稳定）"""
    key = f"names:{_today()}"
    cached = _get_cache(key)
    if cached is not None:
        return cached
    df = await _with_retry(_fetch_concept_names_sync)
    if df is not None:
        _set_cache(key, df)
    return df


async def fetch_concept_history(name: str, window_days: int) -> Optional[pd.DataFrame]:
    """概念指数历史行情（同花顺，稳定）"""
    key = f"hist:{name}:{window_days}:{_today()}"
    cached = _get_cache(key)
    if cached is not None:
        return cached
    df = await _with_retry(_fetch_concept_history_sync, name, window_days, retries=2, delay=1.0)
    if df is not None:
        _set_cache(key, df)
    return df


async def fetch_concept_stocks(name: str) -> Optional[pd.DataFrame]:
    """概念板块成分股（东财，偶发超时返回 None）"""
    key = f"stocks:{name}:{_today()}"
    cached = _get_cache(key)
    if cached is not None:
        return cached
    df = await _with_retry(_fetch_concept_stocks_sync, name, retries=2, delay=1.0)
    if df is not None:
        _set_cache(key, df)
    return df
