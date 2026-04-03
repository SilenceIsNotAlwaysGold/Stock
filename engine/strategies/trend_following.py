"""
趋势跟踪策略 - 均线多头排列 + MACD 金叉
"""

from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class TrendFollowing(BaseStrategy):
    name = "trend_following"
    description = "趋势跟踪：均线多头排列 + MACD 金叉"
    category = "trend"

    default_params: Dict[str, Any] = {
        "ma_short": 5,
        "ma_mid": 10,
        "ma_long": 20,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        if len(df) < self.get_param("ma_long") + 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        ms = self.get_param("ma_short")
        mm = self.get_param("ma_mid")
        ml = self.get_param("ma_long")

        df = df.copy()
        df["ma_s"] = df["close"].rolling(ms).mean()
        df["ma_m"] = df["close"].rolling(mm).mean()
        df["ma_l"] = df["close"].rolling(ml).mean()

        # MACD
        fast = self.get_param("macd_fast")
        slow = self.get_param("macd_slow")
        sig = self.get_param("macd_signal")
        ema_f = df["close"].ewm(span=fast).mean()
        ema_s = df["close"].ewm(span=slow).mean()
        df["dif"] = ema_f - ema_s
        df["dea"] = df["dif"].ewm(span=sig).mean()
        df["macd_hist"] = (df["dif"] - df["dea"]) * 2

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # 均线多头排列
        ma_bull = last["ma_s"] > last["ma_m"] > last["ma_l"]
        # MACD 金叉
        macd_cross = prev["dif"] <= prev["dea"] and last["dif"] > last["dea"]
        # MACD 在零轴上方
        macd_above = last["dif"] > 0

        if ma_bull and macd_cross:
            return StrategySignal("BUY", 0.85, "均线多头排列 + MACD 金叉")
        elif ma_bull and macd_above:
            return StrategySignal("BUY", 0.65, "均线多头排列，MACD 零轴上方")
        elif not ma_bull and last["dif"] < last["dea"]:
            return StrategySignal("SELL", 0.7, "均线空头，MACD 死叉")
        return StrategySignal("HOLD", 0.5, "趋势不明确")
