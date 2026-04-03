"""
均值回归策略 - 布林带下轨反弹 + RSI 超卖
"""

from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class MeanReversion(BaseStrategy):
    name = "mean_reversion"
    description = "均值回归：布林带下轨反弹 + RSI 超卖"
    category = "reversion"

    default_params: Dict[str, Any] = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        period = self.get_param("bb_period")
        if len(df) < period + 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        df = df.copy()
        # 布林带
        df["bb_mid"] = df["close"].rolling(period).mean()
        std = df["close"].rolling(period).std()
        df["bb_upper"] = df["bb_mid"] + self.get_param("bb_std") * std
        df["bb_lower"] = df["bb_mid"] - self.get_param("bb_std") * std

        # RSI
        rsi_p = self.get_param("rsi_period")
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_p).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_p).mean()
        rs = gain / loss.replace(0, 1e-10)
        df["rsi"] = 100 - (100 / (1 + rs))

        last = df.iloc[-1]
        oversold = self.get_param("rsi_oversold")
        overbought = self.get_param("rsi_overbought")

        below_lower = last["close"] <= last["bb_lower"]
        rsi_low = last["rsi"] < oversold
        above_upper = last["close"] >= last["bb_upper"]
        rsi_high = last["rsi"] > overbought

        if below_lower and rsi_low:
            return StrategySignal("BUY", 0.8, "触及布林下轨 + RSI 超卖")
        elif below_lower:
            return StrategySignal("BUY", 0.6, "触及布林下轨")
        elif above_upper and rsi_high:
            return StrategySignal("SELL", 0.8, "触及布林上轨 + RSI 超买")
        elif above_upper:
            return StrategySignal("SELL", 0.6, "触及布林上轨")
        return StrategySignal("HOLD", 0.5, "价格在布林带内")
