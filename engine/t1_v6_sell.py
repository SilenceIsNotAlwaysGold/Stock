"""
T1 v6 卖出引擎：优化止损 + 择机卖出

核心改进：
1. 取消-2%盘中止损（v5失败根源）
2. 改用-3%开盘止损
3. 优化卖出时机：9:30-9:45择机
"""

import pandas as pd
from typing import Dict, List, Tuple


class T1V6SellEngine:
    """T1 v6 卖出引擎"""

    def __init__(self):
        self.open_stop_loss = -3.0  # 开盘止损-3%
        self.high_open_threshold = 2.0  # 高开≥2%集合竞价卖
        self.intraday_high_threshold = 3.0  # 盘中冲高≥3%立即卖
        self.fixed_sell_time = "09:45"  # 固定卖出时间

    def decide_sell(
        self,
        position: Dict,
        next_day_data: pd.Series,
        intraday_data: pd.DataFrame = None,
    ) -> Tuple[str, float, str]:
        """
        决定卖出时机和价格

        Args:
            position: 持仓信息 {'ts_code', 'buy_price', 'buy_date', ...}
            next_day_data: 次日日线数据
            intraday_data: 次日分钟数据（可选，用于模拟盘中卖出）

        Returns:
            (sell_type, sell_price, reason)
        """
        buy_price = position["buy_price"]
        next_open = next_day_data["open"]
        next_high = next_day_data["high"]
        next_close = next_day_data["close"]

        # 计算开盘涨跌幅
        open_change = (next_open - buy_price) / buy_price * 100

        # 优先级1: 开盘止损-3%
        if open_change <= self.open_stop_loss:
            return "stop_loss_open", next_open, f"开盘止损 {open_change:.2f}%"

        # 优先级2: 集合竞价高开≥2%
        if open_change >= self.high_open_threshold:
            return "auction_sell", next_open, f"集合竞价高开 {open_change:.2f}%"

        # 优先级3: 盘中冲高≥3%（使用最高价模拟）
        high_change = (next_high - buy_price) / buy_price * 100
        if high_change >= self.intraday_high_threshold:
            # 假设在冲高时卖出（实际价格可能略低于最高价）
            sell_price = buy_price * (1 + self.intraday_high_threshold / 100)
            sell_price = min(sell_price, next_high)  # 不超过最高价
            return "intraday_high", sell_price, f"盘中冲高 {high_change:.2f}%"

        # 优先级4: 9:45固定卖出（使用收盘价模拟）
        # 实际应该用9:45的价格，这里简化用收盘价
        return "fixed_time_945", next_close, "9:45固定卖出"

    def batch_decide_sell(
        self, positions: List[Dict], next_day_data: pd.DataFrame
    ) -> List[Dict]:
        """
        批量决定卖出

        Args:
            positions: 持仓列表
            next_day_data: 次日数据（包含所有持仓股票）

        Returns:
            卖出决策列表
        """
        sell_decisions = []

        for position in positions:
            ts_code = position["ts_code"]

            # 获取该股票次日数据
            stock_next_data = next_day_data[next_day_data["ts_code"] == ts_code]

            if stock_next_data.empty:
                # 次日停牌或无数据，继续持有
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

            # 决定卖出
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
        """
        统计卖出类型分布

        Returns:
            {
                'total': 总交易数,
                'by_type': {卖出类型: {'count': 次数, 'win_rate': 胜率, 'avg_profit': 平均收益}},
                'overall_win_rate': 总胜率,
                'overall_avg_profit': 总平均收益
            }
        """
        if not sell_decisions:
            return {}

        stats = {
            "total": len(sell_decisions),
            "by_type": {},
            "overall_win_rate": 0,
            "overall_avg_profit": 0,
        }

        # 按类型统计
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

        # 总体统计
        all_profits = [d["profit_pct"] for d in sell_decisions]
        all_wins = sum(1 for p in all_profits if p > 0)
        stats["overall_win_rate"] = (
            all_wins / len(all_profits) * 100 if all_profits else 0
        )
        stats["overall_avg_profit"] = (
            sum(all_profits) / len(all_profits) if all_profits else 0
        )

        return stats
