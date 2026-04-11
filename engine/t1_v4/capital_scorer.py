"""
T1 v4 资金面连续评分模块

满分 25 分，4 个子项。
资金面直接反映"聪明钱"的态度，是区分主力拉升和散户追涨的核心信号。
"""

import numpy as np
import pandas as pd
from typing import Optional


class CapitalScorer:
    """资金面评分器"""

    MAX_SCORE = 25.0

    def score(
        self,
        money_flow_df: Optional[pd.DataFrame],  # 近几天的资金流数据，含 date/main_net_inflow/main_net_inflow_pct
        turnover_rate: Optional[float],           # 当日换手率（%）
        north_flow_df: Optional[pd.DataFrame],   # 近几天的北向资金数据，含 date/north_net_inflow
    ) -> dict:
        """
        计算资金面评分

        Returns:
            {
                "capital_total": float,         # 总分 0-25
                "main_inflow": float,           # 主力净流入 0-10
                "turnover_score": float,        # 换手率适中 0-5
                "continuous_inflow": float,     # 连续资金流入 0-5
                "north_fund": float,            # 北向资金 0-5
            }
        """
        main_inflow = self._score_main_inflow(money_flow_df)
        turnover = self._score_turnover(turnover_rate)
        continuous = self._score_continuous_inflow(money_flow_df)
        north = self._score_north_fund(north_flow_df)

        return {
            "capital_total": float(np.clip(main_inflow + turnover + continuous + north, 0.0, self.MAX_SCORE)),
            "main_inflow": main_inflow,
            "turnover_score": turnover,
            "continuous_inflow": continuous,
            "north_fund": north,
        }

    def _score_main_inflow(self, money_flow_df: Optional[pd.DataFrame]) -> float:
        """
        主力净流入评分 (0-10)

        使用最后一行的 main_net_inflow_pct（主力净流入占比）连续映射：
          占比 <= -3%:  0 分
          占比   0%:   3 分
          占比   3%:  10 分（满分）
          占比 >  3%:  10 分（截断）
        """
        if money_flow_df is None or len(money_flow_df) == 0:
            return 0.0

        pct = float(money_flow_df["main_net_inflow_pct"].iloc[-1])

        # np.interp 在 xp 边界外自动使用端点值（等效截断）
        xp = [-3.0, 0.0, 3.0]
        fp = [ 0.0, 3.0, 10.0]

        score = float(np.interp(pct, xp, fp))
        return float(np.clip(score, 0.0, 10.0))

    def _score_turnover(self, turnover_rate: Optional[float]) -> float:
        """
        换手率适中评分 (0-5)

        分段线性映射：
          换手率  < 1%:  0 分（死水）
          换手率    3%:  5 分（进入最优区间）
          换手率  3-8%:  5 分（满分，最优区间）
          换手率   12%:  2 分（偏高，可能出货）
          换手率 > 20%:  0 分（异常）
        """
        if turnover_rate is None:
            return 2.5  # 中间值，数据缺失时不惩罚也不奖励

        xp = [0.0, 1.0, 3.0, 8.0, 12.0, 20.0, 100.0]
        fp = [0.0, 0.0, 5.0, 5.0,  2.0,  0.0,   0.0]

        score = float(np.interp(turnover_rate, xp, fp))
        return float(np.clip(score, 0.0, 5.0))

    def _score_continuous_inflow(self, money_flow_df: Optional[pd.DataFrame]) -> float:
        """
        连续资金流入评分 (0-5)

        取最近 3 天（按日期降序前 3 行），统计 main_net_inflow > 0 的天数 count：
          count=0 → 0 分
          count=1 → 1.5 分
          count=2 → 3.0 分
          count=3 → 5.0 分
        """
        if money_flow_df is None or len(money_flow_df) == 0:
            return 0.0

        # 按日期降序取最近 3 天
        df_sorted = money_flow_df.sort_values("date", ascending=False).head(3)
        count = int((df_sorted["main_net_inflow"] > 0).sum())

        xp = [0, 1, 2, 3]
        fp = [0.0, 1.5, 3.0, 5.0]

        score = float(np.interp(count, xp, fp))
        return float(np.clip(score, 0.0, 5.0))

    def _score_north_fund(self, north_flow_df: Optional[pd.DataFrame]) -> float:
        """
        北向资金评分 (0-5)

        取最近 3 天（按日期降序）：
          当日北向净买入 > 0 → +3 分
          连续 3 日北向净买入 > 0 → 额外 +2 分（共 5 分）
          当日北向净买入 <= 0 → 0 分
          数据为 None → 2.5 分（中间值，北向数据经常缺失）
        """
        if north_flow_df is None or len(north_flow_df) == 0:
            return 2.5  # 中间值，数据缺失时不惩罚也不奖励

        df_sorted = north_flow_df.sort_values("date", ascending=False).head(3)
        today_inflow = float(df_sorted["north_net_inflow"].iloc[0])

        if today_inflow <= 0:
            return 0.0

        # 当日为正，基础 3 分
        base_score = 3.0

        # 检查连续 3 日是否全为正
        if len(df_sorted) >= 3 and (df_sorted["north_net_inflow"] > 0).all():
            base_score += 2.0  # 额外 +2，共 5 分

        return float(np.clip(base_score, 0.0, 5.0))
