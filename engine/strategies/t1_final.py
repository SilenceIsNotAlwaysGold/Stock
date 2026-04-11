"""
T1 最终策略：回归G12最优因子

基于历史回测验证：
- G12配置：上影线<1% + 前日涨幅<3% + 连涨≤2天
- 胜率：66.7%
- 收益：+26.54%

这是唯一经过验证的有效配置，不再尝试复杂指标。
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional
from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class T1FinalSimple(BaseStrategy):
    """T1 最终策略：简单有效（G12 验证 66.7% 胜率）"""

    name = "t1_final_simple"
    description = "G12因子：上影线<1% + 前日涨幅<3% + 连涨≤2天"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "upper_shadow_max": 1.0,
        "prev_change_max": 3.0,
        "consecutive_up_max": 2,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        """分析单只股票数据，返回标准化信号"""
        if len(df) < 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        last_day = df.iloc[-1]

        # 1. 上影线 < 1%
        if last_day["high"] != last_day["low"]:
            upper_shadow = (
                (last_day["high"] - max(last_day["open"], last_day["close"]))
                / (last_day["high"] - last_day["low"])
                * 100
            )
        else:
            upper_shadow = 0

        if upper_shadow >= self.get_param("upper_shadow_max"):
            return StrategySignal("HOLD", 0.0, f"上影线过长: {upper_shadow:.2f}%")

        # 2. 前日涨幅 < 3%
        prev_close = df.iloc[-2]["close"]
        prev_day_change = (last_day["close"] - prev_close) / prev_close * 100

        if prev_day_change >= self.get_param("prev_change_max"):
            return StrategySignal("HOLD", 0.0, f"前日涨幅过大: {prev_day_change:.2f}%")

        # 3. 连续上涨 ≤ 2天
        consecutive_up = 0
        for i in range(len(df) - 1, 0, -1):
            if df.iloc[i]["close"] > df.iloc[i - 1]["close"]:
                consecutive_up += 1
            else:
                break

        if consecutive_up > self.get_param("consecutive_up_max"):
            return StrategySignal("HOLD", 0.0, f"连涨天数过多: {consecutive_up}")

        # 通过所有条件 - 计算置信度
        confidence = 0.65  # G12 验证基准胜率
        if upper_shadow < 0.5:
            confidence += 0.05
        if prev_day_change < 1.5:
            confidence += 0.05
        if consecutive_up <= 1:
            confidence += 0.05
        confidence = min(confidence, 0.95)

        # 量比和换手率（如果有的话）
        volume_ratio = float(df["volume_ratio"].iloc[-1]) if "volume_ratio" in df.columns else None
        turnover_rate = float(df["turnover_rate"].iloc[-1]) if "turnover_rate" in df.columns else None

        return StrategySignal(
            "BUY",
            confidence,
            f"G12: 上影线={upper_shadow:.2f}% 前日涨幅={prev_day_change:.2f}% 连涨={consecutive_up}天",
            metadata={
                "criterion": "g12_final",
                "volume_ratio": volume_ratio,
                "change_pct": prev_day_change,
                "turnover_rate": turnover_rate,
                "upper_shadow": upper_shadow,
                "consecutive_up": consecutive_up,
            },
        )

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
