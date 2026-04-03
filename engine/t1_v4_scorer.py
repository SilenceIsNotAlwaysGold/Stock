"""
T1 v4 多维度评分器

4个维度评分：
- 趋势健康度（30分）
- 量价关系（25分）
- 价格位置（25分）
- 市场环境（20分）

总分100分，>= threshold 触发买入信号。
"""

import numpy as np
import pandas as pd


class T1V4Scorer:
    """多维度评分器"""

    def score_trend(self, df: pd.DataFrame, i: int) -> float:
        """趋势健康度评分（满分30分）"""
        score = 0.0
        close = df["close"].astype(float)

        if i < 25:
            return 0.0

        # MA多头排列：MA5 > MA10 > MA20 → +10
        ma5 = float(close.iloc[max(0, i - 4) : i + 1].mean())
        ma10 = float(close.iloc[max(0, i - 9) : i + 1].mean())
        ma20 = float(close.iloc[max(0, i - 19) : i + 1].mean())
        current = float(close.iloc[i])

        if current > ma5 > ma10 > ma20:
            score += 10

        # MA20近5日斜率为正 → +5
        if i >= 24:
            ma20_now = float(close.iloc[i - 19 : i + 1].mean())
            ma20_5ago = float(close.iloc[i - 24 : i - 4].mean())
            if ma20_now > ma20_5ago:
                score += 5

        # 布林带中轨上方 → +5
        if i >= 19:
            bb_mid = ma20
            bb_std = float(close.iloc[i - 19 : i + 1].std())
            if current > bb_mid:
                score += 5

        # MACD DIF > DEA → +5
        if i >= 30:
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            dif = float((ema12 - ema26).iloc[i])
            dea = float((ema12 - ema26).ewm(span=9).mean().iloc[i])
            if dif > dea:
                score += 5

        # 收盘在MA5上方 → +5
        if current > ma5:
            score += 5

        return score

    def score_volume(self, df: pd.DataFrame, i: int) -> float:
        """量价关系评分（满分25分）"""
        score = 0.0

        if i < 20:
            return 0.0

        vol = df["volume"].astype(float)
        vol_today = float(vol.iloc[i])
        vol_5avg = float(vol.iloc[max(0, i - 5) : i].mean())
        vol_20avg = float(vol.iloc[max(0, i - 20) : i].mean())

        if vol_5avg <= 0 or vol_20avg <= 0:
            return 0.0

        vol_ratio = vol_today / vol_5avg

        # 量比0.8-1.5（温和放量） → +10
        if 0.8 <= vol_ratio <= 1.5:
            score += 10
        elif 1.5 < vol_ratio <= 2.0:
            score += 5  # 略微放量，给一半分

        # 近3天量能递增 → +5
        if i >= 3:
            v1 = float(vol.iloc[i - 2])
            v2 = float(vol.iloc[i - 1])
            v3 = float(vol.iloc[i])
            if v3 > v2 > v1:
                score += 5

        # 成交量 > 5日均量*0.8 → +5
        if vol_today > vol_5avg * 0.8:
            score += 5

        # 下影线 > 上影线（多方力量）→ +5
        row = df.iloc[i]
        high_val = float(row["high"])
        low_val = float(row["low"])
        open_val = float(row["open"])
        close_val = float(row["close"])

        upper_shadow = high_val - max(open_val, close_val)
        lower_shadow = min(open_val, close_val) - low_val

        if lower_shadow > upper_shadow and upper_shadow >= 0:
            score += 5

        return score

    def score_position(self, df: pd.DataFrame, i: int) -> float:
        """价格位置评分（满分25分）"""
        score = 0.0

        if i < 20:
            return 0.0

        close = df["close"].astype(float)
        current = float(close.iloc[i])
        prev = float(close.iloc[i - 1])

        if prev <= 0:
            return 0.0

        change_pct = (current - prev) / prev * 100

        # 当天涨幅0-3%（蓄势区间）→ +10
        if 0 <= change_pct <= 3:
            score += 10
        elif -1 <= change_pct < 0:
            score += 5  # 微跌也可以

        # 上影线 < 0.5% → +5
        high_val = float(df.iloc[i]["high"])
        if current > 0:
            upper_shadow_pct = (high_val - current) / current * 100
            if upper_shadow_pct < 0.5:
                score += 5

        # 距前高 <= 5%（接近突破）→ +5
        high_20d = float(df["high"].iloc[max(0, i - 20) : i].max())
        if high_20d > 0:
            dist_high = (high_20d - current) / high_20d * 100
            if dist_high <= 5:
                score += 5

        # 距MA60 <= 8% → +5
        if i >= 60:
            ma60 = float(close.iloc[i - 59 : i + 1].mean())
            if ma60 > 0:
                dist_ma60 = abs(current - ma60) / ma60 * 100
                if dist_ma60 <= 8:
                    score += 5

        return score

    def score_market(self, df: pd.DataFrame, i: int, context: dict = None) -> float:
        """市场环境评分（满分20分）"""
        if not context:
            return 10  # 无市场数据时给中间分

        score = 0.0
        market_score = context.get("market_score", 50)
        market_bullish = context.get("market_bullish", None)

        # 大盘当天看多 → +8
        if market_bullish is True:
            score += 8

        # 大盘评分较高 → +4
        if market_score >= 55:
            score += 4

        # 大盘评分适中（非极端）→ +4
        if 40 <= market_score <= 70:
            score += 4

        # 大盘情绪不差 → +4
        mood = context.get("market_mood", "")
        if mood in ("bullish", "neutral"):
            score += 4

        return min(score, 20)

    def total_score(self, df: pd.DataFrame, i: int, context: dict = None) -> dict:
        """计算总分和各维度分数"""
        trend = self.score_trend(df, i)
        volume = self.score_volume(df, i)
        position = self.score_position(df, i)
        market = self.score_market(df, i, context)

        return {
            "total": trend + volume + position + market,
            "trend": trend,
            "volume": volume,
            "position": position,
            "market": market,
        }
