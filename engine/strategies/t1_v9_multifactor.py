"""
T1 v9 多因子策略：评分制选股 + RSI(2)反转 + 大盘择时

基于互联网调研 + 回测数据分析的综合策略：

选股（评分制，满分100）：
  A. 价格行为 (35分)
    - 涨幅 1.5%-3.5% 最优区间 (15分)
    - 上影线 < 1% (10分)
    - 连涨 ≤ 2天 (10分)
  B. 量价关系 (30分)
    - 量比 1.2-2.5 (最优区间) (10分)
    - 换手率 2%-6% (最优区间) (10分)
    - 量能较前3日放大 (10分)
  C. 技术因子 (20分)
    - RSI(2) < 30 (超卖反弹) (10分)
    - 价格在 MA5 附近 (回踩支撑) (10分)
  D. 安全过滤 (15分)
    - 前5日涨幅 < 12% (5分)
    - 换手率 < 8% (避免过热) (5分)
    - 非ST/科创板/北交所 (5分)

入场门槛：总分 ≥ 60分
大盘过滤：全市场5日均涨幅 > 0

卖出（优化参数）：
  1. 开盘止损 ≤ -3%
  2. 开盘止盈 ≥ 0.8%
  3. 盘中冲高 ≥ 1.5%
  4. 9:35 固定卖出

调研来源：
- RSI(2) 反转: Larry Connors (75%胜率, SPY验证)
- 尾盘选股: 东方财富/知乎 (涨3-5%, 量比>1.2)
- 量价关系: 换手率3-7%最活跃, 量比>10反转风险
- 大盘择时: 华泰十指标模型 (年化21%, 胜率53%)
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional
from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class T1V9MultiFactor(BaseStrategy):
    """T1 v9 多因子评分策略"""

    name = "t1_v9_multifactor"
    description = "多因子评分: 价格行为+量价关系+RSI反转+大盘择时"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "min_score": 60,
        # 价格行为
        "change_optimal_low": 1.5,
        "change_optimal_high": 3.5,
        "upper_shadow_max": 1.0,
        "consecutive_up_max": 2,
        # 量价
        "volume_ratio_optimal_low": 1.2,
        "volume_ratio_optimal_high": 2.5,
        "turnover_optimal_low": 2.0,
        "turnover_optimal_high": 6.0,
        # 安全
        "gain_5d_max": 12.0,
        "turnover_max": 8.0,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        """分析单只股票数据，返回标准化信号"""
        if len(df) < 20:
            return StrategySignal("HOLD", 0.0, "数据不足")

        last_day = df.iloc[-1]
        prev_day = df.iloc[-2]
        close_prices = df["close"].values

        score = 0
        details = []

        # ============ A. 价格行为 (35分) ============

        # A1. 涨幅 (15分)
        today_change = (last_day["close"] - prev_day["close"]) / prev_day["close"] * 100
        if today_change < 0 or today_change > 5:
            return StrategySignal("HOLD", 0.0, "涨幅超出范围")

        chg_lo = self.get_param("change_optimal_low")
        chg_hi = self.get_param("change_optimal_high")
        if chg_lo <= today_change <= chg_hi:
            score += 15
        elif 0.5 <= today_change < chg_lo:
            score += 8
        elif chg_hi < today_change <= 5.0:
            score += 5

        # A2. 上影线 (10分)
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
        if upper_shadow < 0.3:
            score += 10
        elif upper_shadow < 0.7:
            score += 7
        else:
            score += 3

        # A3. 连涨天数 (10分)
        consecutive_up = 0
        for i in range(len(df) - 1, 0, -1):
            if df.iloc[i]["close"] > df.iloc[i - 1]["close"]:
                consecutive_up += 1
            else:
                break

        if consecutive_up > self.get_param("consecutive_up_max"):
            return StrategySignal("HOLD", 0.0, f"连涨{consecutive_up}天")
        if consecutive_up <= 1:
            score += 10
        else:
            score += 5

        # ============ B. 量价关系 (30分) ============

        # B1. 量比 (10分)
        if "volume_ratio" in df.columns:
            volume_ratio = float(df["volume_ratio"].iloc[-1])
        else:
            today_vol = df["volume"].iloc[-1]
            prev_avg = df["volume"].iloc[-6:-1].mean() if len(df) > 5 else df["volume"].iloc[:-1].mean()
            volume_ratio = today_vol / max(prev_avg, 1)

        vr_lo = self.get_param("volume_ratio_optimal_low")
        vr_hi = self.get_param("volume_ratio_optimal_high")
        if volume_ratio < vr_lo:
            return StrategySignal("HOLD", 0.0, "量比不足")
        if vr_lo <= volume_ratio <= vr_hi:
            score += 10
        elif volume_ratio <= 3.5:
            score += 6
        else:
            score += 2  # 量比过高，可能见顶

        # B2. 换手率 (10分)
        turnover = float(df["turnover_rate"].iloc[-1]) if "turnover_rate" in df.columns else 0
        tr_lo = self.get_param("turnover_optimal_low")
        tr_hi = self.get_param("turnover_optimal_high")
        if tr_lo <= turnover <= tr_hi:
            score += 10
        elif turnover < tr_lo and turnover > 0:
            score += 5
        elif turnover <= self.get_param("turnover_max"):
            score += 4
        else:
            score -= 5  # 换手率>8% 扣分

        # B3. 量能放大 (10分) - 相比前3日
        turnover_rates = df["turnover_rate"].values if "turnover_rate" in df.columns else np.zeros(len(df))
        avg_turnover_3d = np.mean(turnover_rates[-4:-1]) if len(df) >= 4 else 0
        if turnover > 0 and avg_turnover_3d > 0:
            if turnover > avg_turnover_3d * 1.3:
                score += 10
            elif turnover > avg_turnover_3d:
                score += 6
            else:
                score += 2

        # ============ C. 技术因子 (20分) ============

        # C1. RSI(2) 超卖反弹 (10分) - Connors RSI(2) 策略
        if len(df) >= 3:
            # 计算 RSI(2)
            deltas = df["close"].diff().iloc[-3:]
            gains = deltas.clip(lower=0)
            losses = (-deltas.clip(upper=0))
            avg_gain = gains.mean()
            avg_loss = losses.mean()
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi2 = 100 - (100 / (1 + rs))
            else:
                rsi2 = 100 if avg_gain > 0 else 50

            if rsi2 < 15:
                score += 10  # 强超卖
            elif rsi2 < 30:
                score += 7   # 超卖
            elif rsi2 < 50:
                score += 3
            # RSI > 70 不加分（过热）

        # C2. 价格在 MA5 附近 (10分) - 回踩支撑
        ma5 = df["close"].iloc[-5:].mean()
        price_vs_ma5 = (last_day["close"] - ma5) / ma5 * 100
        if -1.0 <= price_vs_ma5 <= 2.0:
            score += 10  # 在 MA5 附近
        elif 2.0 < price_vs_ma5 <= 5.0:
            score += 5   # 略高于 MA5
        elif price_vs_ma5 > 5.0:
            score += 0   # 偏离过远

        # ============ D. 安全过滤 (15分) ============

        # D1. 前5日涨幅 (5分)
        gain_5d = 0.0
        if len(df) >= 6:
            gain_5d = (close_prices[-1] - close_prices[-6]) / close_prices[-6] * 100
            if gain_5d >= self.get_param("gain_5d_max"):
                return StrategySignal("HOLD", 0.0, f"5日涨幅{gain_5d:.1f}%")
            if gain_5d < 5:
                score += 5
            elif gain_5d < 8:
                score += 3

        # D2. 换手率安全 (5分)
        if turnover <= self.get_param("turnover_max"):
            score += 5
        else:
            return StrategySignal("HOLD", 0.0, f"换手率过高{turnover:.1f}%")

        # D3. 基本排除 (5分) - 在 service 层做，这里默认给分
        score += 5

        # ============ 综合评判 ============

        min_score = self.get_param("min_score")
        if score < min_score:
            return StrategySignal("HOLD", 0.0, f"评分{score}分 < {min_score}")

        # 评分转置信度
        confidence = min(0.95, 0.4 + score / 200)

        return StrategySignal(
            "BUY",
            confidence,
            f"V9评分{score}: 涨{today_change:.1f}% 量比{volume_ratio:.1f} 换手{turnover:.1f}% RSI2={rsi2:.0f}",
            metadata={
                "criterion": "v9_multifactor",
                "score": score,
                "volume_ratio": volume_ratio,
                "change_pct": today_change,
                "turnover_rate": turnover,
                "upper_shadow": upper_shadow,
                "consecutive_up": consecutive_up,
                "gain_5d": gain_5d,
                "rsi2": rsi2 if len(df) >= 3 else None,
                "price_vs_ma5": price_vs_ma5,
            },
        )

    def generate_signals(self, data: pd.DataFrame) -> List[Dict]:
        """批量生成信号（回测用）"""
        signals = []

        for ts_code, group in data.groupby("ts_code"):
            group = group.sort_values("date").reset_index(drop=True)
            if len(group) < 20:
                continue

            last_day = group.iloc[-1]
            prev_day = group.iloc[-2]
            close_prices = group["close"].values

            # 快速过滤
            today_change = (last_day["close"] - prev_day["close"]) / prev_day["close"] * 100
            if today_change < 0 or today_change > 5:
                continue

            # 上影线
            if last_day["high"] != last_day["low"]:
                upper_shadow = (
                    (last_day["high"] - max(last_day["open"], last_day["close"]))
                    / (last_day["high"] - last_day["low"]) * 100
                )
            else:
                upper_shadow = 0
            if upper_shadow >= 1.0:
                continue

            # 连涨
            consecutive_up = 0
            for i in range(len(group) - 1, 0, -1):
                if group.iloc[i]["close"] > group.iloc[i - 1]["close"]:
                    consecutive_up += 1
                else:
                    break
            if consecutive_up > 2:
                continue

            # 量比
            volume_ratios = group["volume_ratio"].values if "volume_ratio" in group.columns else np.ones(len(group))
            volume_ratio = float(volume_ratios[-1])
            if volume_ratio < 1.2:
                continue

            # 换手率
            turnover = float(group["turnover_rate"].iloc[-1]) if "turnover_rate" in group.columns else 0
            if turnover > 8:
                continue

            # 5日涨幅
            gain_5d = 0.0
            if len(group) >= 6:
                gain_5d = (close_prices[-1] - close_prices[-6]) / close_prices[-6] * 100
                if gain_5d >= 12:
                    continue

            # === 评分 ===
            score = 0

            # A1 涨幅
            if 1.5 <= today_change <= 3.5:
                score += 15
            elif 0.5 <= today_change < 1.5:
                score += 8
            elif 3.5 < today_change <= 5.0:
                score += 5

            # A2 上影线
            if upper_shadow < 0.3:
                score += 10
            elif upper_shadow < 0.7:
                score += 7
            else:
                score += 3

            # A3 连涨
            score += 10 if consecutive_up <= 1 else 5

            # B1 量比
            if 1.2 <= volume_ratio <= 2.5:
                score += 10
            elif volume_ratio <= 3.5:
                score += 6
            else:
                score += 2

            # B2 换手率
            if 2 <= turnover <= 6:
                score += 10
            elif turnover < 2 and turnover > 0:
                score += 5
            elif turnover <= 8:
                score += 4

            # B3 量能放大
            turnover_rates = group["turnover_rate"].values if "turnover_rate" in group.columns else np.zeros(len(group))
            avg_turnover_3d = float(np.mean(turnover_rates[-4:-1])) if len(group) >= 4 else 0
            if turnover > 0 and avg_turnover_3d > 0:
                if turnover > avg_turnover_3d * 1.3:
                    score += 10
                elif turnover > avg_turnover_3d:
                    score += 6
                else:
                    score += 2

            # C1 RSI(2)
            rsi2 = 50
            if len(group) >= 3:
                deltas = group["close"].diff().iloc[-3:]
                gains = deltas.clip(lower=0)
                losses = (-deltas.clip(upper=0))
                avg_gain = gains.mean()
                avg_loss = losses.mean()
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi2 = 100 - (100 / (1 + rs))
                else:
                    rsi2 = 100 if avg_gain > 0 else 50

            if rsi2 < 15:
                score += 10
            elif rsi2 < 30:
                score += 7
            elif rsi2 < 50:
                score += 3

            # C2 MA5 位置
            ma5 = group["close"].iloc[-5:].mean()
            price_vs_ma5 = (last_day["close"] - ma5) / ma5 * 100
            if -1.0 <= price_vs_ma5 <= 2.0:
                score += 10
            elif 2.0 < price_vs_ma5 <= 5.0:
                score += 5

            # D 安全
            if gain_5d < 5:
                score += 5
            elif gain_5d < 8:
                score += 3
            score += 5  # 换手率已过滤
            score += 5  # 基本排除

            if score < 60:
                continue

            signals.append({
                "ts_code": ts_code,
                "date": last_day["date"],
                "close": last_day["close"],
                "signal": "buy",
                "reason": f"V9评分{score}: 涨{today_change:.1f}% 量比{volume_ratio:.1f} RSI2={rsi2:.0f}",
                "indicators": {
                    "score": score,
                    "today_change": today_change,
                    "volume_ratio": volume_ratio,
                    "turnover_rate": turnover,
                    "upper_shadow": upper_shadow,
                    "consecutive_up": consecutive_up,
                    "gain_5d": gain_5d,
                    "rsi2": rsi2,
                    "price_vs_ma5": price_vs_ma5,
                },
            })

        return signals
