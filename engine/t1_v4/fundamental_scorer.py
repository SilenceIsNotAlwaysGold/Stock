"""
T1 v4 基本面连续评分模块

满分 15 分，作为底线过滤。
基本面不用于精确选股，而是排除亏损股、高估值泡沫股、财务异常股。
数据按季度更新，缓存即可。
"""

import numpy as np
import pandas as pd
from typing import Optional


class FundamentalScorer:
    """基本面评分器"""

    MAX_SCORE = 15.0

    def score(
        self,
        fina_df: Optional[pd.DataFrame],    # 财务指标，含 roe/netprofit_yoy/eps
        pe: Optional[float],                  # 当前 PE（市盈率）
        industry_pe_median: Optional[float],  # 行业 PE 中位数
    ) -> dict:
        """
        计算基本面评分

        Args:
            fina_df: 财务指标 DataFrame，取最近一期（第一行）
            pe: 当前动态 PE
            industry_pe_median: 所属行业的 PE 中位数

        Returns:
            {
                "fundamental_total": float,    # 总分 0-15
                "roe_score": float,            # ROE 0-5
                "profit_growth": float,        # 净利润增速 0-5
                "pe_reasonable": float,        # PE合理性 0-5
            }
        """
        roe = self._score_roe(fina_df)
        profit = self._score_profit_growth(fina_df)
        pe_score = self._score_pe_reasonable(pe, industry_pe_median)

        return {
            "fundamental_total": float(np.clip(roe + profit + pe_score, 0.0, self.MAX_SCORE)),
            "roe_score": roe,
            "profit_growth": profit,
            "pe_reasonable": pe_score,
        }

    def _score_roe(self, fina_df: Optional[pd.DataFrame]) -> float:
        """
        ROE 评分 (0-5)

        从 fina_df 取最近一期的 roe 值（百分比）。
        np.interp 连续映射：
          ROE <= 0%: 0 分（亏损）
          ROE  5%:  2 分
          ROE 10%:  5 分（满分）
          ROE > 10%: 5 分

        xp = [0, 5, 10], fp = [0, 2, 5]
        缺失时返回 2 分（中间偏低，作为惩罚）
        """
        if fina_df is None or fina_df.empty:
            return 2.0

        if "roe" not in fina_df.columns:
            return 2.0

        roe_val = fina_df["roe"].iloc[0]
        if pd.isna(roe_val):
            return 2.0

        roe_val = float(roe_val)

        xp = [0.0, 5.0, 10.0]
        fp = [0.0, 2.0,  5.0]

        score = float(np.interp(roe_val, xp, fp))
        return float(np.clip(score, 0.0, 5.0))

    def _score_profit_growth(self, fina_df: Optional[pd.DataFrame]) -> float:
        """
        净利润增速评分 (0-5)

        从 fina_df 取 netprofit_yoy（净利润同比增长率，百分比）。
        np.interp 连续映射：
          增速 <= -20%: 0 分
          增速    0%:  2 分
          增速   20%:  5 分（满分）
          增速  > 20%: 5 分

        xp = [-20, 0, 20], fp = [0, 2, 5]
        缺失时返回 2 分
        """
        if fina_df is None or fina_df.empty:
            return 2.0

        if "netprofit_yoy" not in fina_df.columns:
            return 2.0

        yoy_val = fina_df["netprofit_yoy"].iloc[0]
        if pd.isna(yoy_val):
            return 2.0

        yoy_val = float(yoy_val)

        xp = [-20.0,  0.0, 20.0]
        fp = [  0.0,  2.0,  5.0]

        score = float(np.interp(yoy_val, xp, fp))
        return float(np.clip(score, 0.0, 5.0))

    def _score_pe_reasonable(
        self,
        pe: Optional[float],
        industry_pe_median: Optional[float],
    ) -> float:
        """
        PE 合理性评分 (0-5)

        计算 pe_ratio = pe / industry_pe_median，分段线性映射：
          pe_ratio <= 0:   0 分（负 PE，亏损）
          pe_ratio  0.3:  2 分
          pe_ratio  0.5:  5 分
          pe_ratio  1.5:  5 分
          pe_ratio  2.5:  2 分
          pe_ratio >= 4.0: 0 分（严重高估）

        xp = [0, 0.3, 0.5, 1.5, 2.5, 4.0], fp = [0, 2, 5, 5, 2, 0]
        pe 或 industry_pe_median 为 None/0 时返回 2.5 分
        """
        if pe is None or industry_pe_median is None:
            return 2.5

        if industry_pe_median == 0:
            return 2.5

        pe_ratio = float(pe) / float(industry_pe_median)

        xp = [0.0, 0.3, 0.5, 1.5, 2.5, 4.0]
        fp = [0.0, 2.0, 5.0, 5.0, 2.0, 0.0]

        score = float(np.interp(pe_ratio, xp, fp))
        return float(np.clip(score, 0.0, 5.0))
