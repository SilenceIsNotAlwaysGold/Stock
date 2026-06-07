"""轻量技术指标（波段/长线风格用）"""

from __future__ import annotations

import numpy as np
import pandas as pd

_NAN = float("nan")


def ma_np(arr, p: int, n: int) -> float:
    """arr[p-n+1 : p+1] 均值（numpy，O(n) 无 pandas）；不足返回 nan。"""
    s = p - n + 1
    if s < 0:
        return _NAN
    return float(arr[s:p + 1].mean())


def rsi_np(arr, p: int, n: int = 14) -> float:
    """截至 p 的 Wilder 简化 RSI（numpy）；不足返回 nan。"""
    if p - n < 0:
        return _NAN
    d = np.diff(arr[p - n:p + 1])      # n 个差分
    gain = d[d > 0].sum() / n
    loss = -d[d < 0].sum() / n
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - 100 / (1 + rs))


def ret_np(arr, p: int, n: int) -> float:
    """截至 p 的 n 日涨幅（numpy）；不足返回 nan。"""
    if p - n < 0:
        return _NAN
    a = float(arr[p - n])
    b = float(arr[p])
    return (b - a) / a if a > 0 else _NAN


def ma(closes: pd.Series, n: int) -> float:
    """最近 n 日均价；不足返回 nan。"""
    if len(closes) < n:
        return float("nan")
    return float(closes.tail(n).mean())


def rsi(closes: pd.Series, n: int = 14) -> float:
    """Wilder RSI；不足返回 nan。"""
    if len(closes) < n + 1:
        return float("nan")
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0).tail(n).mean()
    loss = (-delta.clip(upper=0)).tail(n).mean()
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - 100 / (1 + rs))


def ret(closes: pd.Series, n: int) -> float:
    """最近 n 日涨幅；不足返回 nan。"""
    if len(closes) < n + 1:
        return float("nan")
    a = float(closes.iloc[-n - 1])
    b = float(closes.iloc[-1])
    return (b - a) / a if a > 0 else float("nan")
