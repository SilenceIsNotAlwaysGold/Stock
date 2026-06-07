"""
低换手宽基组合（唯一被 8 年验证为正的方向：低换手宽分散持有）

8 年硬事实：等权宽基买入持有 +31.2%，打败我们所有主动策略；主动选股/择时
alpha 一致为负，摩擦成本下毁灭价值。故采用唯一有正期望的结构：

  - 宽分散：主板非ST 流动性达标，取 top 100（极宽，近指数化）
  - 低波动倾斜：按 60 日已实现波动率升序选（低波异象=8年筛查唯一弱正且全球最稳健）
  - 年度再平衡：持有 ~240 交易日 → 年换手 ~1 次 → 成本拖累 ~0.3%/年（之前主动策略死于 20~49%）
  - 无止损：止损=增换手=已证毁灭价值；纯持有
  - 真实 T+1 开盘进场 + 全套成交现实化

目标：净跑赢「等权买入持有 +31.2%/8年」基准才算数。跑不赢→纯被动本身即答案。
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
class BroadBasketStyle(TradingStyle):
    key = "broad"
    name = "低换手宽基·低波倾斜·年度"
    desc = "主板非ST流动性达标取top100按低波倾斜，年度再平衡极低换手纯持有，T+1开盘进场。对标等权买入持有。"
    verdict = "打平被动"
    verdict_note = "8年同口径≈+33%，约等于等权买入持有+31%；参数敏感未实质跑赢，年化~3%。是唯一未亏的方向，作近被动配置参考。"
    target_hold_days = 240      # 年度再平衡 → 换手压到极致
    top_n = 100                 # 极宽分散，近指数化
    position_pct = 0.97
    max_hold_days = 252
    min_lookback = 65           # 需 60 日波动率
    emotion_gated = False
    needs_slices = False
    entry_at = "next_open"

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
            if p is None or p < 60:
                continue
            c = e["c"]
            if c[p] <= 0:
                continue
            if e["ld"][p] or e["lu"][p]:               # 涨跌停当日不进
                continue
            if float(np.mean(e["amt"][p - 4:p + 1])) <= 0 or e["vol"][p] <= 0:
                continue
            seg = c[p - 60:p + 1].astype(float)
            rets = np.diff(seg) / seg[:-1]
            vol = float(np.std(rets))                   # 60日已实现波动
            if vol <= 0 or vol != vol:
                continue
            cand.append((vol, ts_code, name))
        if len(cand) < 60:
            return []
        cand.sort(key=lambda x: x[0])                  # 低波动优先
        return [StylePick(ts_code=t, name=n,
                          score=round(100 - v * 1000, 2),
                          reason=f"低波倾斜(60日σ{v*100:.2f}%)")
                for v, t, n in cand[: self.top_n]]

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        # 纯持有：仅年度再平衡时换仓（无止损/止盈，最小化换手）
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(bar["close"], 2),
                             reason="bb_annual_rebal")
        return StyleExit(sell=False, reason="bb_hold")
