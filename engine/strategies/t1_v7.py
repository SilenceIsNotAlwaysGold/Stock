"""
T1 v7 策略：价格行为 + 动态止盈

核心理念：
1. 放弃复杂技术指标（RSI/KDJ不可靠）
2. 专注价格形态：缩量回调后的首次放量
3. 动态止盈：根据次日表现灵活卖出
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional
from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class T1V7PriceAction(BaseStrategy):
    """T1 v7 价格行为策略"""

    name = "t1_v7_price_action"
    description = "缩量回调后放量上涨，价格行为策略"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "volume_ratio_min": 1.3,
        "change_min": 0.5,
        "change_max": 4.0,
        "upper_shadow_max": 2.0,
        "gain_5d_max": 15.0,
        "decline_3d_max": -8.0,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        """分析单只股票数据，返回标准化信号"""
        if len(df) < 10:
            return StrategySignal("HOLD", 0.0, "数据不足")

        close_prices = df["close"].values
        turnover_rates = (
            df["turnover_rate"].values
            if "turnover_rate" in df.columns
            else np.zeros(len(df))
        )

        # 计算量比（如果没有 volume_ratio 列，用当日成交量/前5日均量）
        if "volume_ratio" in df.columns:
            today_volume_ratio = float(df["volume_ratio"].iloc[-1])
        else:
            today_vol = df["volume"].iloc[-1]
            prev_vol_avg = df["volume"].iloc[-6:-1].mean() if len(df) > 5 else df["volume"].iloc[:-1].mean()
            today_volume_ratio = today_vol / max(prev_vol_avg, 1)

        today_turnover = float(turnover_rates[-1])
        last_day = df.iloc[-1]

        # 1. 前3日缩量回调（换手率递减，跌幅<8%）
        last_3_turnover = turnover_rates[-4:-1]
        last_3_close = close_prices[-4:-1]

        if not (last_3_turnover[0] > last_3_turnover[1] > last_3_turnover[2]):
            return StrategySignal("HOLD", 0.0, "前3日未缩量")

        decline_3d = (last_3_close[-1] - last_3_close[0]) / last_3_close[0] * 100
        if decline_3d > 0 or decline_3d < self.get_param("decline_3d_max"):
            return StrategySignal("HOLD", 0.0, f"3日跌幅不符: {decline_3d:.2f}%")

        # 2. 当日放量
        avg_turnover_3d = np.mean(last_3_turnover)
        if today_volume_ratio < self.get_param("volume_ratio_min") or today_turnover < avg_turnover_3d:
            return StrategySignal("HOLD", 0.0, "当日未放量")

        # 3. 温和上涨
        today_change = (last_day["close"] - df.iloc[-2]["close"]) / df.iloc[-2]["close"] * 100
        if today_change < self.get_param("change_min") or today_change > self.get_param("change_max"):
            return StrategySignal("HOLD", 0.0, f"涨幅不符: {today_change:.2f}%")

        # 4. 上影线<2%
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

        # 5. 前5日涨幅<15%
        gain_5d = 0.0
        if len(df) >= 6:
            gain_5d = (close_prices[-1] - close_prices[-6]) / close_prices[-6] * 100
            if gain_5d >= self.get_param("gain_5d_max"):
                return StrategySignal("HOLD", 0.0, f"5日涨幅过大: {gain_5d:.2f}%")

        # 通过所有条件 - 计算置信度
        confidence = 0.6
        if today_volume_ratio >= 1.5:
            confidence += 0.1
        if 1.0 <= today_change <= 3.0:
            confidence += 0.1
        if upper_shadow < 1.0:
            confidence += 0.05
        confidence = min(confidence, 0.95)

        return StrategySignal(
            "BUY",
            confidence,
            f"缩量回调后放量 量比={today_volume_ratio:.2f} 涨幅={today_change:.2f}%",
            metadata={
                "criterion": "price_action_v7",
                "volume_ratio": today_volume_ratio,
                "change_pct": today_change,
                "turnover_rate": today_turnover,
                "upper_shadow": upper_shadow,
                "decline_3d": decline_3d,
                "gain_5d": gain_5d,
            },
        )

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
