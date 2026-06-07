"""
Regime 门控 · 宽分散 · 月度（对症根因的赚钱尝试）

8 年全验证的硬事实：所有亏损策略共因 = 长多 + 在下跌 regime 硬扛 + 高换手。
2018/2021/2022/2024 等大跌段任何长多必亏 —— 选股因子救不了，只有择时能。

机构 long-only 在 A 股活下来的核心机制 = regime 门控：
  - 风险偏好 ON（市场宽度健康）→ 持有宽分散弱反转篮子
  - 风险偏好 OFF（宽度走坏）→ 全部空仓拿现金，绕开大跌段
关键假设：主导 P&L 的是 regime 暴露而非选股；避开崩盘段即可由负转正。

宽度信号：全市场主板个股 收盘 > 各自 MA20 的占比（无未来函数，仅 ≤T）。
低换手（月度再平衡）+ 真实 T+1 开盘进场 + 全套成交现实化。
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

# 全市场宽度缓存（按交易日复用）+ 最近一次宽度（供 should_exit 1日滞后用）
_breadth_cache: dict = {}
_LAST = {"b": 1.0}


def _market_breadth(fast: dict, dn: str) -> float:
    """主板个股 收盘 > 自身 MA20 的占比（0~1）。仅用 ≤dn 数据。"""
    if dn in _breadth_cache:
        return _breadth_cache[dn]
    above = tot = 0
    for ts_code, e in fast.items():
        if ts_code.split(".")[0].startswith(_EXCLUDE_PREFIX):
            continue
        p = e["pos"].get(dn)
        if p is None or p < 20:
            continue
        c = e["c"]
        if c[p] <= 0:
            continue
        ma20 = c[p - 19:p + 1].mean()
        if ma20 > 0:
            tot += 1
            if c[p] > ma20:
                above += 1
    b = (above / tot) if tot > 50 else 0.0
    _breadth_cache[dn] = b
    return b


@register_style
class RegimeGatedStyle(TradingStyle):
    key = "regime"
    name = "Regime门控·宽分散·月度"
    desc = "市场宽度健康才持仓(宽分散弱反转篮)，走坏全空仓避开大跌段；月度低换手，T+1开盘进场。"
    verdict = "样本外证伪"
    verdict_note = "8年 −63%；每日择时whipsaw+高换手，市场择时毁灭价值。"
    target_hold_days = 20
    top_n = 30
    position_pct = 0.95
    max_hold_days = 26
    min_lookback = 30
    emotion_gated = False
    needs_slices = False
    entry_at = "next_open"
    _BREADTH_ON = 0.55       # 宽度 ≥55% = 风险偏好ON（多数股在 MA20 上方）
    _BREADTH_OFF = 0.45      # 宽度 ≤45% = 风险偏好OFF（迟滞，防频繁切换）

    def select(self, day: DayContext) -> List[StylePick]:
        fast = day.fast or {}
        b = _market_breadth(fast, day.date)
        _LAST["b"] = b                    # 供 should_exit 1日滞后读取
        if b < self._BREADTH_ON:          # 风险OFF：不开新仓 → 漂移到现金
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
            if p is None or p < 25:
                continue
            c = e["c"]
            if c[p] <= 0 or c[p - 5] <= 0:
                continue
            if e["ld"][p] or e["lu"][p]:          # 跌停/涨停当日不追
                continue
            if float(np.mean(e["amt"][p - 4:p + 1])) <= 0 or e["vol"][p] <= 0:
                continue
            rev5 = -((c[p] - c[p - 5]) / c[p - 5])  # 温和反转(唯一弱正因子)
            cand.append((rev5, ts_code, name))
        if len(cand) < 50:
            return []
        cand.sort(key=lambda x: -x[0])
        return [StylePick(ts_code=t, name=n,
                          score=round(60 + rv * 100, 1),
                          reason=f"宽度{b:.0%}ON·5日反转{rv*100:+.1f}%")
                for rv, t, n in cand[: self.top_n]]

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        c = bar["close"]
        gain = (c - holding["buy_px"]) / holding["buy_px"]
        if gain <= -0.10:
            return StyleExit(sell=True, price=round(c, 2), reason="rg_stop")
        if gain >= 0.25:
            return StyleExit(sell=True, price=round(c, 2), reason="rg_take")
        # regime 走坏 → 全部清仓避开大跌段（核心机制；用最近一次宽度，1日滞后）
        if _LAST["b"] < self._BREADTH_OFF:
            return StyleExit(sell=True, price=round(c, 2), reason="rg_risk_off")
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(c, 2), reason="rg_rebalance")
        return StyleExit(sell=False, reason="rg_hold")
