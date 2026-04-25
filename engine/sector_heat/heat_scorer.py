"""
板块热度评分引擎

总分 100：
  价格动量  35分 = 窗口涨幅(20) + 今日质量(10) + 上涨家数比(5)
  资金动向  35分 = 净流入绝对值(20) + 净流入占比(15)
  热度加速  30分 = 换手活跃(10) + 涨停含量(10) + 趋势加速(10)
"""

import asyncio
import logging
from typing import List, Optional

import pandas as pd

from engine.sector_heat.data_fetcher import (
    fetch_concept_fund_flow,
    fetch_concept_history,
)
from engine.sector_heat.models import SectorScore

logger = logging.getLogger(__name__)

# 快速初筛：从全量板块保留前 N 个候选，再拉历史做精细评分
_PREFILTER_TOP = 60
# 最终返回板块数上限
_DEFAULT_TOP_N = 5


def _linear(val: float, lo: float, hi: float, score_lo: float, score_hi: float) -> float:
    if hi == lo:
        return score_lo
    ratio = (val - lo) / (hi - lo)
    return score_lo + max(0.0, min(1.0, ratio)) * (score_hi - score_lo)


def _score_price_momentum(
    today_change: float,
    period_return: float,
    up_ratio: float,
) -> float:
    # 窗口涨幅 0-20
    period_s = _linear(period_return, 0, 15, 0, 20)
    if period_return < 0:
        period_s = _linear(period_return, -10, 0, 0, 5)

    # 今日涨幅质量 0-10（梯形：1-3% 最优，过高减分）
    tc = today_change
    if tc < -1:
        today_s = 0.0
    elif tc < 0:
        today_s = _linear(tc, -1, 0, 1, 3)
    elif tc <= 1:
        today_s = _linear(tc, 0, 1, 3, 7)
    elif tc <= 3:
        today_s = _linear(tc, 1, 3, 7, 10)
    elif tc <= 5:
        today_s = _linear(tc, 3, 5, 10, 6)   # 偏强，略减
    elif tc <= 9.5:
        today_s = _linear(tc, 5, 9.5, 6, 2)  # 过强，可能一日游
    else:
        today_s = 0.0  # 涨停，无法追

    # 上涨家数比 0-5
    ratio_s = up_ratio * 5

    return round(period_s + today_s + ratio_s, 2)


def _score_fund_flow(net_inflow: float, inflow: float) -> float:
    # 净流入绝对值 0-20（亿元）
    abs_s = _linear(net_inflow, -5, 20, 0, 20)

    # 净流入占比 0-15
    ratio = net_inflow / inflow if inflow > 0 else 0
    ratio_s = _linear(ratio, -0.3, 0.5, 0, 15)

    return round(max(0, abs_s) + max(0, ratio_s), 2)


def _score_momentum(
    turnover_rate: float,
    limit_up_in_period: int,
    stock_count: int,
    acceleration: float,
) -> float:
    # 换手活跃度 0-10（3-8% 最优，两端扣分）
    if turnover_rate <= 0:
        turn_s = 0.0
    elif turnover_rate <= 1:
        turn_s = _linear(turnover_rate, 0, 1, 0, 3)
    elif turnover_rate <= 3:
        turn_s = _linear(turnover_rate, 1, 3, 3, 8)
    elif turnover_rate <= 8:
        turn_s = 10.0
    elif turnover_rate <= 15:
        turn_s = _linear(turnover_rate, 8, 15, 10, 5)
    else:
        turn_s = 2.0

    # 涨停含量 0-10
    limit_ratio = limit_up_in_period / max(stock_count, 1)
    limit_s = _linear(limit_ratio, 0, 0.2, 0, 10)

    # 加速度 0-10（近3日/窗口占比，0.5 中性，>0.5 升温，<0.5 退烧）
    accel_s = _linear(acceleration, 0, 1, 0, 10)

    return round(turn_s + limit_s + accel_s, 2)


def _compute_history_stats(hist_df: pd.DataFrame, window_days: int):
    """从历史 DataFrame 提取期间收益、涨停次数、加速度"""
    if hist_df is None or hist_df.empty:
        return 0.0, 0, 0.5  # period_return, limit_up_count, acceleration

    close = hist_df["close"].dropna()
    if len(close) < 2:
        return 0.0, 0, 0.5

    period_return = (close.iloc[-1] / close.iloc[0] - 1) * 100

    # 涨停次数（涨幅 ≥ 9.5%）
    chg = hist_df["change_pct"].dropna()
    limit_up = int((chg >= 9.5).sum())

    # 加速度：近3日涨幅 / 全程涨幅
    if len(close) >= 4 and period_return != 0:
        recent_3 = (close.iloc[-1] / close.iloc[-4] - 1) * 100
        acceleration = recent_3 / abs(period_return) + 0.5  # 标准化到 0-1 附近
        acceleration = max(0.0, min(1.0, acceleration))
    else:
        acceleration = 0.5

    return round(period_return, 2), limit_up, round(acceleration, 3)


def _judge_trend(period_return: float, acceleration: float, today_change: float) -> str:
    if period_return < 0 and today_change < 0:
        return "低迷"
    if acceleration > 0.65 and today_change > 0:
        return "升温"
    if period_return > 10 and acceleration < 0.35:
        return "退烧"
    if period_return > 15:
        return "高位"
    return "升温" if today_change > 0 else "低迷"


async def _enrich_with_history(
    candidates: List[dict], window_days: int
) -> List[dict]:
    """并发拉取候选板块历史数据并写回 enriched 字段"""

    async def _enrich_one(item: dict):
        hist = await fetch_concept_history(item["name"], window_days)
        period_return, limit_up, accel = _compute_history_stats(hist, window_days)
        item["period_return"] = period_return
        item["limit_up_in_period"] = limit_up
        item["acceleration"] = accel

    await asyncio.gather(*[_enrich_one(c) for c in candidates])
    return candidates


async def rank_sectors(
    window_days: int = 10,
    top_n: int = _DEFAULT_TOP_N,
    min_stock_count: int = 10,
) -> List[SectorScore]:
    """
    主入口：拉取数据 → 初筛 → 历史丰富 → 打分 → 排名
    """
    fund_flow = await fetch_concept_fund_flow()

    if fund_flow is None or fund_flow.empty:
        logger.error("概念板块资金流数据获取失败")
        return []

    merged = fund_flow.copy()
    merged["net_inflow"] = pd.to_numeric(merged.get("net_inflow", 0), errors="coerce").fillna(0)
    merged["inflow"] = pd.to_numeric(merged.get("inflow", 1), errors="coerce").fillna(1).replace(0, 1)
    merged["stock_count"] = pd.to_numeric(merged.get("stock_count", 0), errors="coerce").fillna(0)
    # fund_flow 没有 up_count/down_count，用 0.5 中性比例占位
    merged["up_count"] = merged["stock_count"] * 0.5
    merged["down_count"] = merged["stock_count"] * 0.5

    # 过滤成分股太少的板块
    merged = merged[merged["stock_count"] >= min_stock_count]

    if merged.empty:
        return []

    # 初筛：按今日涨幅 + 净流入排序，取前 N 做历史分析
    merged["quick_score"] = (
        merged["today_change"].rank(pct=True) * 0.5
        + merged["net_inflow"].rank(pct=True) * 0.5
    )
    candidates = merged.nlargest(_PREFILTER_TOP, "quick_score").to_dict("records")

    # 并发拉历史（有代理问题时会降级为默认值）
    candidates = await _enrich_with_history(candidates, window_days)

    # 计算上涨家数比
    results: List[SectorScore] = []
    for c in candidates:
        up = float(c.get("up_count", 0))
        down = float(c.get("down_count", 0))
        up_ratio = up / (up + down) if (up + down) > 0 else 0.5

        period_return = c.get("period_return", c.get("today_change", 0))
        limit_up = c.get("limit_up_in_period", 0)
        accel = c.get("acceleration", 0.5)
        net_inflow = c.get("net_inflow", 0)
        inflow = c.get("inflow", 1)
        turnover = float(c.get("turnover_rate", 0))
        stock_count = int(c.get("stock_count", 0))
        today_change = float(c.get("today_change", 0))

        p_score = _score_price_momentum(today_change, period_return, up_ratio)
        f_score = _score_fund_flow(net_inflow, inflow)
        m_score = _score_momentum(turnover, limit_up, max(stock_count, 1), accel)

        heat = round(p_score + f_score + m_score, 2)
        trend = _judge_trend(period_return, accel, today_change)

        results.append(SectorScore(
            name=c.get("name", ""),
            code=c.get("code", ""),
            heat_score=heat,
            price_score=p_score,
            fund_score=f_score,
            momentum_score=m_score,
            today_change=today_change,
            period_return=period_return,
            net_inflow=net_inflow,
            inflow_ratio=net_inflow / inflow if inflow else 0,
            up_ratio=up_ratio,
            turnover_rate=turnover,
            limit_up_in_period=limit_up,
            acceleration=accel,
            trend=trend,
            leader_stock=str(c.get("leader_stock", "")),
            leader_change=float(c.get("leader_change", 0)),
            stock_count=stock_count,
        ))

    results.sort(key=lambda x: x.heat_score, reverse=True)
    return results[:top_n]
