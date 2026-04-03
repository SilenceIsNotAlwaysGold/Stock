"""
T1 v4 蓄势隔夜策略

核心理念：不追涨，找蓄势待发的股票。
评分制选股（总分100），替代v3的共振+过滤模式。
"""

from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry
from engine.t1_v4_scorer import T1V4Scorer


@StrategyRegistry.register
class T1V4Accumulation(BaseStrategy):
    """
    T+1 v4 蓄势隔夜策略

    多维度评分选股：
    - 趋势健康度（30分）：均线多头、MACD多头
    - 量价关系（25分）：温和放量、量能递增
    - 价格位置（25分）：蓄势区间（涨0-3%）、低上影线
    - 市场环境（20分）：大盘正向
    总分 >= score_threshold 触发买入
    """

    name = "t1_v4_accumulation"
    description = "v4蓄势隔夜：多维度评分+蓄势选股+简化卖出"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "score_threshold": 65,
        "require_bullish_market": True,
        "max_change_pct": 3.0,  # 当天最大涨幅（蓄势，不追涨）
        "min_change_pct": -1.0,  # 当天最小涨幅（不要跌太多）
        "rsi_max": 70,  # RSI上限（宽松一点）
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.scorer = T1V4Scorer()

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        if len(df) < 60:
            return StrategySignal("HOLD", 0.0, "数据不足60天")

        i = len(df) - 1
        ctx = context or {}

        # === 大盘过滤 ===
        if self.get_param("require_bullish_market"):
            market_bullish = ctx.get("market_bullish", None)
            if market_bullish is False:
                return StrategySignal("HOLD", 0.0, "大盘偏弱")

        # === 基础涨幅过滤 ===
        close = df["close"].astype(float)
        current = float(close.iloc[i])
        prev = float(close.iloc[i - 1])
        if prev <= 0:
            return StrategySignal("HOLD", 0.0, "前日收盘价异常")

        change_pct = (current - prev) / prev * 100

        max_chg = self.get_param("max_change_pct")
        min_chg = self.get_param("min_change_pct")
        if change_pct > max_chg:
            return StrategySignal(
                "HOLD", 0.0, f"涨幅{change_pct:.1f}%>{max_chg}%，超出蓄势区间"
            )
        if min_chg is not None and change_pct < min_chg:
            return StrategySignal(
                "HOLD", 0.0, f"涨幅{change_pct:.1f}%<{min_chg}%，跌幅过大"
            )

        # === RSI 过滤 ===
        rsi_max = self.get_param("rsi_max")
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = 100 - (100 / (1 + gain / loss_s))
        rsi_val = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50
        if rsi_val >= rsi_max:
            return StrategySignal("HOLD", 0.0, f"RSI {rsi_val:.0f}>={rsi_max}")

        # === 多维度评分 ===
        scores = self.scorer.total_score(df, i, ctx)
        total = scores["total"]
        threshold = self.get_param("score_threshold")

        if total < threshold:
            return StrategySignal(
                "HOLD",
                0.0,
                f"评分{total:.0f}<{threshold} (趋势{scores['trend']:.0f}/量价{scores['volume']:.0f}/位置{scores['position']:.0f}/市场{scores['market']:.0f})",
            )

        # === 生成买入信号 ===
        confidence = min(0.95, total / 100)
        return StrategySignal(
            "BUY",
            confidence,
            f"评分{total:.0f}>={threshold} (趋势{scores['trend']:.0f}/量价{scores['volume']:.0f}/位置{scores['position']:.0f}/市场{scores['market']:.0f})",
            metadata={
                "criterion": "v4_accumulation",
                "total_score": total,
                **scores,
                "rsi": rsi_val,
                "change_pct": change_pct,
            },
        )
