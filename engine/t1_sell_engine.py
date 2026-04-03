"""
T+1 策略 v2 - 早盘智能卖出引擎

分档卖出逻辑：
1. 集合竞价止盈：开盘价 >= 买入价 * 1.05
2. 15分钟止损：跌破买入价 * 0.97
3. 15分钟观察：在 ±3% 内震荡则继续观察
4. 30分钟超时：仍未触发止盈/止损则卖出
5. 10:30 兜底：强制清仓
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class SellReason(str, Enum):
    TAKE_PROFIT_OPEN = "take_profit_open"  # 集合竞价止盈
    STOP_LOSS_15MIN = "stop_loss_15min"  # 15分钟止损
    TIMEOUT_30MIN = "timeout_30min"  # 30分钟超时卖出
    TIMEOUT_1030 = "timeout_1030"  # 10:30 兜底
    LIMIT_UP_HOLD = "limit_up_hold"  # 涨停不卖（特殊）
    MANUAL = "manual"


@dataclass
class SellDecision:
    should_sell: bool = False
    reason: SellReason = SellReason.MANUAL
    sell_price: float = 0.0
    description: str = ""


class SmartSellEngine:
    """
    早盘智能卖出引擎 (R-005)

    根据开盘价和盘中走势，分阶段决定卖出时机。
    """

    DEFAULT_PARAMS = {
        "take_profit_pct": 0.05,  # 开盘止盈线 5%
        "stop_loss_pct": -0.03,  # 止损线 -3%
        "observe_range_pct": 0.03,  # 观察区间 ±3%
        "limit_up_pct": 0.098,  # 涨停阈值
        "open_sell_threshold": 0.005,  # 开盘盈利卖出阈值（默认 0.5%）
    }

    def __init__(self, **overrides):
        self.params = {**self.DEFAULT_PARAMS, **overrides}

    def decide_at_open(
        self,
        buy_price: float,
        open_price: float,
    ) -> SellDecision:
        """
        集合竞价阶段决策（9:25）

        如果开盘价已达止盈线，直接卖出。
        """
        pct = (open_price - buy_price) / buy_price

        if pct >= self.params["take_profit_pct"]:
            return SellDecision(
                should_sell=True,
                reason=SellReason.TAKE_PROFIT_OPEN,
                sell_price=open_price,
                description=f"开盘价 {open_price:.2f} 涨 {pct*100:.1f}%，达到止盈线",
            )

        return SellDecision(
            should_sell=False,
            description=f"开盘价 {open_price:.2f} 涨 {pct*100:.1f}%，进入观察期",
        )

    def decide_at_15min(
        self,
        buy_price: float,
        current_price: float,
        high_price: float,
        low_price: float,
    ) -> SellDecision:
        """
        开盘后 15 分钟决策（9:45）

        - 跌破止损线 → 立即止损
        - 涨停 → 不卖
        - 在观察区间内 → 继续观察
        """
        pct = (current_price - buy_price) / buy_price
        high_pct = (high_price - buy_price) / buy_price

        # 涨停不卖
        if high_pct >= self.params["limit_up_pct"]:
            return SellDecision(
                should_sell=False,
                reason=SellReason.LIMIT_UP_HOLD,
                description=f"触及涨停，继续持有",
            )

        # 止损
        if pct <= self.params["stop_loss_pct"]:
            return SellDecision(
                should_sell=True,
                reason=SellReason.STOP_LOSS_15MIN,
                sell_price=current_price,
                description=f"15分钟跌 {pct*100:.1f}%，触发止损",
            )

        # 在观察区间内，继续观察
        return SellDecision(
            should_sell=False,
            description=f"15分钟涨 {pct*100:.1f}%，在观察区间内",
        )

    def decide_at_30min(
        self,
        buy_price: float,
        current_price: float,
        high_price: float,
    ) -> SellDecision:
        """
        开盘后 30 分钟决策（10:00）

        - 涨停 → 不卖
        - 其他 → 超时卖出
        """
        pct = (current_price - buy_price) / buy_price
        high_pct = (high_price - buy_price) / buy_price

        if high_pct >= self.params["limit_up_pct"]:
            return SellDecision(
                should_sell=False,
                reason=SellReason.LIMIT_UP_HOLD,
                description=f"触及涨停，继续持有",
            )

        return SellDecision(
            should_sell=True,
            reason=SellReason.TIMEOUT_30MIN,
            sell_price=current_price,
            description=f"30分钟超时，当前涨 {pct*100:.1f}%，卖出",
        )

    def decide_at_1030(
        self,
        buy_price: float,
        current_price: float,
    ) -> SellDecision:
        """
        10:30 兜底清仓

        无论什么情况，强制卖出。
        """
        pct = (current_price - buy_price) / buy_price
        return SellDecision(
            should_sell=True,
            reason=SellReason.TIMEOUT_1030,
            sell_price=current_price,
            description=f"10:30 兜底清仓，涨 {pct*100:.1f}%",
        )

    def simulate_morning_sell(
        self,
        buy_price: float,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        vwap_30min: Optional[float] = None,
    ) -> SellDecision:
        """
        回测用：模拟早盘卖出决策。

        用日线数据近似模拟分时走势：
        - open >= buy * 1.05 → 开盘卖
        - open > buy → 直接卖开盘价（锁定隔夜利润）
        - low <= buy * 0.97 → 止损
        - 否则用加权均价作为 30 分钟卖出价
        """
        # 阶段1: 集合竞价止盈
        decision = self.decide_at_open(buy_price, open_price)
        if decision.should_sell:
            return decision

        # 阶段1.5: 开盘盈利直接卖（T+1核心：锁定隔夜跳空利润）
        open_pct = (open_price - buy_price) / buy_price
        threshold = self.params.get("open_sell_threshold", 0.005)
        if open_pct > threshold:
            return SellDecision(
                should_sell=True,
                reason=SellReason.TIMEOUT_30MIN,
                sell_price=open_price,
                description=f"开盘涨 {open_pct*100:.1f}%，锁定隔夜利润",
            )

        # 阶段2: 15分钟止损（用日内最低价近似）
        stop_price = buy_price * (1 + self.params["stop_loss_pct"])
        if low_price <= stop_price:
            return SellDecision(
                should_sell=True,
                reason=SellReason.STOP_LOSS_15MIN,
                sell_price=stop_price,
                description=f"日内低点 {low_price:.2f} 触发止损线 {stop_price:.2f}",
            )

        # 阶段3: 涨停不卖
        limit_price = buy_price * (1 + self.params["limit_up_pct"])
        if high_price >= limit_price:
            return SellDecision(
                should_sell=True,
                reason=SellReason.LIMIT_UP_HOLD,
                sell_price=close_price,
                description=f"触及涨停，收盘价 {close_price:.2f} 卖出",
            )

        # 阶段4: 30分钟超时卖出（加权均价，偏向开盘价）
        sell_price = (
            vwap_30min if vwap_30min else (open_price * 2 + high_price + low_price) / 4
        )
        pct = (sell_price - buy_price) / buy_price
        return SellDecision(
            should_sell=True,
            reason=SellReason.TIMEOUT_30MIN,
            sell_price=sell_price,
            description=f"30分钟超时，均价 {sell_price:.2f}，涨 {pct*100:.1f}%",
        )
