"""
动量策略 - N日涨幅排名 + 成交量放大
"""

from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class Momentum(BaseStrategy):
    name = "momentum"
    description = "动量策略：N日涨幅 + 成交量放大"
    category = "momentum"

    default_params: Dict[str, Any] = {
        "lookback": 20,
        "volume_ratio_threshold": 1.5,
        "return_threshold": 0.05,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        lb = self.get_param("lookback")
        if len(df) < lb + 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        df = df.copy()
        # N日涨幅
        n_return = df["close"].iloc[-1] / df["close"].iloc[-lb] - 1
        # 成交量放大
        vol_recent = df["volume"].tail(5).mean()
        vol_avg = df["volume"].tail(lb).mean()
        vol_ratio = vol_recent / max(vol_avg, 1)

        threshold = self.get_param("return_threshold")
        vol_thresh = self.get_param("volume_ratio_threshold")

        if n_return > threshold and vol_ratio > vol_thresh:
            return StrategySignal(
                "BUY", 0.8, f"{lb}日涨幅{n_return*100:.1f}%，量比{vol_ratio:.1f}"
            )
        elif n_return > threshold:
            return StrategySignal(
                "BUY", 0.6, f"{lb}日涨幅{n_return*100:.1f}%，量能一般"
            )
        elif n_return < -threshold and vol_ratio > vol_thresh:
            return StrategySignal(
                "SELL", 0.75, f"{lb}日跌幅{n_return*100:.1f}%，放量下跌"
            )
        return StrategySignal("HOLD", 0.5, "动量不明显")
