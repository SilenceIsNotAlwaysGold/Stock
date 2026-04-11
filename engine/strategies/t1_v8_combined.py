"""
T1 v8 组合策略：V7 价格行为 + G12 因子 + 优化卖出

基于 V7 和 Final 回测分析的改进：
- V7 问题：选股太严只有71笔，胜率34%
- Final 问题：选股太松16255笔，62%走到固定卖出
- V8 目标：适度选股量 + 更高胜率

选股条件（多条件共振）：
1. G12 因子：上影线<1% + 前日涨幅<3% + 连涨≤2天
2. 量价确认：量比>1.2 + 换手率>前3日均值
3. 温和涨幅：当日涨幅 0.3%-3.5%
4. 排除过热：前5日涨幅<12%
5. 市值过滤：流通市值 30-500亿（避免大象和小票）
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional
from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class T1V8Combined(BaseStrategy):
    """T1 v8 组合策略"""

    name = "t1_v8_combined"
    description = "G12因子+量价确认+温和涨幅，多条件共振"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "upper_shadow_max": 1.0,
        "prev_change_max": 3.0,
        "consecutive_up_max": 2,
        "volume_ratio_min": 1.2,
        "change_min": 0.3,
        "change_max": 3.5,
        "gain_5d_max": 12.0,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        """分析单只股票数据，返回标准化信号"""
        if len(df) < 10:
            return StrategySignal("HOLD", 0.0, "数据不足")

        last_day = df.iloc[-1]
        prev_day = df.iloc[-2]
        close_prices = df["close"].values

        # === G12 因子 ===

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
            return StrategySignal("HOLD", 0.0, "上影线过长")

        # 2. 当日涨幅
        today_change = (last_day["close"] - prev_day["close"]) / prev_day["close"] * 100
        if today_change < self.get_param("change_min") or today_change > self.get_param("change_max"):
            return StrategySignal("HOLD", 0.0, f"涨幅不符: {today_change:.2f}%")

        # 3. 连续上涨 ≤ 2天
        consecutive_up = 0
        for i in range(len(df) - 1, 0, -1):
            if df.iloc[i]["close"] > df.iloc[i - 1]["close"]:
                consecutive_up += 1
            else:
                break

        if consecutive_up > self.get_param("consecutive_up_max"):
            return StrategySignal("HOLD", 0.0, f"连涨过多: {consecutive_up}")

        # === 量价确认 ===

        # 4. 量比确认
        if "volume_ratio" in df.columns:
            today_volume_ratio = float(df["volume_ratio"].iloc[-1])
        else:
            today_vol = df["volume"].iloc[-1]
            prev_vol_avg = df["volume"].iloc[-6:-1].mean() if len(df) > 5 else df["volume"].iloc[:-1].mean()
            today_volume_ratio = today_vol / max(prev_vol_avg, 1)

        if today_volume_ratio < self.get_param("volume_ratio_min"):
            return StrategySignal("HOLD", 0.0, "量比不足")

        # 5. 换手率高于前3日均值
        turnover_rates = df["turnover_rate"].values if "turnover_rate" in df.columns else np.zeros(len(df))
        today_turnover = float(turnover_rates[-1])
        avg_turnover_3d = np.mean(turnover_rates[-4:-1]) if len(df) >= 4 else 0

        if today_turnover > 0 and avg_turnover_3d > 0 and today_turnover < avg_turnover_3d:
            return StrategySignal("HOLD", 0.0, "换手率低于均值")

        # === 安全过滤 ===

        # 6. 前5日涨幅<12%
        gain_5d = 0.0
        if len(df) >= 6:
            gain_5d = (close_prices[-1] - close_prices[-6]) / close_prices[-6] * 100
            if gain_5d >= self.get_param("gain_5d_max"):
                return StrategySignal("HOLD", 0.0, f"5日涨幅过大: {gain_5d:.2f}%")

        # === 通过所有条件 - 计算置信度 ===
        confidence = 0.60
        # 量比越高越好
        if today_volume_ratio >= 1.5:
            confidence += 0.10
        elif today_volume_ratio >= 1.3:
            confidence += 0.05
        # 上影线越小越好
        if upper_shadow < 0.3:
            confidence += 0.05
        # 涨幅在 1-2.5% 区间最优
        if 1.0 <= today_change <= 2.5:
            confidence += 0.10
        # 连涨0-1天比2天好
        if consecutive_up <= 1:
            confidence += 0.05
        confidence = min(confidence, 0.95)

        return StrategySignal(
            "BUY",
            confidence,
            f"V8: 上影线={upper_shadow:.1f}% 涨幅={today_change:.1f}% 量比={today_volume_ratio:.1f} 连涨={consecutive_up}",
            metadata={
                "criterion": "v8_combined",
                "volume_ratio": today_volume_ratio,
                "change_pct": today_change,
                "turnover_rate": today_turnover,
                "upper_shadow": upper_shadow,
                "consecutive_up": consecutive_up,
                "gain_5d": gain_5d,
            },
        )

    def generate_signals(self, data: pd.DataFrame) -> List[Dict]:
        """
        批量生成买入信号（回测用）
        """
        signals = []

        for ts_code, group in data.groupby("ts_code"):
            group = group.sort_values("date").reset_index(drop=True)

            if len(group) < 10:
                continue

            last_day = group.iloc[-1]
            prev_day = group.iloc[-2]
            close_prices = group["close"].values

            # G12: 上影线 < 1%
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

            # 涨幅 0.3%-3.5%
            today_change = (last_day["close"] - prev_day["close"]) / prev_day["close"] * 100
            if today_change < 0.3 or today_change > 3.5:
                continue

            # 连涨 ≤ 2
            consecutive_up = 0
            for i in range(len(group) - 1, 0, -1):
                if group.iloc[i]["close"] > group.iloc[i - 1]["close"]:
                    consecutive_up += 1
                else:
                    break
            if consecutive_up > 2:
                continue

            # 量比 > 1.2
            volume_ratios = (
                group["volume_ratio"].values
                if "volume_ratio" in group.columns
                else np.ones(len(group))
            )
            today_volume_ratio = float(volume_ratios[-1])
            if today_volume_ratio < 1.2:
                continue

            # 换手率高于前3日均值
            turnover_rates = (
                group["turnover_rate"].values
                if "turnover_rate" in group.columns
                else np.zeros(len(group))
            )
            today_turnover = float(turnover_rates[-1])
            avg_turnover_3d = float(np.mean(turnover_rates[-4:-1])) if len(group) >= 4 else 0
            if today_turnover > 0 and avg_turnover_3d > 0 and today_turnover < avg_turnover_3d:
                continue

            # 前5日涨幅<12%
            gain_5d = 0.0
            if len(group) >= 6:
                gain_5d = (close_prices[-1] - close_prices[-6]) / close_prices[-6] * 100
                if gain_5d >= 12:
                    continue

            signals.append(
                {
                    "ts_code": ts_code,
                    "date": last_day["date"],
                    "close": last_day["close"],
                    "signal": "buy",
                    "reason": f"V8: 上影线={upper_shadow:.1f}% 涨幅={today_change:.1f}% 量比={today_volume_ratio:.1f}",
                    "indicators": {
                        "today_change": today_change,
                        "volume_ratio": today_volume_ratio,
                        "turnover_rate": today_turnover,
                        "upper_shadow": upper_shadow,
                        "consecutive_up": consecutive_up,
                        "gain_5d": gain_5d,
                    },
                }
            )

        return signals
