"""
长线风格

多头排列趋势跟随：close>MA20>MA60 且 MA60 向上，半年涨幅为正但未过热。
持仓约 40 个交易日，跌破 MA60 趋势走坏止损 / -15% 硬止损 / +40% 止盈 / 到期出。
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
from engine.styles.indicators import ma_np, ret_np

_EXCLUDE_PREFIX = ("8", "4", "920")


@register_style
class LongTermStyle(TradingStyle):
    key = "long"
    name = "长线·趋势跟随"
    desc = "多头排列(MA20>MA60↑)+半年正收益未过热，持仓约40日，破MA60/-15%止损，+40%止盈。"
    verdict = "样本外证伪"
    verdict_note = "8年 −45%；追多头排列=动量负边际，长持仍负。"
    target_hold_days = 40
    top_n = 3
    position_pct = 0.8
    max_hold_days = 60
    min_lookback = 130   # 需半年(120日)收益 + MA60
    needs_slices = False  # 改用 fast 索引（numpy O(1)）

    def select(self, day: DayContext) -> List[StylePick]:
        picks: List[StylePick] = []
        fast = day.fast or {}
        for ts_code, e in fast.items():
            if ts_code.split(".")[0].startswith(_EXCLUDE_PREFIX):
                continue
            info = day.stock_info.get(ts_code) or {}
            name = info.get("name", "") or ""
            if "ST" in name.upper():
                continue
            p = e["pos"].get(day.date)
            if p is None or p < 130:
                continue
            cl = e["c"]
            c = float(cl[p])
            ma20, ma60 = ma_np(cl, p, 20), ma_np(cl, p, 60)
            ma60_prev = ma_np(cl, p - 10, 60)
            if any(x != x for x in (ma20, ma60, ma60_prev)) or ma60 <= 0:
                continue
            if e["lu"][p]:
                continue
            # 多头排列 + MA60 向上
            if not (c > ma20 > ma60 and ma60 > ma60_prev):
                continue
            r120 = ret_np(cl, p, 120)          # 半年涨幅
            if r120 != r120 or not (0 < r120 < 0.8):   # 正收益但未翻倍式过热
                continue

            score = 60 + (ma60 - ma60_prev) / ma60_prev * 150
            score += min(r120, 0.5) * 40
            score += (c - ma60) / ma60 * 30
            picks.append(StylePick(
                ts_code=ts_code, name=name, score=round(score, 1),
                reason=f"多头排列半年+{r120*100:.0f}%",
                meta={"ma60": round(ma60, 2)},
            ))
        picks.sort(key=lambda x: -x.score)
        return picks

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        c = bar["close"]
        arr = np.asarray(holding.get("recent_closes", []) + [c], dtype=float)
        ma60 = ma_np(arr, len(arr) - 1, 60)
        gain = (c - holding["buy_px"]) / holding["buy_px"]
        if gain >= 0.40:
            return StyleExit(sell=True, price=round(c, 2), reason="long_take_profit")
        if gain <= -0.15:
            return StyleExit(sell=True, price=round(c, 2), reason="long_stop_loss")
        if ma60 == ma60 and c < ma60:
            return StyleExit(sell=True, price=round(c, 2), reason="long_break_ma60")
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(c, 2), reason="long_time_exit")
        return StyleExit(sell=False, reason="long_hold")
