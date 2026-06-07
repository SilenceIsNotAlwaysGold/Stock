"""
T1 v4 卖出引擎 v2

4 阶段决策，用日线 OHLCV 近似模拟分时逻辑。
核心改进：给盈利交易更多发展时间，低开快速止损。
"""

from dataclasses import dataclass

from engine.t1_v4.market_rules import (
    is_one_word_limit_down,
    is_one_word_limit_up,
    limit_down_price,
    limit_up_price,
)


@dataclass
class SellDecision:
    """卖出决策结果"""
    sell_price: float          # 卖出价格（stuck 时为 0，由回测器顺延持有）
    sell_reason: str           # 决策原因标签
    pnl_pct: float            # 盈亏百分比（小数，0.03 表示 3%；未含成本）
    phase: int                 # 哪个阶段触发的 (1-4)；0 = 无法成交需顺延
    description: str           # 人类可读描述
    stuck: bool = False        # True = 一字板无法成交，回测器应继续持有到次日


class SellEngineV2:
    """
    v2 卖出引擎 - 4 阶段决策

    基于日线 OHLCV 模拟分时决策逻辑。

    关键设计原则：
    1. 大幅高开（>=5%）立即锁利 — 不贪
    2. 低开（<=-2%）立即止损 — 快跑
    3. 盘中有 3% 利润就落袋 — 有赚就跑
    4. 盘中触及 -2% 止损线 — 控制风险
    5. 涨停不卖 — 顺势持有
    6. 最终兜底 — 最迟 10:00 出场
    """

    def __init__(
        self,
        # 阶段 1 参数
        phase1_take_profit: float = 0.05,   # 高开止盈线 5%
        phase1_stop_loss: float = -0.03,    # 低开止损线 -3%（主板-2%常见，放宽以减少被震出）
        # 阶段 2 参数
        phase2_take_profit: float = 0.05,   # 盘中止盈 5%（让利润奔跑，不急于3%就走）
        phase2_stop_loss: float = -0.03,    # 盘中止损 -3%（容忍日内波动）
        # 阶段 3 参数
        phase3_stop_loss: float = -0.025,   # 观察期止损 -2.5%
        # 涨跌停幅度（板块限制，主板 0.10）
        limit_pct: float = 0.10,
        # 止盈/止损同日均可达时的路径假设：True=悲观(假设先触止损)
        # 关闭未来函数乐观偏差的关键开关
        ambiguous_pessimistic: bool = True,
    ):
        self.phase1_take_profit = phase1_take_profit
        self.phase1_stop_loss = phase1_stop_loss
        self.phase2_take_profit = phase2_take_profit
        self.phase2_stop_loss = phase2_stop_loss
        self.phase3_stop_loss = phase3_stop_loss
        self.limit_pct = limit_pct
        self.ambiguous_pessimistic = ambiguous_pessimistic

    def decide(
        self,
        buy_price: float,
        next_open: float,
        next_high: float,
        next_low: float,
        next_close: float,
        prev_close: float = None,
    ) -> SellDecision:
        """
        基于卖出日 OHLCV 做卖出决策

        用日线数据近似分时逻辑：
        - open  → 集合竞价价格
        - high  → 盘中最高（止盈检查）
        - low   → 盘中最低（止损检查）
        - close → 收盘价（兜底退出价格）

        A 股成交现实化：
        - prev_close = 卖出日的前收（计算涨跌停价用）。正常 T+1 即买入日收盘价。
        - 一字跌停 → 无法卖出，返回 stuck，回测器顺延持有到次日
        - 一字涨停 → 同样无法卖出，stuck 顺延（不提前兑现浮盈，偏保守）
        - 止盈/止损同日均触及 → ambiguous_pessimistic=True 时假设先触止损（杀乐观未来函数偏差）

        决策优先级（按时间顺序）：
        0. 一字涨/跌停 → stuck（顺延）
        1. 开盘涨>=止盈线 → 开盘价卖出（阶段1 止盈）
        2. 开盘跌<=止损线 → 开盘价卖出（阶段1 止损）
        3. high 触及涨停价 → 收盘价卖出（涨停持有到收盘）
        4. 盘中 high 触止盈 且 low 触止损 → 悲观取止损（或按 open 位置）
        5. 盘中 high 触止盈 → buy*(1+止盈) 卖出
        6. 盘中 low  触止损 → buy*(1+止损) 卖出
        7. 收盘盈利 > 0 → 收盘价卖出（锁利）
        8. 收盘亏损 <= 观察期止损 → 收盘价卖出（止损）
        9. 兜底 → 收盘价卖出
        """
        # prev_close 缺省 = 买入价（正常 T+1：买入日收盘即卖出日前收）
        if prev_close is None or prev_close <= 0:
            prev_close = buy_price

        # 阶段 0：一字板无法成交 → 顺延持有
        if is_one_word_limit_down(next_open, next_high, next_low, next_close,
                                  prev_close, self.limit_pct):
            return SellDecision(
                sell_price=0.0, sell_reason="stuck_limit_down",
                pnl_pct=(next_close - buy_price) / buy_price, phase=0,
                description="一字跌停无法卖出，顺延持有", stuck=True,
            )
        if is_one_word_limit_up(next_open, next_high, next_low, next_close,
                                prev_close, self.limit_pct):
            return SellDecision(
                sell_price=0.0, sell_reason="stuck_limit_up",
                pnl_pct=(next_close - buy_price) / buy_price, phase=0,
                description="一字涨停无法卖出，顺延持有", stuck=True,
            )

        limit_up = limit_up_price(prev_close, self.limit_pct)
        limit_down = limit_down_price(prev_close, self.limit_pct)

        open_pct = (next_open - buy_price) / buy_price
        high_pct = (next_high - buy_price) / buy_price
        low_pct = (next_low - buy_price) / buy_price
        close_pct = (next_close - buy_price) / buy_price

        # 阶段 1：集合竞价（9:25）
        # 开盘即跌停无买盘 → 不能在开盘价成交，跳过到盘中/收盘判定
        if next_open > limit_down + 0.005:
            if open_pct >= self.phase1_take_profit:
                return SellDecision(
                    sell_price=round(next_open, 2),
                    sell_reason="phase1_take_profit",
                    pnl_pct=open_pct,
                    phase=1,
                    description=f"高开{open_pct*100:.1f}%止盈",
                )
            if open_pct <= self.phase1_stop_loss:
                return SellDecision(
                    sell_price=round(next_open, 2),
                    sell_reason="phase1_stop_loss",
                    pnl_pct=open_pct,
                    phase=1,
                    description=f"低开{open_pct*100:.1f}%止损",
                )

        # 涨停检查：盘中触及涨停价 → 持有到收盘
        if next_high >= limit_up - 0.005:
            # 收盘仍封死在涨停 → 无法卖出，顺延持有（不提前兑现，偏保守）
            if next_close >= limit_up - 0.005:
                return SellDecision(
                    sell_price=0.0, sell_reason="stuck_limit_up_seal",
                    pnl_pct=close_pct, phase=0,
                    description=f"封板未开无法卖出，顺延（浮盈{close_pct*100:.1f}%）",
                    stuck=True,
                )
            return SellDecision(
                sell_price=round(next_close, 2),
                sell_reason="limit_up_hold",
                pnl_pct=close_pct,
                phase=2,
                description=f"涨停回落，收盘{close_pct*100:.1f}%",
            )

        # 阶段 2：早盘 — 盘中 high/low 是否触及止盈/止损
        # 同日双触：ambiguous_pessimistic=True → 假设先触止损（消除日线对路径的乐观偏差）
        if high_pct >= self.phase2_take_profit and low_pct <= self.phase2_stop_loss:
            if self.ambiguous_pessimistic:
                sell_price = round(buy_price * (1 + self.phase2_stop_loss), 2)
                return SellDecision(
                    sell_price=sell_price,
                    sell_reason="phase2_stop_loss",
                    pnl_pct=self.phase2_stop_loss,
                    phase=2,
                    description=f"双触取悲观：下探{self.phase2_stop_loss*100:.1f}%止损",
                )
            if (next_open - next_low) > (next_high - next_open):
                sell_price = round(buy_price * (1 + self.phase2_take_profit), 2)
                return SellDecision(
                    sell_price=sell_price,
                    sell_reason="phase2_take_profit",
                    pnl_pct=self.phase2_take_profit,
                    phase=2,
                    description=f"盘中冲高{self.phase2_take_profit*100:.1f}%止盈",
                )
            sell_price = round(buy_price * (1 + self.phase2_stop_loss), 2)
            return SellDecision(
                sell_price=sell_price,
                sell_reason="phase2_stop_loss",
                pnl_pct=self.phase2_stop_loss,
                phase=2,
                description=f"盘中下探{self.phase2_stop_loss*100:.1f}%止损",
            )

        if high_pct >= self.phase2_take_profit:
            sell_price = round(buy_price * (1 + self.phase2_take_profit), 2)
            return SellDecision(
                sell_price=sell_price,
                sell_reason="phase2_take_profit",
                pnl_pct=self.phase2_take_profit,
                phase=2,
                description=f"盘中冲高{self.phase2_take_profit*100:.1f}%止盈",
            )

        if low_pct <= self.phase2_stop_loss:
            sell_price = round(buy_price * (1 + self.phase2_stop_loss), 2)
            return SellDecision(
                sell_price=sell_price,
                sell_reason="phase2_stop_loss",
                pnl_pct=self.phase2_stop_loss,
                phase=2,
                description=f"盘中下探{self.phase2_stop_loss*100:.1f}%止损",
            )

        # 阶段 3：观察期（9:45-10:00）— 用 close 判断
        if close_pct > 0:
            return SellDecision(
                sell_price=round(next_close, 2),
                sell_reason="phase3_lock_profit",
                pnl_pct=close_pct,
                phase=3,
                description=f"收盘盈利{close_pct*100:.1f}%锁利",
            )

        if close_pct <= self.phase3_stop_loss:
            return SellDecision(
                sell_price=round(next_close, 2),
                sell_reason="phase3_stop_loss",
                pnl_pct=close_pct,
                phase=3,
                description=f"收盘亏损{close_pct*100:.1f}%止损",
            )

        # 阶段 4：兜底（10:00）
        return SellDecision(
            sell_price=round(next_close, 2),
            sell_reason="phase4_timeout",
            pnl_pct=close_pct,
            phase=4,
            description=f"兜底退出{close_pct*100:.1f}%",
        )

    def batch_decide(self, trades: list) -> list:
        """
        批量决策

        trades: List[dict]，每个 dict 包含 buy_price / next_open /
                next_high / next_low / next_close 字段
        """
        return [self.decide(**t) for t in trades]

    def summary_stats(self, decisions: list) -> dict:
        """
        统计卖出决策分布

        返回：
        {
            "total": int,
            "by_reason": {reason: {"count": int, "avg_pnl": float}},
            "by_phase": {phase: {"count": int, "avg_pnl": float}},
            "avg_pnl": float,
            "win_rate": float,   # pnl_pct > 0 的比例
        }
        """
        if not decisions:
            return {
                "total": 0,
                "by_reason": {},
                "by_phase": {},
                "avg_pnl": 0.0,
                "win_rate": 0.0,
            }

        total = len(decisions)

        # 按 reason 统计
        by_reason: dict = {}
        for d in decisions:
            r = d.sell_reason
            if r not in by_reason:
                by_reason[r] = {"count": 0, "pnl_sum": 0.0}
            by_reason[r]["count"] += 1
            by_reason[r]["pnl_sum"] += d.pnl_pct

        by_reason_stats = {
            r: {
                "count": v["count"],
                "avg_pnl": round(v["pnl_sum"] / v["count"], 6),
            }
            for r, v in by_reason.items()
        }

        # 按 phase 统计
        by_phase: dict = {}
        for d in decisions:
            p = d.phase
            if p not in by_phase:
                by_phase[p] = {"count": 0, "pnl_sum": 0.0}
            by_phase[p]["count"] += 1
            by_phase[p]["pnl_sum"] += d.pnl_pct

        by_phase_stats = {
            p: {
                "count": v["count"],
                "avg_pnl": round(v["pnl_sum"] / v["count"], 6),
            }
            for p, v in by_phase.items()
        }

        avg_pnl = sum(d.pnl_pct for d in decisions) / total
        win_rate = sum(1 for d in decisions if d.pnl_pct > 0) / total

        return {
            "total": total,
            "by_reason": by_reason_stats,
            "by_phase": by_phase_stats,
            "avg_pnl": round(avg_pnl, 6),
            "win_rate": round(win_rate, 4),
        }
