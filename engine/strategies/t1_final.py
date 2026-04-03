"""
T1 最终策略：回归G12最优因子

基于你的历史回测验证：
- G12配置：上影线<1% + 前日涨幅<3% + 连涨≤2天
- 胜率：66.7%
- 收益：+26.54%

这是唯一经过验证的有效配置，不再尝试复杂指标。
"""

import pandas as pd
import numpy as np
from typing import Dict, List
from engine.base import BaseStrategy


class T1FinalSimple(BaseStrategy):
    """T1 最终策略：简单有效"""

    name = "t1_final_simple"

    def signal(self, data: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame()

    def generate_signals(self, data: pd.DataFrame) -> List[Dict]:
        """
        选股条件（G12验证有效）：
        1. 上影线 < 1%
        2. 前日涨幅 < 3%
        3. 连续上涨 ≤ 2天
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

            signals.append(
                {
                    "ts_code": ts_code,
                    "date": last_day["date"],
                    "close": last_day["close"],
                    "signal": "buy",
                    "reason": f"G12: 上影线={upper_shadow:.2f}% 前日涨幅={prev_day_change:.2f}% 连涨={consecutive_up}天",
                    "indicators": {
                        "upper_shadow": upper_shadow,
                        "prev_day_change": prev_day_change,
                        "consecutive_up": consecutive_up,
                    },
                }
            )

        return signals
