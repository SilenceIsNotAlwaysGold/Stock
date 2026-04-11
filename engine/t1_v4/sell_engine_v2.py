"""
T1 v4 卖出引擎 v2

4 阶段决策，用日线 OHLCV 近似模拟分时逻辑。
核心改进：给盈利交易更多发展时间，低开快速止损。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SellDecision:
    """卖出决策结果"""
    sell_price: float          # 卖出价格
    sell_reason: str           # 决策原因标签
    pnl_pct: float            # 盈亏百分比（小数，0.03 表示 3%）
    phase: int                 # 哪个阶段触发的 (1-4)
    description: str           # 人类可读描述


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
        phase1_stop_loss: float = -0.02,    # 低开止损线 -2%
        # 阶段 2 参数
        phase2_take_profit: float = 0.03,   # 盘中止盈 3%
        phase2_stop_loss: float = -0.02,    # 盘中止损 -2%
        # 阶段 3 参数
        phase3_stop_loss: float = -0.015,   # 观察期止损 -1.5%
        # 涨停阈值
        limit_up_pct: float = 0.098,
    ):
        self.phase1_take_profit = phase1_take_profit
        self.phase1_stop_loss = phase1_stop_loss
        self.phase2_take_profit = phase2_take_profit
        self.phase2_stop_loss = phase2_stop_loss
        self.phase3_stop_loss = phase3_stop_loss
        self.limit_up_pct = limit_up_pct

    def decide(
        self,
        buy_price: float,
        next_open: float,
        next_high: float,
        next_low: float,
        next_close: float,
    ) -> SellDecision:
        """
        基于次日 OHLCV 做卖出决策

        用日线数据近似分时逻辑：
        - open  → 集合竞价价格
        - high  → 盘中最高（可达 take_profit 检查）
        - low   → 盘中最低（可达 stop_loss 检查）
        - close → 收盘价（兜底退出价格）

        决策优先级（按时间顺序）：
        1. 开盘涨>=5%  → 开盘价卖出（阶段1 止盈）
        2. 开盘跌<=-2% → 开盘价卖出（阶段1 止损）
        3. 涨停检查    → high 触及涨停价 → 收盘价卖出（持有到收盘）
        4. 盘中 high 触及 +3% 且 low 触及 -2% → 用 open 位置判断先后
        5. 盘中 high 触及 +3% → 以 buy_price*(1+3%) 止盈
        6. 盘中 low  触及 -2% → 以 buy_price*(1-2%) 止损
        7. 收盘盈利 > 0        → 收盘价卖出（锁利）
        8. 收盘亏损 <= -1.5%   → 收盘价卖出（止损）
        9. 兜底                → 收盘价卖出
        """
        open_pct = (next_open - buy_price) / buy_price
        high_pct = (next_high - buy_price) / buy_price
        low_pct = (next_low - buy_price) / buy_price
        close_pct = (next_close - buy_price) / buy_price

        # 阶段 1：集合竞价（9:25）
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

        # 涨停检查（阶段 2 之前：涨停日持有到收盘）
        if high_pct >= self.limit_up_pct:
            return SellDecision(
                sell_price=round(next_close, 2),
                sell_reason="limit_up_hold",
                pnl_pct=close_pct,
                phase=2,
                description=f"涨停持有，收盘{close_pct*100:.1f}%",
            )

        # 阶段 2：早盘（9:30-9:45）— 检查盘中 high/low 是否触及止盈/止损
        # 如果 high 和 low 同时触发，用 open 位置判断哪个先发生：
        #   open 更接近 high → 可能先冲高再回落 → 先触发止盈
        #   open 更接近 low  → 可能先下探再反弹 → 先触发止损
        if high_pct >= self.phase2_take_profit and low_pct <= self.phase2_stop_loss:
            if (next_open - next_low) > (next_high - next_open):
                # open 更接近 high，先冲高 → 止盈
                sell_price = round(buy_price * (1 + self.phase2_take_profit), 2)
                return SellDecision(
                    sell_price=sell_price,
                    sell_reason="phase2_take_profit",
                    pnl_pct=self.phase2_take_profit,
                    phase=2,
                    description=f"盘中冲高{self.phase2_take_profit*100:.1f}%止盈",
                )
            else:
                # open 更接近 low，先下探 → 止损
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
