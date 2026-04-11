"""
T1 v4 板块面连续评分模块

满分 15 分。隔夜策略的核心逻辑是"强者恒强"，
热门板块的股票次日高开概率显著高于冷门板块。
"""

import numpy as np
import pandas as pd
from typing import Optional


class SectorScorer:
    """板块面评分器"""

    MAX_SCORE = 15.0

    def score(
        self,
        sector_rank: Optional[int],        # 个股所属行业的当日涨幅排名（1=最强）
        total_sectors: Optional[int],       # 行业总数
        sector_limit_up_count: int = 0,     # 板块内涨停股票数
        sector_consecutive_strong_days: int = 0,  # 板块连续强势天数（排名前30%的天数）
    ) -> dict:
        """
        计算板块面评分

        Returns:
            {
                "sector_total": float,          # 总分 0-15
                "rank_score": float,            # 行业排名 0-8
                "limit_up_score": float,        # 涨停数 0-4
                "consecutive_strong": float,    # 连续强势 0-3
            }
        """
        rank = self._score_rank(sector_rank, total_sectors)
        limit_up = self._score_limit_up(sector_limit_up_count)
        consecutive = self._score_consecutive_strong(sector_consecutive_strong_days)

        return {
            "sector_total": rank + limit_up + consecutive,
            "rank_score": rank,
            "limit_up_score": limit_up,
            "consecutive_strong": consecutive,
        }

    def _score_rank(
        self,
        sector_rank: Optional[int],
        total_sectors: Optional[int],
    ) -> float:
        """
        行业排名评分 (0-8)

        计算排名百分位 rank_pct = sector_rank / total_sectors（0=最强, 1=最弱）
        连续映射（排名越靠前分越高）：
          rank_pct 0%  (最强): 8 分
          rank_pct 20%        : 8 分（前 20% 都满分）
          rank_pct 50%        : 3 分
          rank_pct 80%        : 0.5 分
          rank_pct 100% (最弱): 0 分
        sector_rank 或 total_sectors 为 None 时返回 4 分（中间值）
        """
        if sector_rank is None or total_sectors is None:
            return 4.0

        if total_sectors <= 0:
            return 4.0

        rank_pct = sector_rank / total_sectors

        xp = [0.0, 0.2, 0.5, 0.8, 1.0]
        fp = [8.0, 8.0, 3.0, 0.5, 0.0]

        score = float(np.interp(rank_pct, xp, fp))
        return float(np.clip(score, 0.0, 8.0))

    def _score_limit_up(self, sector_limit_up_count: int) -> float:
        """
        板块内涨停数评分 (0-4)

        连续映射：
          0 只涨停: 0 分
          1 只    : 1.5 分
          2 只    : 3 分
          >= 3 只 : 4 分（满分）
        """
        xp = [0, 1, 2, 3]
        fp = [0.0, 1.5, 3.0, 4.0]

        score = float(np.interp(sector_limit_up_count, xp, fp))
        return float(np.clip(score, 0.0, 4.0))

    def _score_consecutive_strong(self, sector_consecutive_strong_days: int) -> float:
        """
        板块连续强势天数评分 (0-3)

        连续映射：
          0 天    : 0 分
          1 天    : 1.5 分
          >= 2 天 : 3 分（满分）
        """
        xp = [0, 1, 2]
        fp = [0.0, 1.5, 3.0]

        score = float(np.interp(sector_consecutive_strong_days, xp, fp))
        return float(np.clip(score, 0.0, 3.0))
