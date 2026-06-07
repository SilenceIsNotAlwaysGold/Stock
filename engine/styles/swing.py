"""
波段风格

上升趋势中的回踩买点：close>MA20 且 MA20 走平向上，回踩接近 MA20，
RSI 不超买，不追涨停。持仓约 10 个交易日，止损破 MA20，止盈 +12% 或到期。
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
from engine.styles.indicators import ma_np, rsi_np

_EXCLUDE_PREFIX = ("8", "4", "920")


@register_style
class SwingStyle(TradingStyle):
    key = "swing"
    name = "波段·趋势回踩"
    desc = "上升趋势回踩MA20买入，RSI不超买，持仓约10日，破MA20止损/+12%止盈/到期出。"
    verdict = "样本外证伪"
    verdict_note = "8年 −74%；追上升趋势=动量负边际，事件研究全负。"
    target_hold_days = 10
    top_n = 3
    position_pct = 0.7
    max_hold_days = 15
    min_lookback = 30
    needs_slices = False   # 改用 fast 索引（numpy O(1)）

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
            if p is None or p < 25:
                continue
            cl = e["c"]
            c = float(cl[p])
            prev = float(cl[p - 1])
            ma20 = ma_np(cl, p, 20)
            ma20_prev = ma_np(cl, p - 5, 20)
            if ma20 != ma20 or ma20_prev != ma20_prev or ma20 <= 0:
                continue
            if e["lu"][p]:                          # 不追涨停（预计算）
                continue
            # 上升趋势
            if not (c > ma20 and ma20 > ma20_prev):
                continue
            # 回踩：收盘接近 MA20（0~6% 以内）
            gap = (c - ma20) / ma20
            if gap > 0.06:
                continue
            r = rsi_np(cl, p, 14)
            if r != r or not (40 <= r <= 65):
                continue

            score = 60 + (ma20 - ma20_prev) / ma20_prev * 200   # 趋势斜率
            score += (0.06 - gap) * 100                          # 越贴近 MA20 越好
            score += (60 - abs(r - 52)) * 0.3                    # RSI 居中加分
            picks.append(StylePick(
                ts_code=ts_code, name=name, score=round(score, 1),
                reason=f"趋势回踩MA20(距{gap*100:.1f}% RSI{r:.0f})",
                meta={"ma20": round(ma20, 2)},
            ))
        picks.sort(key=lambda x: -x.score)
        return picks

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        c = bar["close"]
        arr = np.asarray(holding.get("recent_closes", []) + [c], dtype=float)
        ma20 = ma_np(arr, len(arr) - 1, 20)
        gain = (c - holding["buy_px"]) / holding["buy_px"]
        if gain >= 0.12:
            return StyleExit(sell=True, price=round(c, 2), reason="swing_take_profit")
        if ma20 == ma20 and c < ma20 * 0.97:
            return StyleExit(sell=True, price=round(c, 2), reason="swing_break_ma20")
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(c, 2), reason="swing_time_exit")
        return StyleExit(sell=False, reason="swing_hold")
