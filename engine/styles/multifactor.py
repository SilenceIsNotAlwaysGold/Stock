"""
多因子合成 · 宽分散 · 月度低换手（证据驱动的"真正赚钱"尝试）

研究结论汇总（全部经诚实回测/样本外）：
  - 动量/追涨/追板 = 负边际（RPS20 ICIR−0.32、连板−0.47）→ 反向用
  - 5日反转 = 唯一正边际，但单因子薄且 regime 依赖
  - 高换手必死（daban/swing 成本拖累 23~34%）；反转降换手 −28%→+11% 已证控成本有效

故采用机构标准做法把薄而真的边际转成净正：
  1. 合成同向的多个弱因子（横截面 z-score 等权）：
       反转5(-5日涨幅) + 反动量20(-20日涨幅) + 低波20(-振幅) + 高流动性
  2. 宽分散：买 top 25（非 top 3~8）→ 摊薄个股/regime 方差
  3. 月度再平衡：持有 ~20 交易日 → 年换手 ~12 次（非 ~50）→ 成本拖累 ~3-5%
  4. 真实 T+1 开盘进场 + 全套成交现实化
不保证高夏普；这是证据指向的最高概率路径，由样本外验证定真伪。
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
class MultiFactorStyle(TradingStyle):
    key = "multifactor"
    name = "多因子·宽分散·月度"
    desc = "反转+反动量+低波 横截面z合成，主板非ST取top25，月度再平衡低换手，T+1开盘进场。"
    verdict = "样本外证伪"
    verdict_note = "2年 −19%；等权合成混入falling-knife因子稀释真信号，无边际。"
    target_hold_days = 20       # 月度再平衡 → 低换手控成本
    top_n = 25                  # 宽分散降方差
    position_pct = 0.9
    max_hold_days = 28
    min_lookback = 30
    emotion_gated = False
    needs_slices = False
    entry_at = "next_open"

    def select(self, day: DayContext) -> List[StylePick]:
        fast = day.fast or {}
        rows = []   # (ts_code, name, rev5, antimom20, lowvol20)
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
            if c[p] <= 0 or c[p - 5] <= 0 or c[p - 20] <= 0:
                continue
            if e["ld"][p]:                       # 今日跌停剔除（无量续跌）
                continue
            # 流动性：近5日有成交（amount 单位随源不同，仅排除停牌/零量）
            if float(np.mean(e["amt"][p - 4:p + 1])) <= 0 or e["vol"][p] <= 0:
                continue
            rev5 = -((c[p] - c[p - 5]) / c[p - 5])           # 反转：5日跌得多→大
            antimom = -((c[p] - c[p - 20]) / c[p - 20])      # 反动量：20日弱→大
            h, l = e["h"], e["l"]
            amp = np.mean([(h[i] - l[i]) / c[i - 1]
                           for i in range(p - 19, p + 1) if c[i - 1] > 0])
            lowvol = -float(amp)                              # 低波动→大
            rows.append([ts_code, name, rev5, antimom, lowvol])

        if len(rows) < 50:
            return []

        arr = np.array([[r[2], r[3], r[4]] for r in rows], dtype=float)
        # 横截面 z-score（每个因子当日标准化），等权合成
        mu = arr.mean(axis=0)
        sd = arr.std(axis=0)
        sd[sd == 0] = 1.0
        z = (arr - mu) / sd
        comp = z.mean(axis=1)

        order = np.argsort(-comp)               # 合成分降序
        picks: List[StylePick] = []
        for i in order[: self.top_n]:
            ts_code, name = rows[i][0], rows[i][1]
            picks.append(StylePick(
                ts_code=ts_code, name=name,
                score=round(float(comp[i]) * 10 + 50, 2),
                reason=(f"合成{comp[i]:+.2f}(反转{z[i,0]:+.1f}"
                        f"反动量{z[i,1]:+.1f}低波{z[i,2]:+.1f})"),
                meta={"comp": float(comp[i])},
            ))
        return picks

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        c = bar["close"]
        gain = (c - holding["buy_px"]) / holding["buy_px"]
        # 单票硬止损护底；其余持有到月度再平衡（target_hold_days）
        if gain <= -0.12:
            return StyleExit(sell=True, price=round(c, 2), reason="mf_stop_loss")
        if gain >= 0.25:
            return StyleExit(sell=True, price=round(c, 2), reason="mf_take_profit")
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(c, 2), reason="mf_rebalance")
        return StyleExit(sell=False, reason="mf_hold")
