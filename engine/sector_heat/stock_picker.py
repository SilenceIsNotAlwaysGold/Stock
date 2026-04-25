"""
板块内选股

评分维度（满分100）：
  今日表现   30分：涨幅适中得高分（1-5%最优），过高/过低扣分
  换手活跃   25分：3-8% 区间最优
  资金流入   25分：主力净流入（有数据时）
  龙头加分   20分：领涨股 +20，贡献涨幅前3 +10

当成分股 API 不可用时，降级为仅返回领涨股作为唯一推荐。
"""

import logging
from typing import List

import pandas as pd

from engine.sector_heat.data_fetcher import fetch_concept_stocks
from engine.sector_heat.models import SectorScore, StockPick

logger = logging.getLogger(__name__)

# 过滤：这些前缀不在主板，一般不推荐（可按需放开）
_EXCLUDED_PREFIXES = ("688", "4", "8")


def _is_excluded(ts_code: str) -> bool:
    code = ts_code.split(".")[0]
    return code.startswith(_EXCLUDED_PREFIXES)


def _score_today_change(chg: float) -> float:
    """涨幅质量得分 0-30"""
    if chg < -2:
        return 0.0
    if chg < 0:
        return chg / (-2) * 5 + 5       # -2%~0 → 0~5
    if chg <= 1:
        return 5 + chg * 10              # 0~1% → 5~15
    if chg <= 3:
        return 15 + (chg - 1) * 7.5     # 1~3% → 15~30
    if chg <= 5:
        return 30 - (chg - 3) * 5       # 3~5% → 30~20
    if chg <= 9:
        return 20 - (chg - 5) * 4       # 5~9% → 20~4
    return 0.0                           # 涨停附近，无法追


def _score_turnover(rate: float) -> float:
    """换手率得分 0-25"""
    if rate <= 0:
        return 0.0
    if rate <= 1:
        return rate * 5
    if rate <= 3:
        return 5 + (rate - 1) * 10
    if rate <= 8:
        return 25.0
    if rate <= 15:
        return 25 - (rate - 8) * 2
    return max(0.0, 11 - (rate - 15) * 1)


def _score_net_inflow(net: float) -> float:
    """主力净流入得分 0-25（单位：亿元，无数据时返回 12.5 中性值）"""
    if pd.isna(net):
        return 12.5
    if net <= -1:
        return 0.0
    if net <= 0:
        return 8.0 + net * 8            # -1~0 → 0~8
    if net <= 3:
        return 8 + net * 5.67           # 0~3 → 8~25
    return 25.0


def _build_fallback(sector: SectorScore, top_n: int) -> List[StockPick]:
    """成分股 API 不可用时，用领涨股兜底"""
    if not sector.leader_stock:
        return []
    return [StockPick(
        ts_code="",
        name=sector.leader_stock,
        sector=sector.name,
        role="龙头",
        score=80.0,
        today_change=sector.leader_change,
        turnover_rate=sector.turnover_rate,
        reason=f"板块领涨股，今日涨幅 {sector.leader_change:.2f}%",
    )]


async def pick_stocks(sector: SectorScore, top_n: int = 3) -> List[StockPick]:
    """
    从板块成分股中选出 top_n 只推荐股。
    若成分股 API 失败，降级为领涨股兜底。
    """
    df = await fetch_concept_stocks(sector.name)
    if df is None or df.empty:
        logger.warning(f"[{sector.name}] 成分股获取失败，降级为领涨股兜底")
        return _build_fallback(sector, top_n)

    # 过滤科创/北交
    if "ts_code" in df.columns:
        df = df[~df["ts_code"].apply(_is_excluded)]

    # 过滤当日涨停（今日 ≥9.8% 无法买入）
    if "today_change" in df.columns:
        df = df[df["today_change"] < 9.8]

    if df.empty:
        return _build_fallback(sector, top_n)

    # 龙头身份判断：今日涨幅最大的前3名
    if "today_change" in df.columns:
        df = df.sort_values("today_change", ascending=False).reset_index(drop=True)
        leader_idx = set(df.index[:3])
    else:
        leader_idx = set()

    picks: List[StockPick] = []
    for idx, row in df.iterrows():
        chg = float(row.get("today_change", 0))
        turn = float(row.get("turnover_rate", 0))
        net = float(row.get("main_net_inflow", float("nan")))

        s_chg = _score_today_change(chg)
        s_turn = _score_turnover(turn)
        s_flow = _score_net_inflow(net)

        # 龙头加分
        if idx == 0:
            leader_bonus = 20.0
            role = "龙头"
        elif idx in leader_idx:
            leader_bonus = 10.0
            role = "次龙头"
        else:
            leader_bonus = 0.0
            role = "潜力股"

        score = round(s_chg + s_turn + s_flow + leader_bonus, 2)

        # 生成推荐理由
        reasons = []
        if role in ("龙头", "次龙头"):
            reasons.append(f"板块{role}")
        if not pd.isna(net) and net > 0:
            reasons.append(f"主力净流入 {net:.1f}亿")
        if 3 <= turn <= 8:
            reasons.append(f"换手率适中({turn:.1f}%)")
        if 1 <= chg <= 5:
            reasons.append(f"涨幅健康({chg:.1f}%)")
        reason = "，".join(reasons) if reasons else f"今日涨幅 {chg:.1f}%"

        picks.append(StockPick(
            ts_code=str(row.get("ts_code", "")),
            name=str(row.get("name", "")),
            sector=sector.name,
            role=role,
            score=score,
            today_change=chg,
            turnover_rate=turn,
            reason=reason,
        ))

    picks.sort(key=lambda x: x.score, reverse=True)
    return picks[:top_n]
