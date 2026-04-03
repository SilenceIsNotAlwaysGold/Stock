"""
T1 Optimized 卖出引擎：更快止盈

基于Final策略的教训：
- 止盈阈值太高（0.8%/1.5%），很多股票达不到
- 9:35太晚，应该更早卖出

优化：
1. 降低止盈：0.5%/1.0%
2. 提前卖出：9:30
3. 放宽止损：-5%
"""

import pandas as pd
from typing import Dict, List, Tuple


class T1OptimizedSellEngine:
    """T1 优化卖出引擎"""

    def __init__(self):
        self.open_profit_threshold = 0.5  # 开盘盈利≥0.5%卖
        self.intraday_high_threshold = 1.0  # 盘中冲高≥1.0%卖
        self.open_stop_loss = -5.0  # 开盘止损-5%
        self.fixed_sell_time = "09:30"

    def decide_sell(
        self, position: Dict, next_day_data: pd.Series
    ) -> Tuple[str, float, str]:
        buy_price = position["buy_price"]
        next_open = next_day_data["open"]
        next_high = next_day_data["high"]
        next_close = next_day_data["close"]

        open_change = (next_open - buy_price) / buy_price * 100

        # 优先级1: 开盘止损-5%
        if open_change <= self.open_stop_loss:
            return "stop_loss_open", next_open, f"开盘止损 {open_change:.2f}%"

        # 优先级2: 开盘盈利≥0.5%
        if open_change >= self.open_profit_threshold:
            return "open_profit_sell", next_open, f"开盘止盈 {open_change:.2f}%"

        # 优先级3: 盘中冲高≥1.0%
        high_change = (next_high - buy_price) / buy_price * 100
        if high_change >= self.intraday_high_threshold:
            sell_price = buy_price * (1 + self.intraday_high_threshold / 100)
            sell_price = min(sell_price, next_high)
            return "intraday_high", sell_price, f"盘中冲高 {high_change:.2f}%"

        # 优先级4: 9:30固定卖出
        return "fixed_time_930", next_close, "9:30固定卖出"

    def batch_decide_sell(
        self, positions: List[Dict], next_day_data: pd.DataFrame
    ) -> List[Dict]:
        sell_decisions = []

        for position in positions:
            ts_code = position["ts_code"]
            stock_next_data = next_day_data[next_day_data["ts_code"] == ts_code]

            if stock_next_data.empty:
                sell_decisions.append(
                    {
                        "ts_code": ts_code,
                        "sell_type": "suspended",
                        "sell_price": position["buy_price"],
                        "reason": "次日停牌",
                    }
                )
                continue

            stock_next_data = stock_next_data.iloc[0]
            sell_type, sell_price, reason = self.decide_sell(position, stock_next_data)

            sell_decisions.append(
                {
                    "ts_code": ts_code,
                    "sell_type": sell_type,
                    "sell_price": sell_price,
                    "reason": reason,
                    "buy_price": position["buy_price"],
                    "profit_pct": (sell_price - position["buy_price"])
                    / position["buy_price"]
                    * 100,
                }
            )

        return sell_decisions

    def get_statistics(self, sell_decisions: List[Dict]) -> Dict:
        if not sell_decisions:
            return {}

        stats = {
            "total": len(sell_decisions),
            "by_type": {},
            "overall_win_rate": 0,
            "overall_avg_profit": 0,
        }

        type_groups = {}
        for decision in sell_decisions:
            sell_type = decision["sell_type"]
            if sell_type not in type_groups:
                type_groups[sell_type] = []
            type_groups[sell_type].append(decision)

        for sell_type, decisions in type_groups.items():
            profits = [d["profit_pct"] for d in decisions]
            wins = sum(1 for p in profits if p > 0)

            stats["by_type"][sell_type] = {
                "count": len(decisions),
                "win_rate": wins / len(decisions) * 100 if decisions else 0,
                "avg_profit": sum(profits) / len(profits) if profits else 0,
                "pct_of_total": len(decisions) / len(sell_decisions) * 100,
            }

        all_profits = [d["profit_pct"] for d in sell_decisions]
        all_wins = sum(1 for p in all_profits if p > 0)
        stats["overall_win_rate"] = (
            all_wins / len(all_profits) * 100 if all_profits else 0
        )
        stats["overall_avg_profit"] = (
            sum(all_profits) / len(all_profits) if all_profits else 0
        )

        return stats
