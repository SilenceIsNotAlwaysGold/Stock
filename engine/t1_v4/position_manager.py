"""
T1 v4 仓位管理模块

根据候选数量、近期交易表现、账户状态，动态计算仓位分配。
核心目标：集中持仓但有风控兜底，避免连续亏损时加速回撤。
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional


@dataclass
class PositionAdvice:
    """仓位建议"""

    ts_code: str
    stock_name: str
    score: float
    suggested_pct: float       # 建议仓位百分比 (0.0-1.0)
    suggested_amount: float    # 建议金额
    suggested_quantity: int    # 建议股数（100的整数倍）
    reason: str                # 仓位决策原因


class PositionManager:
    """
    仓位管理器

    核心规则:
    1. 选 1 只 → 最大 60% 仓位，留 40% 现金
    2. 选 2 只 → 50% + 30%，留 20% 现金
    3. 连续亏损 N 次 → 仓位减半
    4. 总回撤超阈值 → 暂停交易 M 天
    """

    DEFAULT_CONFIG = {
        "max_single_pct": 0.60,
        "two_stock_pcts": [0.50, 0.30],
        "cash_reserve_pct": 0.20,
        "consecutive_loss_limit": 3,
        "consecutive_loss_reduce": 0.50,
        "max_drawdown_pct": 0.15,
        "drawdown_pause_days": 3,
        "daily_loss_alert_pct": 0.05,
        "min_lot_size": 100,            # A股最小交易单位
    }

    def __init__(self, **config_overrides):
        self.config = {**self.DEFAULT_CONFIG, **config_overrides}

    def allocate(
        self,
        candidates: list,
        total_cash: float,
        recent_trades: Optional[list] = None,
        account_stats: Optional[dict] = None,
    ) -> List[PositionAdvice]:
        """
        计算仓位分配。

        Args:
            candidates: 排序后的候选列表，每个元素需有
                        ts_code, stock_name, total_score, close_price 属性或键
            total_cash: 当前可用现金
            recent_trades: 近期交易记录列表，每条需有 is_win(bool), sell_date(str)
            account_stats: 账户统计，需有:
                - initial_cash: 初始资金
                - current_value: 当前总资产
                - last_pause_date: 上次暂停日期 (str|None)

        Returns:
            仓位建议列表，可能为空（暂停交易时）
        """
        if not candidates or total_cash <= 0:
            return []

        if recent_trades is None:
            recent_trades = []
        if account_stats is None:
            account_stats = {}

        # 1. 检查回撤暂停
        pause_result = self._check_drawdown_pause(account_stats)
        if pause_result is not None:
            return pause_result

        # 2. 计算减仓系数
        reduce_factor = self._calc_reduce_factor(recent_trades)

        # 3. 分配仓位百分比
        n = min(len(candidates), 2)  # 最多 2 只
        if n == 1:
            raw_pcts = [self.config["max_single_pct"]]
        else:
            raw_pcts = list(self.config["two_stock_pcts"][:2])

        # 应用减仓系数
        adjusted_pcts = [p * reduce_factor for p in raw_pcts]

        # 4. 转换为具体仓位建议
        advices = []
        for i in range(n):
            cand = candidates[i]
            ts_code = self._get_attr(cand, "ts_code")
            stock_name = self._get_attr(cand, "stock_name", "")
            score = float(self._get_attr(cand, "total_score", 0))
            close_price = float(self._get_attr(cand, "close_price", 0))

            pct = adjusted_pcts[i]
            amount = total_cash * pct

            quantity = self._calc_quantity(amount, close_price)

            reason_parts = [f"仓位{pct*100:.0f}%"]
            if reduce_factor < 1.0:
                reason_parts.append(f"(连续亏损降仓{reduce_factor*100:.0f}%)")

            advices.append(PositionAdvice(
                ts_code=ts_code,
                stock_name=stock_name,
                score=score,
                suggested_pct=pct,
                suggested_amount=round(amount, 2),
                suggested_quantity=quantity,
                reason="".join(reason_parts),
            ))

        return advices

    def check_daily_loss_alert(
        self,
        daily_pnl_pct: float,
    ) -> Optional[str]:
        """检查单日亏损是否触发预警。"""
        threshold = self.config["daily_loss_alert_pct"]
        if daily_pnl_pct <= -threshold:
            return f"单日亏损预警: {daily_pnl_pct*100:.1f}% 超过阈值 -{threshold*100:.0f}%"
        return None

    def _check_drawdown_pause(
        self,
        account_stats: dict,
    ) -> Optional[List[PositionAdvice]]:
        """
        检查是否因回撤过大而暂停交易。

        Returns:
            None 表示不暂停，[] 表示暂停（返回空列表）
        """
        initial_cash = account_stats.get("initial_cash")
        current_value = account_stats.get("current_value")
        last_pause_date = account_stats.get("last_pause_date")

        if initial_cash is None or current_value is None:
            return None

        if initial_cash <= 0:
            return None

        drawdown = (initial_cash - current_value) / initial_cash

        if drawdown <= self.config["max_drawdown_pct"]:
            return None

        # 回撤超限，检查冷静期
        pause_days = self.config["drawdown_pause_days"]
        if last_pause_date:
            try:
                pause_start = date.fromisoformat(str(last_pause_date))
                if (date.today() - pause_start).days < pause_days:
                    return []  # 仍在冷静期
            except (ValueError, TypeError):
                pass

        # 触发新的暂停
        return []

    def _calc_reduce_factor(self, recent_trades: list) -> float:
        """
        计算减仓系数。

        检查最近 N 笔交易是否连续亏损。
        """
        limit = self.config["consecutive_loss_limit"]
        if len(recent_trades) < limit:
            return 1.0

        # 取最近 limit 笔，按卖出日期降序
        sorted_trades = sorted(
            recent_trades,
            key=lambda t: t.get("sell_date", ""),
            reverse=True,
        )[:limit]

        all_loss = all(not t.get("is_win", True) for t in sorted_trades)
        if all_loss:
            return self.config["consecutive_loss_reduce"]

        return 1.0

    def _calc_quantity(self, amount: float, price: float) -> int:
        """计算买入股数（100 股整数倍）。"""
        if price <= 0:
            return 0
        lot_size = self.config["min_lot_size"]
        lots = math.floor(amount / (price * lot_size))
        return lots * lot_size

    @staticmethod
    def _get_attr(obj, key, default=None):
        """兼容 dict 和 dataclass 的取值。"""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
