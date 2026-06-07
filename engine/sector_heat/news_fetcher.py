"""
新闻数据采集 — 财联社电报 / 东财个股新闻

财联社：每次拉 20 条最新电报，10 分钟缓存
东财：个股新闻 10 条/股，30 分钟缓存
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

_NEWS_CACHE: Dict[str, Tuple[float, object]] = {}
_TELEGRAPH_TTL = 600   # 财联社 10 分钟
_STOCK_NEWS_TTL = 1800  # 个股新闻 30 分钟


def _get(key: str, ttl: int):
    e = _NEWS_CACHE.get(key)
    if e and time.time() - e[0] < ttl:
        return e[1]
    return None


def _set(key: str, val):
    _NEWS_CACHE[key] = (time.time(), val)


def _fetch_telegraph_sync() -> Optional[pd.DataFrame]:
    """财联社全球电报 — 返回最新 20 条"""
    import akshare as ak
    df = ak.stock_info_global_cls(symbol="全部")
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "标题": "title", "内容": "content",
        "发布日期": "pub_date", "发布时间": "pub_time",
    })
    # 合成 datetime 列方便排序过滤
    df["timestamp"] = pd.to_datetime(
        df["pub_date"].astype(str) + " " + df["pub_time"].astype(str),
        errors="coerce",
    )
    return df


def _fetch_stock_news_sync(stock_code: str) -> Optional[pd.DataFrame]:
    """东财个股新闻 — 10 条最新"""
    import akshare as ak
    # stock_news_em 接受 6 位代码
    code = stock_code.split(".")[0] if "." in stock_code else stock_code
    df = ak.stock_news_em(symbol=code)
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "关键词": "keyword",
        "新闻标题": "title",
        "新闻内容": "content",
        "发布时间": "pub_time",
        "文章来源": "source",
        "新闻链接": "url",
    })
    df["timestamp"] = pd.to_datetime(df["pub_time"], errors="coerce")
    return df


async def _retry(fn, *args, retries: int = 2, delay: float = 1.0, **kw):
    last_err = None
    for i in range(retries):
        try:
            return await asyncio.to_thread(fn, *args, **kw)
        except Exception as e:
            last_err = e
            if i < retries - 1:
                await asyncio.sleep(delay * (2 ** i))
    logger.warning(f"{fn.__name__} failed: {last_err}")
    return None


# ───────── 公开接口 ─────────

async def fetch_telegraph_news(hours: int = 24) -> Optional[pd.DataFrame]:
    """
    财联社近 N 小时电报。
    Args:
        hours: 仅返回最近 N 小时内的电报（默认 24h）
    Returns:
        DataFrame: title, content, pub_date, pub_time, timestamp
    """
    key = "telegraph"
    cached = _get(key, _TELEGRAPH_TTL)
    if cached is None:
        cached = await _retry(_fetch_telegraph_sync)
        if cached is None:
            return None
        _set(key, cached)

    cutoff = datetime.now() - timedelta(hours=hours)
    df = cached[cached["timestamp"] >= cutoff].copy()
    return df


async def fetch_stock_news(stock_code: str, days: int = 7) -> Optional[pd.DataFrame]:
    """
    个股近 N 天新闻。
    Args:
        stock_code: 6 位代码或 xxx.SH/SZ 格式
        days: 仅返回最近 N 天的新闻
    """
    key = f"stock_news:{stock_code}"
    cached = _get(key, _STOCK_NEWS_TTL)
    if cached is None:
        cached = await _retry(_fetch_stock_news_sync, stock_code)
        if cached is None:
            return None
        _set(key, cached)

    cutoff = datetime.now() - timedelta(days=days)
    df = cached[cached["timestamp"] >= cutoff].copy()
    return df


def filter_news_by_keywords(
    news_df: pd.DataFrame,
    keywords: List[str],
    max_items: int = 10,
) -> List[Dict]:
    """
    按关键词过滤新闻（标题或内容包含任一关键词）。
    Returns:
        [{title, content, pub_time}]，按时间倒序
    """
    if news_df is None or news_df.empty or not keywords:
        return []
    # 用 | 分隔做正则匹配
    pattern = "|".join([k for k in keywords if k])
    if not pattern:
        return []
    mask = (
        news_df["title"].str.contains(pattern, na=False, regex=True)
        | news_df["content"].str.contains(pattern, na=False, regex=True)
    )
    matched = news_df[mask].sort_values("timestamp", ascending=False).head(max_items)
    return [
        {
            "title": str(row.get("title", "")),
            "content": str(row.get("content", ""))[:300],  # 截断长度
            "pub_time": str(row.get("timestamp", "")),
        }
        for _, row in matched.iterrows()
    ]
