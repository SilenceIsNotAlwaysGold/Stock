"""
低换手宽基 + 粗粒度趋势闸（对症拖累项的进阶版）

已验证赢家 broad（低波宽基年度）8 年 +54%，但拖累全在下跌年(2018/19/22/23)。
regime_gated 失败的根因是【每日】择时→频繁 whipsaw+高换手。
本策略只在【再平衡点(≈年度)】查一次【长周期(MA120)市场趋势】决定该期上不上：
  - 市场宽度(收盘>MA120 占比) ≥ 阈值 → 部署低波宽基篮
  - 否则该期空仓拿现金（绕开熊市年，换手仍≈年度）

与 regime_gated 的本质区别：粗粒度(MA120) + 极低频(年度查) → 无 whipsaw、无高换手。
保留 broad 不动，作为对照。
"""

from __future__ import annotations

from typing import List

import numpy as np

from engine.styles.base import (
    DayContext,
    StyleExit,
    StylePick,
    TradingStyle,
    register_style,
)

_EXCLUDE_PREFIX = ("300", "301", "688", "8", "4", "920")
_TREND = {"on": True}   # 最近一次判定的趋势态，供 should_exit 复用
_UT_CACHE: dict = {}    # dn -> 趋势占比（同一回测复用，MA120 慢不 whipsaw）


def _market_uptrend(fast: dict, dn: str) -> float:
    """主板个股 收盘 > 自身 MA120 占比（长周期、稳定，仅 ≤dn）。"""
    if dn in _UT_CACHE:
        return _UT_CACHE[dn]
    above = tot = 0
    for ts_code, e in fast.items():
        if ts_code.split(".")[0].startswith(_EXCLUDE_PREFIX):
            continue
        p = e["pos"].get(dn)
        if p is None or p < 120:
            continue
        c = e["c"]
        if c[p] <= 0:
            continue
        ma120 = c[p - 119:p + 1].mean()
        if ma120 > 0:
            tot += 1
            if c[p] > ma120:
                above += 1
    r = (above / tot) if tot > 50 else 0.0
    _UT_CACHE[dn] = r
    return r


@register_style
class BroadTrendStyle(TradingStyle):
    key = "broad_trend"
    name = "低换手宽基+粗趋势闸·年度"
    desc = "已验证低波宽基赢家 + 年度级长周期(MA120)趋势闸：熊市年空仓避开拖累，牛市年才上。"
    verdict = "样本外证伪"
    verdict_note = "8年 −49%；择时闸滞后、错杀，市场择时毁灭价值（与regime门控一致）。"
    target_hold_days = 240      # 年度再平衡（趋势闸只在此刻判，无 whipsaw）
    top_n = 100
    position_pct = 0.97
    max_hold_days = 252
    min_lookback = 125          # 需 MA120
    emotion_gated = False
    needs_slices = False
    entry_at = "next_open"
    _TREND_ON = 0.45            # 收盘>MA120 占比 ≥45% = 市场长周期向上 → 该期可上

    def select(self, day: DayContext) -> List[StylePick]:
        fast = day.fast or {}
        up = _market_uptrend(fast, day.date)
        _TREND["on"] = up >= self._TREND_ON
        if not _TREND["on"]:                 # 长周期趋势向下 → 该期空仓
            return []
        cand = []
        for ts_code, e in fast.items():
            if ts_code.split(".")[0].startswith(_EXCLUDE_PREFIX):
                continue
            info = day.stock_info.get(ts_code) or {}
            name = info.get("name", "") or ""
            if "ST" in name.upper():
                continue
            p = e["pos"].get(day.date)
            if p is None or p < 60:
                continue
            c = e["c"]
            if c[p] <= 0 or e["ld"][p] or e["lu"][p]:
                continue
            if float(np.mean(e["amt"][p - 4:p + 1])) <= 0 or e["vol"][p] <= 0:
                continue
            seg = c[p - 60:p + 1].astype(float)
            rets = np.diff(seg) / seg[:-1]
            vol = float(np.std(rets))
            if vol <= 0 or vol != vol:
                continue
            cand.append((vol, ts_code, name))
        if len(cand) < 60:
            return []
        cand.sort(key=lambda x: x[0])        # 低波优先
        return [StylePick(ts_code=t, name=n,
                          score=round(100 - v * 1000, 2),
                          reason=f"趋势ON({up:.0%}>MA120)·低波σ{v*100:.2f}%")
                for v, t, n in cand[: self.top_n]]

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        # 趋势在再平衡点转向下 → 该期清仓避熊（低频，仍≈年度换手）
        if not _TREND["on"]:
            return StyleExit(sell=True, price=round(bar["close"], 2),
                             reason="bt_trend_off")
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(bar["close"], 2),
                             reason="bt_annual_rebal")
        return StyleExit(sell=False, reason="bt_hold")
