"""
短期超跌反转风格（建立在唯一验证出正边际的因子上）

因子筛查（2 年真实口径）结论：这段 A 股「5日反转」是唯一内部一致的正边际
（RankIC +0.042 / ICIR +0.29 / IC>0 62% / 五分位单调同号 / TopT+5 +0.80%）；
而动量/追涨/追板/追高 均为负边际 —— 故选「买超跌」而非追涨。

设计要点（边际弱，成败在控成本）：
  - 选：主板非ST，按近5日跌幅最大排序（最超跌优先）
  - 过滤：剔除今日跌停(可能继续无量跌)、一字、低流动性、次新
  - 进场：真实 T+1 开盘（防止用收盘幻觉价）
  - 持有 ~5 个交易日（吃 T+1→T+5 反弹衰减曲线），低换手压低成本
  - 止损 -8% / 止盈 +12% / 到期出
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


@register_style
class ReversalStyle(TradingStyle):
    key = "reversal"
    name = "短期超跌反转"
    desc = "买近5日跌幅≥10%最极端超跌(主板非ST)，T+1开盘进场，持有约15日低换手控成本。建于唯一验证出正边际的5日反转因子。"
    verdict = "样本外证伪"
    verdict_note = "2年全样本曾+11%(H1运气)；8年逐年9年全亏、全程−96%。典型过拟合，被分段验证当场拆穿。"
    # 温和信号(有边际) + 极限低换手：实测温和超跌横截面才有 +0.25% 毛边际，
    # 极端暴跌无边际(falling knife)。故保留温和信号、拉长持有20日+分散8只压成本。
    target_hold_days = 20       # 极限拉长 → 换手压到最低
    top_n = 8                   # 分散，降单票风险
    position_pct = 0.8
    max_hold_days = 28
    min_lookback = 30
    emotion_gated = False
    needs_slices = False        # 纯 fast 索引 numpy
    entry_at = "next_open"      # 真实次日开盘进场
    _MIN_OVERSOLD = 0.02        # 温和：近5日小幅下跌即可（保留有边际的横截面信号）

    def select(self, day: DayContext) -> List[StylePick]:
        fast = day.fast or {}
        cand = []
        for ts_code, e in fast.items():
            if ts_code.split(".")[0].startswith(_EXCLUDE_PREFIX):
                continue
            info = day.stock_info.get(ts_code) or {}
            name = info.get("name", "") or ""
            if "ST" in name.upper():
                continue
            p = e["pos"].get(day.date)
            if p is None or p < 6:
                continue
            c = e["c"]
            base = c[p - 5]
            if base <= 0 or c[p] <= 0:
                continue
            # 今日跌停：很可能无量继续跌，剔除
            if e["ld"][p]:
                continue
            # 流动性：近5日均额 > 5000万，避免买不进/冲击大
            if float(np.mean(e["amt"][p - 4:p + 1])) <= 5e7 \
               and float(np.mean(e["amt"][p - 4:p + 1])) <= 5000:
                continue
            ret5 = (c[p] - base) / base          # 近5日涨幅
            if ret5 >= -self._MIN_OVERSOLD:        # 只要足够极端的超跌
                continue
            oversold = -ret5                      # 跌得越多分越高
            cand.append((oversold, ts_code, name, ret5))

        cand.sort(key=lambda x: -x[0])
        picks: List[StylePick] = []
        for oversold, ts_code, name, ret5 in cand[: self.top_n]:
            picks.append(StylePick(
                ts_code=ts_code, name=name,
                score=round(60 + oversold * 200, 1),
                reason=f"近5日{ret5*100:.1f}%超跌反转",
                meta={"ret5": round(ret5, 4)},
            ))
        return picks

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        c = bar["close"]
        gain = (c - holding["buy_px"]) / holding["buy_px"]
        if gain >= 0.12:
            return StyleExit(sell=True, price=round(c, 2), reason="rev_take_profit")
        if gain <= -0.08:
            return StyleExit(sell=True, price=round(c, 2), reason="rev_stop_loss")
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(c, 2), reason="rev_time_exit")
        return StyleExit(sell=False, reason="rev_hold")
