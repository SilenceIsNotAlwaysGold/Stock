"""
打板风格（主板 10cm）

研报/复盘实证规则：
  - 仅主板（排除 ST / 688 / 300 / 8 / 4，涨跌停动力学不同）
  - 今日须涨停封板；排除一字涨停（买不进）
  - 换手板优先（low != close，盘中有换手 → 次日竞价溢价更稳）
  - 首板 / 低位连板优先；高度板（≥4 连）风险高、易炸 → 降分
  - 小市值更优（无流通市值时用成交额做代理，避开大象）
  - 持仓 1 日，次日集合竞价（开盘）出场；次日续一字涨停则无法卖出，顺延

参考：4年盈利5亿打板框架 / 大A打板敢死队换手板撬板 / khQuant 打板回测横评
"""

from __future__ import annotations

from typing import List

from engine.styles.base import (
    DayContext,
    StyleExit,
    StylePick,
    TradingStyle,
    register_style,
)
from engine.factors import factor_adjust, rps_map
from engine.t1_v4.market_rules import (
    board_limit_pct,
    is_limit_up,
    is_one_word_limit_up,
    limit_up_price,
)

_EXCLUDE_PREFIX = ("688", "300", "301", "8", "4", "920")


@register_style
class DabanStyle(TradingStyle):
    key = "daban"
    name = "打板·涨停接力"
    desc = "选今日封板个股(换手板优先/低位连板)，收盘打板，次日集合竞价出。持仓1日，超短线高波动。"
    verdict = "封板幻觉"
    verdict_note = "首跑+26000%是封板按收盘价买不进的幻觉；真实次日开盘进场 8年 −82%。追板=确定亏损陷阱。"
    target_hold_days = 1
    top_n = 2
    position_pct = 0.5      # 打板风险高，仓位更保守
    max_hold_days = 4       # 续板顺延上限
    min_lookback = 20       # 因子重排需 RPS(20日)/TOI(20日)
    emotion_gated = True    # 打板对情绪周期最敏感：冰点空仓、高潮放大
    needs_slices = False    # 仅用 fast 索引（numpy O(1)）→ 回测器跳过切片构建
    entry_at = "next_open"  # 封死涨停按收盘买不进 → 真实次日开盘进场（隔夜接力）

    # A/B 实测：跳空/TOI 均值回复因子与打板动量逻辑相悖 → 默认关闭
    # （RPS-only 的定向验证留待后续迭代；保留开关与测量工具）
    def __init__(self, use_factors: bool = False, **overrides):
        super().__init__(**overrides)
        self.use_factors = use_factors

    def select(self, day: DayContext) -> List[StylePick]:
        picks: List[StylePick] = []
        fast = day.fast or {}
        for ts_code, e in fast.items():
            code = ts_code.split(".")[0]
            if code.startswith(_EXCLUDE_PREFIX):
                continue
            info = day.stock_info.get(ts_code) or {}
            name = info.get("name", "") or ""
            if "ST" in name.upper():
                continue
            p = e["pos"].get(day.date)
            if p is None or p < 5:
                continue

            # 必须今日封板（预计算）
            if not e["lu"][p]:
                continue
            o, h, l, c = (float(e["o"][p]), float(e["h"][p]),
                          float(e["l"][p]), float(e["c"][p]))
            prev_close = float(e["c"][p - 1])
            if prev_close <= 0:
                continue
            pct = e["pct"]
            # 一字板买不进
            if is_one_word_limit_up(o, h, l, c, prev_close, pct):
                continue

            amount = float(e["amt"][p])
            volume = float(e["vol"][p])
            if amount <= 0 or volume <= 0:
                continue

            boards = int(e["cons"][p])                     # 预计算连板数
            is_huanshou = abs(l - c) > 0.01                # 换手板：盘中有波动
            turnover = float(e["tr"][p])

            score = 60.0
            reason = []
            if boards == 1:
                score += 12; reason.append("首板")
            elif boards == 2:
                score += 8; reason.append("2连板")
            elif boards == 3:
                score += 2; reason.append("3连板")
            else:
                score -= 8 * (boards - 3); reason.append(f"{boards}连板(高度风险)")

            if is_huanshou:
                score += 12; reason.append("换手板")
            else:
                score -= 4; reason.append("T字/准一字")

            if 3.0 <= turnover <= 15.0:
                score += 8; reason.append(f"换手{turnover:.0f}%佳")
            elif turnover > 25.0:
                score -= 6; reason.append(f"换手{turnover:.0f}%过热")

            # 成交额代理市值：偏好中小（2亿~25亿活跃但非大象）
            amt_yi = amount / 1e8 if amount > 1e6 else amount / 1e4
            if 1.5 <= amt_yi <= 25:
                score += 6
            elif amt_yi > 60:
                score -= 8; reason.append("大象盘")

            picks.append(StylePick(
                ts_code=ts_code, name=name, score=round(score, 1),
                reason="·".join(reason),
                meta={"boards": boards, "huanshou": is_huanshou},
            ))

        # 三因子重排（隔夜跳空惩罚 / TOI 拉锯 / RPS 相对强度）
        # 需 slices；needs_slices=False 时默认关闭(use_factors 默认 False)
        if self.use_factors and picks and day.slices:
            rps = rps_map(day.slices, n=20)
            for pk in picks:
                df = day.slices.get(pk.ts_code)
                adj, det = factor_adjust(pk.score, df, rps.get(pk.ts_code))
                pk.score = adj
                pk.reason += f"·因子{det['factor_mult']}(RPS{det['rps']})"
                pk.meta.update(det)

        picks.sort(key=lambda x: -x.score)
        return picks

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        pct = board_limit_pct(holding["ts_code"], is_st=False)
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        # 次日续一字涨停 → 卖不出，顺延（继续吃连板）
        if is_one_word_limit_up(o, h, l, c, prev_close, pct):
            return StyleExit(sell=False, reason="continue_board_stuck", stuck=True)
        # 打板纪律：次日集合竞价（开盘价）无条件出场，不恋战
        return StyleExit(sell=True, price=round(o, 2), reason="daban_t1_open")
