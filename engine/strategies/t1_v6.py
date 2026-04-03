"""
T1 v6 策略：低位反弹 + 优化止损

核心改进：
1. 基于G12最优因子（上影线<1% + 前日涨幅<3% + 连涨≤2天）
2. 增加低位反弹条件（RSI<35 + KDJ<25 + 缩量）
3. 取消-2%盘中止损，改用-3%开盘止损
4. 优化卖出时机（9:30-9:45择机）
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from engine.base import BaseStrategy


class T1V6LowRebound(BaseStrategy):
    """T1 v6 低位反弹策略"""

    name = "t1_v6_low_rebound"

    def __init__(self):
        super().__init__()
        self.rsi_period = 14
        self.kdj_period = 9

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """计算RSI指标"""
        if len(prices) < period + 1:
            return 50.0

        deltas = prices.diff()
        gain = deltas.where(deltas > 0, 0).rolling(window=period).mean()
        loss = -deltas.where(deltas < 0, 0).rolling(window=period).mean()

        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]

    def calculate_kdj(
        self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9
    ) -> Tuple[float, float, float]:
        """计算KDJ指标"""
        if len(close) < period:
            return 50.0, 50.0, 50.0

        low_min = low.rolling(window=period).min()
        high_max = high.rolling(window=period).max()

        rsv = (close - low_min) / (high_max - low_min).replace(0, 1) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d

        return k.iloc[-1], d.iloc[-1], j.iloc[-1]

    def signal(self, data: pd.DataFrame) -> pd.DataFrame:
        """BaseStrategy要求的抽象方法（暂不使用）"""
        return pd.DataFrame()

    def generate_signals(self, data: pd.DataFrame) -> List[Dict]:
        """
        生成买入信号

        选股条件：
        1. 上影线 < 1%
        2. 前日涨幅 < 3%
        3. 连续上涨 ≤ 2天
        4. RSI(14) < 35
        5. KDJ_K < 25
        6. 换手率 1.5%-5%
        7. 量比 < 1.2
        """
        signals = []

        # 按股票分组
        for ts_code, group in data.groupby("ts_code"):
            group = group.sort_values("date").reset_index(drop=True)

            if len(group) < 30:  # 至少需要30天数据计算指标
                continue

            # 获取最后一天数据
            last_day = group.iloc[-1]

            # 计算技术指标
            close_prices = group["close"].values
            high_prices = group["high"].values
            low_prices = group["low"].values

            # RSI
            rsi = self.calculate_rsi(pd.Series(close_prices), self.rsi_period)

            # KDJ
            k, d, j = self.calculate_kdj(
                pd.Series(high_prices),
                pd.Series(low_prices),
                pd.Series(close_prices),
                self.kdj_period,
            )

            # 计算上影线比例
            if last_day["high"] != last_day["low"]:
                upper_shadow = (
                    (last_day["high"] - max(last_day["open"], last_day["close"]))
                    / (last_day["high"] - last_day["low"])
                    * 100
                )
            else:
                upper_shadow = 0

            # 计算前日涨幅
            if len(group) >= 2:
                prev_close = group.iloc[-2]["close"]
                prev_day_change = (last_day["close"] - prev_close) / prev_close * 100
            else:
                prev_day_change = 0

            # 计算连续上涨天数
            consecutive_up = 0
            for i in range(len(group) - 1, 0, -1):
                if group.iloc[i]["close"] > group.iloc[i - 1]["close"]:
                    consecutive_up += 1
                else:
                    break

            # 换手率和量比
            turnover_rate = last_day.get("turnover_rate", 0)
            volume_ratio = last_day.get("volume_ratio", 1.0)

            # 选股条件判断
            conditions = {
                "upper_shadow": upper_shadow < 1.0,
                "prev_day_change": prev_day_change < 3.0,
                "consecutive_up": consecutive_up <= 2,
                "rsi": rsi < 35.0,
                "kdj_k": k < 25.0,
                "turnover_rate": 1.5 <= turnover_rate <= 5.0,
                "volume_ratio": volume_ratio < 1.2,
            }

            # 所有条件都满足才买入
            if all(conditions.values()):
                signals.append(
                    {
                        "ts_code": ts_code,
                        "date": last_day["date"],
                        "close": last_day["close"],
                        "signal": "buy",
                        "reason": f"低位反弹: RSI={rsi:.1f}, K={k:.1f}, 上影线={upper_shadow:.1f}%",
                        "indicators": {
                            "rsi": rsi,
                            "kdj_k": k,
                            "kdj_d": d,
                            "kdj_j": j,
                            "upper_shadow": upper_shadow,
                            "prev_day_change": prev_day_change,
                            "consecutive_up": consecutive_up,
                            "turnover_rate": turnover_rate,
                            "volume_ratio": volume_ratio,
                        },
                    }
                )

        return signals
