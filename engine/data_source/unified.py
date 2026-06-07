"""
统一数据源适配 — 多源容灾

策略：
  实时报价  → AKShare(东财) → Sina  → Tushare
  日线历史  → Tushare → AKShare(stock_zh_a_hist)
  全市场快照 → AKShare(stock_zh_a_spot_em) → Tushare(daily)

每个数据源只在前一个失败/限流时启用。
"""

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

_CACHE: Dict[str, Tuple[float, object]] = {}
_RT_TTL = 30      # 实时 30s
_DAILY_TTL = 600  # 日线 10min
_MARKET_TTL = 60  # 市场快照 60s


def _cget(k, ttl):
    e = _CACHE.get(k)
    if e and time.time() - e[0] < ttl:
        return e[1]
    return None


def _cset(k, v):
    _CACHE[k] = (time.time(), v)


class DataSourceError(Exception):
    pass


# ───────── 同步采集函数（每个源一个）─────────

def _norm_code(ts_code: str) -> Tuple[str, str]:
    """000001.SZ → (000001, SZ)，6 位代码 + 市场后缀"""
    if "." in ts_code:
        code, mkt = ts_code.split(".", 1)
        return code.zfill(6), mkt.upper()
    code = ts_code.zfill(6)
    if code.startswith("6"):
        return code, "SH"
    if code.startswith(("4", "8")):
        return code, "BJ"
    return code, "SZ"


# 1. 实时报价 — AKShare 东财
def _rt_akshare_em(ts_code: str) -> Optional[dict]:
    import akshare as ak
    code, _ = _norm_code(ts_code)
    df = ak.stock_zh_a_spot_em()  # 全市场快照
    row = df[df["代码"] == code]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "ts_code": ts_code,
        "name": str(r.get("名称", "")),
        "price": float(r.get("最新价", 0) or 0),
        "open": float(r.get("今开", 0) or 0),
        "high": float(r.get("最高", 0) or 0),
        "low": float(r.get("最低", 0) or 0),
        "pre_close": float(r.get("昨收", 0) or 0),
        "change_pct": float(r.get("涨跌幅", 0) or 0),
        "volume": int(r.get("成交量", 0) or 0),
        "amount": float(r.get("成交额", 0) or 0),
        "turnover_rate": float(r.get("换手率", 0) or 0),
        "source": "akshare_em",
    }


# 2. 实时报价 — Sina
def _rt_sina(ts_code: str) -> Optional[dict]:
    import urllib.request
    code, mkt = _norm_code(ts_code)
    sym = f"sh{code}" if mkt == "SH" else (f"sz{code}" if mkt == "SZ" else f"bj{code}")
    url = f"http://hq.sinajs.cn/list={sym}"
    req = urllib.request.Request(url, headers={"Referer": "http://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, timeout=5).read().decode("gbk")
    # var hq_str_sh000001="名称,今开,昨收,最新,最高,最低,...";
    m = raw.split('="', 1)
    if len(m) < 2:
        return None
    fields = m[1].rstrip('";\n').split(",")
    if len(fields) < 6:
        return None
    return {
        "ts_code": ts_code,
        "name": fields[0],
        "open": float(fields[1] or 0),
        "pre_close": float(fields[2] or 0),
        "price": float(fields[3] or 0),
        "high": float(fields[4] or 0),
        "low": float(fields[5] or 0),
        "volume": int(float(fields[8] or 0)) if len(fields) > 8 else 0,
        "amount": float(fields[9] or 0) if len(fields) > 9 else 0,
        "change_pct": (
            (float(fields[3] or 0) - float(fields[2] or 0))
            / max(float(fields[2] or 1), 0.01) * 100
        ),
        "source": "sina",
    }


# 3. 日线 — Tushare
def _daily_tushare(ts_code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    import tushare as ts
    from app.config import settings
    if not settings.TUSHARE_TOKEN:
        return None
    ts.set_token(settings.TUSHARE_TOKEN)
    api = ts.pro_api()
    df = api.daily(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return None
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["source"] = "tushare"
    return df


# 4. 日线 — AKShare
def _daily_akshare(ts_code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    import akshare as ak
    code, _ = _norm_code(ts_code)
    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
        "涨跌幅": "pct_chg",
    })
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["source"] = "akshare"
    return df


# ───────── 异步包装 + 容灾链 ─────────

async def _try_chain(*fns_with_args) -> Optional[object]:
    """依次调用，第一个返回非 None 的结果即返回。"""
    for label, fn, args in fns_with_args:
        try:
            r = await asyncio.to_thread(fn, *args)
            if r is not None and (not hasattr(r, "empty") or not r.empty):
                logger.debug(f"data_source: 命中 {label}")
                return r
        except Exception as e:
            logger.warning(f"data_source: {label} 失败 {type(e).__name__}: {e}")
    return None


async def fetch_realtime_quote(ts_code: str) -> Optional[dict]:
    """
    单股实时报价。多源容灾：AKShare → Sina
    """
    key = f"rt:{ts_code}"
    cached = _cget(key, _RT_TTL)
    if cached is not None:
        return cached

    result = await _try_chain(
        ("akshare_em", _rt_akshare_em, (ts_code,)),
        ("sina", _rt_sina, (ts_code,)),
    )
    if result is not None:
        _cset(key, result)
    return result


async def fetch_daily_bars(
    ts_code: str, start: date, end: date
) -> Optional[pd.DataFrame]:
    """
    单股日线历史。Tushare → AKShare
    """
    s = start.strftime("%Y%m%d")
    e = end.strftime("%Y%m%d")
    key = f"daily:{ts_code}:{s}:{e}"
    cached = _cget(key, _DAILY_TTL)
    if cached is not None:
        return cached

    result = await _try_chain(
        ("tushare", _daily_tushare, (ts_code, s, e)),
        ("akshare", _daily_akshare, (ts_code, s, e)),
    )
    if result is not None:
        _cset(key, result)
    return result


# ───────── 全市场快照 ─────────

def _market_overview_em() -> Optional[dict]:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        return None
    chg = pd.to_numeric(df.get("涨跌幅", 0), errors="coerce").fillna(0)
    amt = pd.to_numeric(df.get("成交额", 0), errors="coerce").fillna(0)
    return {
        "total": len(df),
        "up_count": int((chg > 0.5).sum()),
        "down_count": int((chg < -0.5).sum()),
        "limit_up": int((chg >= 9.8).sum()),
        "limit_down": int((chg <= -9.8).sum()),
        "total_amount_yi": round(amt.sum() / 1e8, 1),  # 亿元
        "source": "akshare_em",
    }


async def fetch_market_overview() -> Optional[dict]:
    """全市场快照 — 涨跌家数/成交额/涨停跌停"""
    key = "market_overview"
    cached = _cget(key, _MARKET_TTL)
    if cached is not None:
        return cached

    try:
        result = await asyncio.to_thread(_market_overview_em)
        if result is not None:
            _cset(key, result)
        return result
    except Exception as e:
        logger.warning(f"market_overview 失败: {e}")
        return None
