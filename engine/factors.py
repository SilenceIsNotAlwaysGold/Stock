"""
研报实证因子库（提升选股准确率）

均可从日线 OHLCV 计算，接入风格选股做重排：

  1. 隔夜跳空惩罚 (overnight gap)
     A 股存在结构性"隔夜负收益之谜"：近期大幅高开/跳空冲高的个股，
     次日隔夜期望收益为负（研报隔夜跳空因子 IC≈-4.34%, rankIC≈-7%）。
     → 偏好近期低/平开，惩罚连续大幅跳空。

  2. TOI 隔夜-日内拉锯因子
     隔夜收益率与日内收益率的负相关度（"拉锯"）。负相关越强=均值回复健康，
     次日期望更优（研报月度 IC≈0.035, ICIR≈2.75, 胜率 83%）。

  3. RPS 相对强度（O'Neil）
     个股 N 日涨幅在全市场的分位（0-100）。高 RPS = 强相对动量，
     A 股散户/研报最常用的动量选股因子。

参考：BigQuant 昼夜分离 / 中信建投 隔夜-日内异象 / qstock·Sequoia RPS
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd


def overnight_gap_penalty(df: pd.DataFrame, window: int = 5) -> float:
    """
    近 window 日平均隔夜跳空幅度 → 惩罚系数 ∈ [0.85, 1.05]。
    大幅高开越多 → 系数越低（隔夜期望差）；低/平开 → 略加成。
    """
    if df is None or len(df) < window + 1:
        return 1.0
    closes = df["close"].astype(float).values
    opens = df["open"].astype(float).values
    gaps = []
    for i in range(len(df) - window, len(df)):
        pc = closes[i - 1]
        if pc > 0:
            gaps.append((opens[i] - pc) / pc)
    if not gaps:
        return 1.0
    avg_gap = float(np.mean(gaps))
    # avg_gap: <= -1% → 1.05(优), 0% → 1.0, >= +3% → 0.85(差)
    if avg_gap <= -0.01:
        return 1.05
    if avg_gap >= 0.03:
        return 0.85
    # 线性插值 [-0.01, 0.03] → [1.05, 0.85]
    return round(1.05 - (avg_gap + 0.01) / 0.04 * 0.20, 4)


def toi_factor(df: pd.DataFrame, window: int = 20) -> float:
    """
    隔夜收益率 vs 日内收益率 的相关系数取负 → 健康度 ∈ [0.95, 1.08]。
    负相关越强（拉锯越健康）系数越高。
    """
    if df is None or len(df) < window + 1:
        return 1.0
    o = df["open"].astype(float).values
    c = df["close"].astype(float).values
    overnight, intraday = [], []
    for i in range(len(df) - window, len(df)):
        pc = c[i - 1]
        if pc > 0 and o[i] > 0:
            overnight.append((o[i] - pc) / pc)
            intraday.append((c[i] - o[i]) / o[i])
    if len(overnight) < 5:
        return 1.0
    s1, s2 = pd.Series(overnight), pd.Series(intraday)
    if s1.std() == 0 or s2.std() == 0:
        return 1.0
    corr = s1.corr(s2)
    if corr != corr:
        return 1.0
    toi = -corr  # 负相关→正向
    # toi: <=-0.2 → 0.95, 0 → 1.0, >=0.5 → 1.08
    return round(float(np.clip(1.0 + toi * 0.16, 0.95, 1.08)), 4)


def rps_map(slices: Dict[str, pd.DataFrame], n: int = 20) -> Dict[str, float]:
    """
    全市场 n 日涨幅 → RPS 分位(0-100)。返回 ts_code -> rps。
    """
    rets: List[tuple] = []
    for code, df in slices.items():
        if df is None or len(df) < n + 1:
            continue
        c = df["close"].astype(float).values
        base = c[-n - 1]
        if base > 0:
            rets.append((code, (c[-1] - base) / base))
    if len(rets) < 10:
        return {}
    codes = [r[0] for r in rets]
    vals = pd.Series([r[1] for r in rets])
    ranks = vals.rank(pct=True) * 100.0
    return {codes[i]: round(float(ranks.iloc[i]), 1) for i in range(len(codes))}


def rps_multiplier(rps: float) -> float:
    """RPS 分位 → 评分乘子 ∈ [0.90, 1.10]。"""
    if rps is None or rps != rps:
        return 1.0
    # rps 0→0.90, 50→1.0, 100→1.10
    return round(0.90 + rps / 100.0 * 0.20, 4)


def factor_adjust(base_score: float, df: pd.DataFrame, rps: float = None,
                   gap_window: int = 5, toi_window: int = 20) -> tuple:
    """
    对基础评分施加三因子重排乘子。
    返回 (调整后分, 明细 dict)。
    """
    g = overnight_gap_penalty(df, gap_window)
    t = toi_factor(df, toi_window)
    r = rps_multiplier(rps)
    adjusted = base_score * g * t * r
    return round(adjusted, 2), {
        "gap_penalty": g, "toi": t, "rps": rps, "rps_mult": r,
        "factor_mult": round(g * t * r, 4),
    }
