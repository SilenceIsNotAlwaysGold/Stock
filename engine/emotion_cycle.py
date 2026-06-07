"""
情绪周期引擎（A 股短线最大 edge）

从全市场日线截面计算（仅用 ≤T 数据，无未来函数）：
  - 涨停数 / 跌停数
  - 炸板率   = 炸板 / 触及涨停总数（盘中触涨停但收盘未封）
  - 最高连板 = 全市场最大连续涨停数
  - 晋级率   = 昨涨停今继续涨停 / 昨涨停数
  - 赚钱效应 = 昨涨停股今日平均收益（打板隔夜钱效代理）

合成 0-100 情绪分 + 相位（冰点/修复/发酵/高潮/退潮）+ gate 系数。
gate 系数用于短线/打板风格的"冰点收缩、高潮放大"。

参考：A股情绪周期 / 涨停板复盘 / 炸板率≈35% 历史经验
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from engine.t1_v4.market_rules import board_limit_pct, is_limit_down, is_limit_up

# 主板以外（20cm/北交）涨跌停动力学不同，情绪统计聚焦主板
_NON_MAIN = ("300", "301", "688", "8", "4", "920")


@dataclass
class EmotionState:
    date: str
    limit_up: int = 0
    limit_down: int = 0
    touched_up: int = 0           # 盘中触及涨停的家数
    sealed: int = 0               # 收盘封住涨停
    broken_rate: float = 0.0      # 炸板率
    max_consecutive: int = 0      # 最高连板
    advance_rate: float = 0.0     # 晋级率（昨涨停今继续涨停）
    money_effect: float = 0.0     # 昨涨停股今日平均收益%
    score: float = 50.0           # 0-100 情绪分
    phase: str = "修复"           # 冰点/修复/发酵/高潮/退潮
    gate: float = 1.0             # 短线/打板评分与仓位缩放系数
    note: str = ""


def _is_main(ts_code: str) -> bool:
    return not ts_code.split(".")[0].startswith(_NON_MAIN)


def compute_emotion(idx: Dict[str, dict], dnorm: str) -> EmotionState:
    """
    idx: build_fast_index() 产物（含 numpy 列数组 + lu/ld/cons 预计算）。
    dnorm: 目标交易日 YYYYMMDD。仅使用 <= 目标日的数据。
    全程 O(股票数)、O(1)/股，无 pandas、无走板回溯。
    """
    st = EmotionState(date=dnorm)
    money_rets: List[float] = []
    prev_up_set = 0
    prev_up_still_up = 0

    for ts_code, e in idx.items():
        if not _is_main(ts_code):
            continue
        p = e["pos"].get(dnorm)
        if p is None or p < 1:
            continue
        c_arr = e["c"]
        prev_close = c_arr[p - 1]
        if prev_close <= 0:
            continue
        c = c_arr[p]
        h = e["h"][p]
        pct = e["pct"]

        up_today = bool(e["lu"][p])
        down_today = bool(e["ld"][p])
        touched = h >= prev_close * (1 + pct) - 0.005

        if up_today:
            st.limit_up += 1
            st.sealed += 1
        if down_today:
            st.limit_down += 1
        if touched:
            st.touched_up += 1

        # 昨涨停（T-1）→ 今表现 + 晋级（lu[p-1] 已预计算）
        if p >= 2 and e["lu"][p - 1]:
            prev_up_set += 1
            money_rets.append((c - prev_close) / prev_close * 100)
            if up_today:
                prev_up_still_up += 1

        # 连板高度：cons 已预计算 run-length
        if up_today:
            st.max_consecutive = max(st.max_consecutive, int(e["cons"][p]))

    # 炸板率 = 触及涨停但未封 / 触及涨停
    broken = st.touched_up - st.sealed
    st.broken_rate = round(broken / st.touched_up, 4) if st.touched_up > 0 else 0.0
    st.advance_rate = round(prev_up_still_up / prev_up_set, 4) if prev_up_set > 0 else 0.0
    st.money_effect = round(sum(money_rets) / len(money_rets), 2) if money_rets else 0.0

    # ── 合成情绪分 0-100 ──
    # 涨停数：>80 强，<30 弱（线性映射到 0-30）
    lu_s = max(0.0, min(30.0, (st.limit_up - 15) / 75 * 30))
    # 连板高度：1→0, 5+→20
    hc_s = max(0.0, min(20.0, (st.max_consecutive - 1) / 4 * 20))
    # 晋级率：0→0, 0.5+→20
    ar_s = max(0.0, min(20.0, st.advance_rate / 0.5 * 20))
    # 赚钱效应：-3%→0, +3%→20
    me_s = max(0.0, min(20.0, (st.money_effect + 3) / 6 * 20))
    # 炸板率惩罚：0%→+10, 50%+→-10
    bk_s = 10.0 - min(20.0, st.broken_rate / 0.5 * 20)
    # 跌停惩罚
    dn_pen = min(15.0, st.limit_down / 30 * 15)

    score = 20 + lu_s + hc_s + ar_s + me_s + bk_s - dn_pen
    st.score = round(max(0.0, min(100.0, score)), 1)

    # ── 相位 + gate ──
    if st.score >= 75:
        st.phase, st.gate = "高潮", 1.25
    elif st.score >= 58:
        st.phase, st.gate = "发酵", 1.05
    elif st.score >= 42:
        st.phase, st.gate = "修复", 0.85
    elif st.score >= 28:
        st.phase, st.gate = "退潮", 0.5
    else:
        st.phase, st.gate = "冰点", 0.0   # 冰点空仓

    st.note = (f"涨停{st.limit_up} 跌停{st.limit_down} 炸板率{st.broken_rate:.0%} "
               f"最高{st.max_consecutive}连板 晋级{st.advance_rate:.0%} "
               f"钱效{st.money_effect:+.1f}%")
    return st
