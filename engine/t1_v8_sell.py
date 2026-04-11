"""
T1 v8 卖出引擎：优化止盈止损参数

基于 V7 回测分析：
- 83% 走到固定卖出，胜率仅22% → 问题：持有时间太短
- 开盘止盈(≥1%) 和 盘中冲高(≥2%) 都是100%胜率

优化：
1. 降低开盘止盈阈值到 0.8%（更多交易命中快速止盈）
2. 降低盘中冲高阈值到 1.5%（更容易触发）
3. 收紧止损到 -3%（更快止损减少亏损）
4. 固定卖出改为 9:35（稍早退出减少尾部风险）
"""

import pandas as pd
from typing import Dict, List, Tuple


class T1V8SellEngine:
    """T1 v8 优化卖出引擎"""

    def __init__(self):
        self.open_profit_threshold = 0.8   # 开盘盈利≥0.8%卖出（降低自1%）
        self.intraday_high_threshold = 1.5  # 盘中冲高≥1.5%卖出（降低自2%）
        self.open_stop_loss = -3.0          # 开盘止损-3%（收紧自-4%）
        self.fixed_sell_time = "09:35"      # 9:35卖出

    def decide_sell(
        self, position: Dict, next_day_data: pd.Series
    ) -> Tuple[str, float, str]:
        """决定卖出时机和价格"""
        buy_price = position["buy_price"]
        next_open = next_day_data["open"]
        next_high = next_day_data["high"]
        next_close = next_day_data["close"]

        open_change = (next_open - buy_price) / buy_price * 100

        # 优先级1: 开盘止损
        if open_change <= self.open_stop_loss:
            return "stop_loss_open", next_open, f"开盘止损 {open_change:.2f}%"

        # 优先级2: 开盘止盈
        if open_change >= self.open_profit_threshold:
            return "open_profit_sell", next_open, f"开盘止盈 {open_change:.2f}%"

        # 优先级3: 盘中冲高
        high_change = (next_high - buy_price) / buy_price * 100
        if high_change >= self.intraday_high_threshold:
            sell_price = buy_price * (1 + self.intraday_high_threshold / 100)
            sell_price = min(sell_price, next_high)
            return "intraday_high", sell_price, f"盘中冲高 {high_change:.2f}%"

        # 优先级4: 固定卖出
        return "fixed_time_935", next_close, "9:35固定卖出"

    def batch_decide_sell(
        self, positions: List[Dict], next_day_data: pd.DataFrame
    ) -> List[Dict]:
        """批量决定卖出"""
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
        """统计卖出类型分布"""
        if not sell_decisions:
            return {}

        stats = {
            "total": len(sell_decisions),
            "by_type": {},
        }

        type_groups = {}
        for decision in sell_decisions:
            sell_type = decision.get("sell_type", "unknown")
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

        return stats
