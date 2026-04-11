"""
T1 v4 技术面连续评分模块

满分 30 分，4 个子项全部使用连续评分函数。
不使用 if-else 硬阈值，全部使用 numpy clip/where 等向量化操作。
"""

import numpy as np
import pandas as pd


class TechScorer:
    """技术面评分器"""

    MAX_SCORE = 30.0

    def score(self, df: pd.DataFrame, i: int) -> dict:
        """
        计算第 i 行的技术面评分

        Args:
            df: 日线 DataFrame，含 open/high/low/close/volume 列
            i: 行索引（当日位置）

        Returns:
            {
                "tech_total": float,        # 总分 0-30
                "trend_strength": float,    # 趋势强度 0-10
                "momentum_quality": float,  # 动量质量 0-8
                "volume_price": float,      # 量价配合 0-7
                "candle_shape": float,      # K线形态 0-5
            }
        """
        if i < 25:  # 数据不足
            return self._empty_scores()

        trend = self._score_trend_strength(df, i)
        momentum = self._score_momentum_quality(df, i)
        volume = self._score_volume_price(df, i)
        candle = self._score_candle_shape(df, i)

        return {
            "tech_total": trend + momentum + volume + candle,
            "trend_strength": trend,
            "momentum_quality": momentum,
            "volume_price": volume,
            "candle_shape": candle,
        }

    def _score_trend_strength(self, df: pd.DataFrame, i: int) -> float:
        """
        趋势强度评分 (0-10)

        计算价格相对 MA5/MA10/MA20 的偏离程度，连续评分。
        每条均线贡献约 3.33 分，用偏离百分比线性调制：
          - close 比均线高 5%+ → 满分（3.33 分）
          - close 比均线高 0%  → 0 分
          - close 低于均线    → 0 分（截断）
        三条均线得分加总，上限 10 分。
        """
        close = df["close"].astype(float)
        current = float(close.iloc[i])

        ma5 = float(close.iloc[max(0, i - 4): i + 1].mean())
        ma10 = float(close.iloc[max(0, i - 9): i + 1].mean())
        ma20 = float(close.iloc[max(0, i - 19): i + 1].mean())

        # 每条均线：偏离度 0~5% 线性映射到 0~3.33 分，超过 5% 给满分
        # score_per_ma = 3.33 * clip(deviation_pct / 5.0, 0, 1)
        per_ma_max = 10.0 / 3.0  # 约 3.333

        def _ma_score(ma_val: float) -> float:
            if ma_val <= 0:
                return 0.0
            deviation_pct = (current - ma_val) / ma_val * 100.0
            # 线性映射：[0%, 5%] → [0, per_ma_max]，截断到 [0, per_ma_max]
            raw = per_ma_max * np.clip(deviation_pct / 5.0, 0.0, 1.0)
            return float(raw)

        total = _ma_score(ma5) + _ma_score(ma10) + _ma_score(ma20)
        return float(np.clip(total, 0.0, 10.0))

    def _score_momentum_quality(self, df: pd.DataFrame, i: int) -> float:
        """
        动量质量评分 (0-8)

        当日涨幅使用梯形函数（trapezoid），不使用 if-else 硬阈值：
          [0%, 1%)   线性 0 → 4
          [1%, 2%)   线性 4 → 8
          [2%, 5%]   满分 8
          (5%, 7%]   线性 8 → 4
          (7%, 10%]  线性 4 → 0
          负涨幅      0
          >10%       0
        """
        close = df["close"].astype(float)
        prev = float(close.iloc[i - 1])
        curr = float(close.iloc[i])

        if prev <= 0:
            return 0.0

        chg = (curr - prev) / prev * 100.0  # 涨幅百分比

        # 使用 numpy.interp 实现分段线性映射（连续无硬阈值）
        # xp 为控制点涨幅，fp 为对应分数
        xp = [-1.0, 0.0, 1.0, 2.0, 5.0, 7.0, 10.0, 11.0]
        fp = [0.0,  0.0, 4.0, 8.0, 8.0, 4.0,  0.0,  0.0]

        score = float(np.interp(chg, xp, fp))
        return float(np.clip(score, 0.0, 8.0))

    def _score_volume_price(self, df: pd.DataFrame, i: int) -> float:
        """
        量价配合评分 (0-7)

        量比（今日成交量 / 5日均量）分段线性映射：
          量比 < 0.5              0 分
          量比 0.5 ~ 1.5          线性上升到 7 分
          量比 1.5 ~ 3.0          满分 7 分
          量比 3.0 ~ 5.0          线性下降到 1 分
          量比 > 5.0              1 分（异常放量）
        """
        vol = df["volume"].astype(float)
        vol_today = float(vol.iloc[i])

        # 5 日均量用前 5 日（不含当日）
        start = max(0, i - 5)
        vol_5avg = float(vol.iloc[start:i].mean()) if i > 0 else 0.0

        if vol_5avg <= 0 or vol_today < 0:
            return 0.0

        vol_ratio = vol_today / vol_5avg

        xp = [0.0, 0.5, 1.5, 3.0, 5.0, 100.0]
        fp = [0.0, 0.0, 7.0, 7.0, 1.0,   1.0]

        score = float(np.interp(vol_ratio, xp, fp))
        return float(np.clip(score, 0.0, 7.0))

    def _score_candle_shape(self, df: pd.DataFrame, i: int) -> float:
        """
        K线形态评分 (0-5)

        两个子项各 2.5 分：
        1. 实体占比 (0-2.5)：body_ratio = |close-open| / (high-low)
           body_ratio >= 0.7 → 满分 2.5，线性映射 [0, 0.7] → [0, 2.5]
        2. 上影线短 (0-2.5)：upper_shadow_pct = (high - max(open,close)) / close * 100
           shadow_score = 2.5 * max(0, 1 - upper_shadow_pct / 2.0)
           0%→2.5分，2%→0分，连续衰减
        """
        row = df.iloc[i]
        high_val = float(row["high"])
        low_val = float(row["low"])
        open_val = float(row["open"])
        close_val = float(row["close"])

        # --- 子项1：实体占比 ---
        candle_range = high_val - low_val
        if candle_range <= 0:
            body_score = 0.0
        else:
            body_ratio = abs(close_val - open_val) / candle_range
            # [0, 0.7] → [0, 2.5]，超过 0.7 截断到满分
            body_score = float(np.clip(2.5 * body_ratio / 0.7, 0.0, 2.5))

        # --- 子项2：上影线短 ---
        if close_val <= 0:
            shadow_score = 0.0
        else:
            upper_shadow = high_val - max(open_val, close_val)
            upper_shadow = max(upper_shadow, 0.0)  # 防止浮点负值
            upper_shadow_pct = upper_shadow / close_val * 100.0
            # 2%→0分，0%→2.5分，连续线性衰减
            shadow_score = float(np.clip(2.5 * (1.0 - upper_shadow_pct / 2.0), 0.0, 2.5))

        return float(np.clip(body_score + shadow_score, 0.0, 5.0))

    def _empty_scores(self) -> dict:
        return {
            "tech_total": 0.0,
            "trend_strength": 0.0,
            "momentum_quality": 0.0,
            "volume_price": 0.0,
            "candle_shape": 0.0,
        }
