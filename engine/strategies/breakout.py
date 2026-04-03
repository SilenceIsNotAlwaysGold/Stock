"""
突破策略 - 箱体突破 + 新高突破
"""

from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class Breakout(BaseStrategy):
    name = "breakout"
    description = "突破策略：箱体突破 + 新高突破"
    category = "breakout"

    default_params: Dict[str, Any] = {
        "box_period": 20,
        "confirm_days": 2,
        "volume_confirm_ratio": 1.3,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        period = self.get_param("box_period")
        if len(df) < period + 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        df = df.copy()
        box = df.iloc[-(period + 1) : -1]
        box_high = box["high"].max()
        box_low = box["low"].min()

        last = df.iloc[-1]
        confirm = self.get_param("confirm_days")
        vol_ratio = self.get_param("volume_confirm_ratio")

        vol_ma = df["volume"].tail(period).mean()
        vol_confirm = last["volume"] > vol_ma * vol_ratio

        # 向上突破
        if last["close"] > box_high:
            # 检查确认天数
            recent_above = sum(
                1 for _, r in df.tail(confirm).iterrows() if r["close"] > box_high
            )
            if recent_above >= confirm and vol_confirm:
                return StrategySignal(
                    "BUY", 0.85, f"放量突破{period}日箱体高点{box_high:.2f}"
                )
            elif recent_above >= confirm:
                return StrategySignal(
                    "BUY", 0.65, f"突破{period}日箱体高点，量能待确认"
                )

        # 向下突破
        if last["close"] < box_low:
            return StrategySignal("SELL", 0.75, f"跌破{period}日箱体低点{box_low:.2f}")

        return StrategySignal("HOLD", 0.5, "价格在箱体内震荡")
