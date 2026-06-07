"""
华安"首板换手板回调"复现（规则券商研报，宣称样本外年化20%+、与沪深300相关0.14）

目的：用我方真实成本/涨停买不进/逐年样本外引擎【独立证伪】其卖方数字，
看扣真实摩擦后是否仍剩"可执行残值"+ 低相关分散价值（不接受其 20% 口径）。

规则（尽量忠实，偏离已标注）：
  - 信号池：当日首板换手板 = 今日涨停 且 非一字(盘中有波动 low!=close)
            且 T-1 非涨停（=首板，不是连板）
  - 过滤：T-1 日涨幅 ≤ +3%（排除已启动）；剔除 ST / 688/300/8/4 / 上市<60日
  - 规模过滤：用近5日均成交额代理（**无真实流通市值，已标注局限**），
            取 1.5亿~25亿 区间（对应研报 15亿~100亿 流通市值的粗代理）
  - 入场：T+1 开盘（真实，含滑点；一字涨停买不进由框架过滤）
  - 持有：默认1日；T+1 仍涨停则续持（框架 stuck），最长 max_hold_days 强平
  - 退出：T+1 未涨停 → 次日开盘走；固定止损 -4%（**研报为情绪自适应，v1 简化已标注**）
  - 组合回撤熔断：**v1 未实现（框架级，已标注）**

口径忠实度：方向性可信、非逐字精确；以逐年样本外是否打不倒为唯一判准。
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
from engine.t1_v4.market_rules import is_one_word_limit_up

_EXCLUDE_PREFIX = ("300", "301", "688", "8", "4", "920")


@register_style
class FirstBoardPullbackStyle(TradingStyle):
    key = "fb_pullback"
    name = "首板换手板回调(华安复现)"
    desc = "首板换手板(T-1非涨停且涨幅≤3%)，T+1开盘进场，1日为主最长持有N日，固定止损。券商规则独立证伪。"
    verdict = "封板幻觉"
    verdict_note = "券商研报称年化20%+；我方真实成本逐年样本外 8年 −99%。卖方回测系统性虚高的铁证。"
    target_hold_days = 1
    top_n = 3
    position_pct = 0.6
    max_hold_days = 5
    min_lookback = 60
    emotion_gated = False
    needs_slices = False
    entry_at = "next_open"          # 真实次日开盘进场
    _STOP = -0.04                   # v1 固定止损（研报为情绪自适应，已标注简化）

    def select(self, day: DayContext) -> List[StylePick]:
        fast = day.fast or {}
        picks: List[StylePick] = []
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
            # 今日首板：涨停 且 T-1 非涨停
            if not e["lu"][p] or e["lu"][p - 1]:
                continue
            o, h, l, c = (float(e["o"][p]), float(e["h"][p]),
                          float(e["l"][p]), float(e["c"][p]))
            prev = float(e["c"][p - 1])
            if prev <= 0:
                continue
            # 一字板买不进
            if is_one_word_limit_up(o, h, l, c, prev, e["pct"]):
                continue
            # 换手板：盘中有波动
            if abs(l - c) <= 0.01:
                continue
            # T-1 日涨幅 ≤ +3%（排除已启动）
            pp = float(e["c"][p - 2])
            if pp <= 0 or (prev - pp) / pp > 0.03:
                continue
            # 规模代理：近5日均成交额（amount 单位随源，用相对带；标注局限）
            amt5 = float(np.mean(e["amt"][p - 4:p + 1]))
            if amt5 <= 0 or e["vol"][p] <= 0:
                continue
            amt_yi = amt5 / 1e8 if amt5 > 1e6 else amt5 / 1e4
            if not (1.5 <= amt_yi <= 25):
                continue
            # 评分：换手适中优先
            turn = float(e["tr"][p])
            score = 60.0
            if 3 <= turn <= 15:
                score += 15
            elif turn > 25:
                score -= 8
            picks.append(StylePick(
                ts_code=ts_code, name=name, score=round(score, 1),
                reason=f"首板换手板(T-1涨{(prev-pp)/pp*100:+.1f}% 换手{turn:.0f}%)",
                meta={"turn": turn},
            ))
        picks.sort(key=lambda x: -x.score)
        return picks

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        c = bar["close"]
        gain = (c - holding["buy_px"]) / holding["buy_px"]
        if gain <= self._STOP:
            return StyleExit(sell=True, price=round(c, 2), reason="fb_stop")
        # 次日仍涨停则续持（框架对一字 stuck 已处理）；否则到期开盘走
        if hold_days >= self.target_hold_days:
            return StyleExit(sell=True, price=round(bar["open"], 2),
                             reason="fb_t1_open")
        return StyleExit(sell=False, reason="fb_hold")
