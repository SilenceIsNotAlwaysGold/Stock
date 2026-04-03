"""
量价策略 - 量价齐升 + 换手率异常
"""

from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class VolumePrice(BaseStrategy):
    name = "volume_price"
    description = "量价策略：量价齐升 + 换手率异常"
    category = "volume"

    default_params: Dict[str, Any] = {
        "vol_ma_period": 20,
        "vol_ratio_buy": 2.0,
        "price_change_min": 0.02,
        "turnover_threshold": 5.0,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        period = self.get_param("vol_ma_period")
        if len(df) < period + 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        df = df.copy()
        vol_ma = df["volume"].rolling(period).mean()
        df["vol_ratio"] = df["volume"] / vol_ma.replace(0, 1)
        df["price_change"] = df["close"].pct_change()

        last = df.iloc[-1]
        vol_thresh = self.get_param("vol_ratio_buy")
        price_min = self.get_param("price_change_min")

        vol_surge = last["vol_ratio"] > vol_thresh
        price_up = last["price_change"] > price_min
        price_down = last["price_change"] < -price_min

        # 换手率异常
        turnover_high = False
        if "turnover_rate" in df.columns:
            turnover_high = last["turnover_rate"] > self.get_param("turnover_threshold")

        if vol_surge and price_up:
            conf = 0.85 if turnover_high else 0.7
            return StrategySignal("BUY", conf, "量价齐升，放量上涨")
        elif vol_surge and price_down:
            return StrategySignal("SELL", 0.75, "放量下跌，注意风险")
        elif vol_surge and turnover_high:
            return StrategySignal("HOLD", 0.6, "异常放量，观望为主")
        return StrategySignal("HOLD", 0.5, "量价正常")
