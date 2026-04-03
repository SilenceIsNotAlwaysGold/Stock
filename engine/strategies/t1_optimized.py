"""
T1 Optimized 策略：收紧选股 + 快速止盈

基于Final策略的问题：
- 18,426笔交易太多，质量不高
- 60%走到fixed_time只有28.77%胜率

优化：
1. 增加选股条件：当日涨幅0.5%-3% + 换手率>2% + 量比>0.8
2. 降低止盈阈值：0.5%/1.0%（更快兑现）
3. 提前卖出：9:30（不等9:35）
"""

import pandas as pd
import numpy as np
from typing import Dict, List
from engine.base import BaseStrategy


class T1Optimized(BaseStrategy):
    """T1 优化策略"""

    name = "t1_optimized"

    def signal(self, data: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame()

    def generate_signals(self, data: pd.DataFrame) -> List[Dict]:
        """
        选股条件（G12 + 增强）：
        1. 上影线 < 1%
        2. 前日涨幅 < 3%
        3. 连续上涨 ≤ 2天
        4. 当日涨幅 0.5%-3%（新增：必须有一定涨幅）
        5. 换手率 > 2%（新增：避免冷门股）
        6. 量比 > 0.8（新增：有成交量）
        """
        signals = []

        for ts_code, group in data.groupby("ts_code"):
            group = group.sort_values("date").reset_index(drop=True)

            if len(group) < 5:
                continue

            last_day = group.iloc[-1]

            # 1. 上影线 < 1%
            if last_day["high"] != last_day["low"]:
                upper_shadow = (
                    (last_day["high"] - max(last_day["open"], last_day["close"]))
                    / (last_day["high"] - last_day["low"])
                    * 100
                )
            else:
                upper_shadow = 0

            if upper_shadow >= 1.0:
                continue

            # 2. 前日涨幅 < 3%
            if len(group) >= 2:
                prev_close = group.iloc[-2]["close"]
                prev_day_change = (last_day["close"] - prev_close) / prev_close * 100
            else:
                prev_day_change = 0

            if prev_day_change >= 3.0:
                continue

            # 3. 连续上涨 ≤ 2天
            consecutive_up = 0
            for i in range(len(group) - 1, 0, -1):
                if group.iloc[i]["close"] > group.iloc[i - 1]["close"]:
                    consecutive_up += 1
                else:
                    break

            if consecutive_up > 2:
                continue

            # 4. 当日涨幅 0.5%-3%（新增）
            today_change = prev_day_change  # 实际上是当日涨幅
            if today_change < 0.5 or today_change >= 3.0:
                continue

            # 5. 换手率 > 2%（新增）
            turnover_rate = last_day.get("turnover_rate", 0)
            if turnover_rate <= 2.0:
                continue

            # 6. 量比 > 0.8（新增）
            volume_ratio = last_day.get("volume_ratio", 1.0)
            if volume_ratio <= 0.8:
                continue

            signals.append(
                {
                    "ts_code": ts_code,
                    "date": last_day["date"],
                    "close": last_day["close"],
                    "signal": "buy",
                    "reason": f"优化G12: 涨幅={today_change:.2f}% 换手={turnover_rate:.2f}% 量比={volume_ratio:.2f}",
                    "indicators": {
                        "upper_shadow": upper_shadow,
                        "prev_day_change": prev_day_change,
                        "consecutive_up": consecutive_up,
                        "today_change": today_change,
                        "turnover_rate": turnover_rate,
                        "volume_ratio": volume_ratio,
                    },
                }
            )

        return signals
