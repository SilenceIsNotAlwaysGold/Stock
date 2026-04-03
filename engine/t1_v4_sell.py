"""
T1 v4 简化版卖出引擎

基于开盘价的直接决策，不再用日线模拟分时。
"""

from dataclasses import dataclass


@dataclass
class V4SellDecision:
    sell_price: float
    sell_reason: str
    pnl_pct: float
    description: str


class T1V4SellEngine:
    """
    v4 简化版卖出引擎

    3级决策（基于次日开盘价）：
    1. 高开止盈：开盘涨 >= take_profit_pct → 开盘价卖出
    2. 低开止损：开盘跌 >= stop_loss_pct → 开盘价卖出
    3. 正常退出：用VWAP均价 (O+H+L+C)/4 卖出
    """

    def __init__(
        self,
        take_profit_pct: float = 0.03,
        stop_loss_pct: float = -0.02,
        limit_up_pct: float = 0.098,
    ):
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.limit_up_pct = limit_up_pct

    def decide(
        self,
        buy_price: float,
        next_open: float,
        next_high: float,
        next_low: float,
        next_close: float,
    ) -> V4SellDecision:
        open_pct = (next_open - buy_price) / buy_price

        # 1. 高开止盈
        if open_pct >= self.take_profit_pct:
            return V4SellDecision(
                sell_price=next_open,
                sell_reason="take_profit_open",
                pnl_pct=round(open_pct * 100, 2),
                description=f"高开{open_pct*100:.1f}%止盈",
            )

        # 2. 低开止损
        if open_pct <= self.stop_loss_pct:
            return V4SellDecision(
                sell_price=next_open,
                sell_reason="stop_loss_open",
                pnl_pct=round(open_pct * 100, 2),
                description=f"低开{open_pct*100:.1f}%止损",
            )

        # 3. 涨停不卖（用收盘价）
        high_pct = (next_high - buy_price) / buy_price
        if high_pct >= self.limit_up_pct:
            pnl = (next_close - buy_price) / buy_price
            return V4SellDecision(
                sell_price=next_close,
                sell_reason="limit_up_hold",
                pnl_pct=round(pnl * 100, 2),
                description=f"涨停持有，收盘卖{pnl*100:.1f}%",
            )

        # 4. 盘中止损检查
        low_pct = (next_low - buy_price) / buy_price
        if low_pct <= self.stop_loss_pct:
            stop_price = buy_price * (1 + self.stop_loss_pct)
            return V4SellDecision(
                sell_price=stop_price,
                sell_reason="stop_loss_intraday",
                pnl_pct=round(self.stop_loss_pct * 100, 2),
                description=f"盘中触及止损线{self.stop_loss_pct*100:.1f}%",
            )

        # 5. 正常退出：VWAP均价
        vwap = (next_open + next_high + next_low + next_close) / 4
        pnl = (vwap - buy_price) / buy_price
        return V4SellDecision(
            sell_price=round(vwap, 2),
            sell_reason="vwap_exit",
            pnl_pct=round(pnl * 100, 2),
            description=f"VWAP均价退出{pnl*100:.1f}%",
        )
