"""
T1 v7 策略：价格行为 + 动态止盈

核心理念：
1. 放弃复杂技术指标（RSI/KDJ不可靠）
2. 专注价格形态：缩量回调后的首次放量
3. 动态止盈：根据次日表现灵活卖出
"""

import pandas as pd
import numpy as np
from typing import Dict, List
from engine.base import BaseStrategy


class T1V7PriceAction(BaseStrategy):
    """T1 v7 价格行为策略"""

    name = "t1_v7_price_action"

    def signal(self, data: pd.DataFrame) -> pd.DataFrame:
        """BaseStrategy要求的抽象方法"""
        return pd.DataFrame()

    def generate_signals(self, data: pd.DataFrame) -> List[Dict]:
        """
        生成买入信号

        选股逻辑：
        1. 前3日缩量回调（换手率递减，跌幅<8%）
        2. 当日放量（量比>1.3，换手率>前3日平均）
        3. 温和上涨（涨幅0.5%-4%）
        4. 收盘价接近最高价（上影线<2%）
        5. 非连续大涨（前5日涨幅<15%）
        """
        signals = []

        for ts_code, group in data.groupby("ts_code"):
            group = group.sort_values("date").reset_index(drop=True)

            if len(group) < 10:
                continue

            last_day = group.iloc[-1]

            # 基础数据
            close_prices = group["close"].values
            turnover_rates = (
                group["turnover_rate"].values
                if "turnover_rate" in group.columns
                else np.zeros(len(group))
            )
            volume_ratios = (
                group["volume_ratio"].values
                if "volume_ratio" in group.columns
                else np.ones(len(group))
            )

            # 1. 前3日缩量回调
            if len(group) < 4:
                continue

            last_3_turnover = turnover_rates[-4:-1]  # 前3日
            last_3_close = close_prices[-4:-1]

            # 换手率递减
            if not (last_3_turnover[0] > last_3_turnover[1] > last_3_turnover[2]):
                continue

            # 跌幅<8%
            decline_3d = (last_3_close[-1] - last_3_close[0]) / last_3_close[0] * 100
            if decline_3d > 0 or decline_3d < -8:
                continue

            # 2. 当日放量
            today_volume_ratio = volume_ratios[-1]
            today_turnover = turnover_rates[-1]
            avg_turnover_3d = np.mean(last_3_turnover)

            if today_volume_ratio < 1.3 or today_turnover < avg_turnover_3d:
                continue

            # 3. 温和上涨
            today_change = (
                (last_day["close"] - group.iloc[-2]["close"])
                / group.iloc[-2]["close"]
                * 100
            )
            if today_change < 0.5 or today_change > 4.0:
                continue

            # 4. 上影线<2%
            if last_day["high"] != last_day["low"]:
                upper_shadow = (
                    (last_day["high"] - max(last_day["open"], last_day["close"]))
                    / (last_day["high"] - last_day["low"])
                    * 100
                )
            else:
                upper_shadow = 0

            if upper_shadow >= 2.0:
                continue

            # 5. 前5日涨幅<15%
            if len(group) >= 6:
                gain_5d = (close_prices[-1] - close_prices[-6]) / close_prices[-6] * 100
                if gain_5d >= 15:
                    continue

            # 通过所有条件
            signals.append(
                {
                    "ts_code": ts_code,
                    "date": last_day["date"],
                    "close": last_day["close"],
                    "signal": "buy",
                    "reason": f"缩量回调后放量 量比={today_volume_ratio:.2f} 涨幅={today_change:.2f}%",
                    "indicators": {
                        "today_change": today_change,
                        "volume_ratio": today_volume_ratio,
                        "turnover_rate": today_turnover,
                        "upper_shadow": upper_shadow,
                        "decline_3d": decline_3d,
                        "gain_5d": gain_5d if len(group) >= 6 else 0,
                    },
                }
            )

        return signals
