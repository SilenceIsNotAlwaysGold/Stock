"""
T1 v4 市场面连续评分模块

满分 15 分，用于环境适配。
当市场环境差时压低总分，避免在系统性下跌中选股。
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional

from engine.t1_filters import MarketEnvironmentFilter


class MarketScorer:
    """市场面评分器"""

    MAX_SCORE = 15.0

    def __init__(self):
        self._env_filter = MarketEnvironmentFilter()

    def score(
        self,
        index_df: Optional[pd.DataFrame],    # 上证指数日线（至少30天），含 close/volume
        market_stats: Optional[Dict] = None,  # 市场统计 {up_count, down_count, limit_up, limit_down, total_amount}
    ) -> dict:
        """
        计算市场面评分

        Args:
            index_df: 指数日线数据
            market_stats: 市场统计数据
                - up_count: 上涨家数
                - down_count: 下跌家数
                - limit_up: 涨停数
                - limit_down: 跌停数
                - total_amount: 两市成交额（亿元）

        Returns:
            {
                "market_total": float,          # 总分 0-15
                "trend_score": float,           # 大盘趋势 0-5
                "sentiment_score": float,       # 市场情绪 0-5
                "activity_score": float,        # 成交额活跃度 0-5
            }
        """
        trend = self._score_trend(index_df, market_stats)
        sentiment = self._score_sentiment(market_stats)
        activity = self._score_activity(market_stats)

        return {
            "market_total": trend + sentiment + activity,
            "trend_score": trend,
            "sentiment_score": sentiment,
            "activity_score": activity,
        }

    def _score_trend(
        self,
        index_df: Optional[pd.DataFrame],
        market_stats: Optional[Dict],
    ) -> float:
        """
        大盘趋势评分 (0-5)

        调用 MarketEnvironmentFilter.evaluate() 获取 0-100 分，归一化到 0-5。
        数据不足时返回中间值 2.5 分。
        """
        if index_df is None or len(index_df) < 30:
            return 2.5

        env = self._env_filter.evaluate(index_df, market_stats)
        trend = 5.0 * float(np.clip(env.score / 100.0, 0.0, 1.0))
        return float(trend)

    def _score_sentiment(self, market_stats: Optional[Dict]) -> float:
        """
        市场情绪评分 (0-5)

        基于涨跌比（up_count / down_count）连续映射：
          ad_ratio <= 0.5: 0 分
          ad_ratio  0.8:  1 分
          ad_ratio  1.0:  2.5 分
          ad_ratio  1.5:  5 分（满分）
          ad_ratio > 1.5: 5 分

        market_stats 为 None 时返回 2.5 分。
        """
        if market_stats is None:
            return 2.5

        up = market_stats.get("up_count", 0)
        down = market_stats.get("down_count", 1)
        ad_ratio = up / max(down, 1)

        xp = [0.5, 0.8, 1.0, 1.5]
        fp = [0.0, 1.0, 2.5, 5.0]

        score = float(np.interp(ad_ratio, xp, fp))
        return float(np.clip(score, 0.0, 5.0))

    def _score_activity(self, market_stats: Optional[Dict]) -> float:
        """
        成交额活跃度评分 (0-5)

        基于两市成交额（亿元）连续映射：
          < 5000亿:  0 分
          7000亿:    2 分
          10000亿:   5 分（万亿，满分）
          > 10000亿: 5 分

        total_amount 缺失时返回 2.5 分。
        """
        if market_stats is None:
            return 2.5

        total_amount = market_stats.get("total_amount")
        if total_amount is None:
            return 2.5

        xp = [5000.0, 7000.0, 10000.0]
        fp = [0.0,    2.0,    5.0]

        score = float(np.interp(total_amount, xp, fp))
        return float(np.clip(score, 0.0, 5.0))

    def is_tradable(
        self,
        index_df: Optional[pd.DataFrame],
        market_stats: Optional[Dict] = None,
    ) -> bool:
        """
        判断当前市场是否适合交易（复用 MarketEnvironmentFilter）

        index_df 数据不足 30 天时返回 False。
        否则调用 env_filter.evaluate() 返回 env.is_tradable。
        """
        if index_df is None or len(index_df) < 30:
            return False

        env = self._env_filter.evaluate(index_df, market_stats)
        return env.is_tradable
