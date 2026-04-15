"""
T1 v4 多策略共振检测模块

对 T1 候选股票运行其他量化策略，统计 BUY 信号数量。
多策略同时看好 → 加分提升排名，提高选股确定性。

共振加分规则:
  0-1 个策略 BUY → 不加分
  2 个策略 BUY   → +10 分
  3+ 个策略 BUY  → +15 分
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from engine.base import BaseStrategy
from engine.registry import StrategyRegistry

logger = logging.getLogger(__name__)


@dataclass
class ResonanceResult:
    """共振检测结果"""

    ts_code: str
    resonance_count: int = 0               # 共振策略数（发出 BUY 的策略数）
    resonance_bonus: float = 0.0           # 加分值
    resonating_strategies: List[str] = field(default_factory=list)
    details: Dict = field(default_factory=dict)


class ResonanceDetector:
    """
    多策略共振检测器

    使用 StrategyRegistry 获取所有非 T1 策略，
    对候选股票逐一运行，统计 BUY 信号以确定共振强度。
    """

    BONUS_MAP = {
        0: 0.0,
        1: 0.0,
        2: 10.0,
    }
    MAX_BONUS = 15.0  # 3 个及以上

    def __init__(self, strategies: Optional[List[BaseStrategy]] = None):
        if strategies is not None:
            self.strategies = strategies
        else:
            self.strategies = self._load_strategies()

    def _load_strategies(self) -> List[BaseStrategy]:
        """从注册表加载非 T1 策略。"""
        strategies = []
        for cls in StrategyRegistry.all().values():
            if getattr(cls, "category", "") == "t1_overnight":
                continue
            try:
                strategies.append(cls())
            except Exception as e:
                logger.warning(f"Failed to instantiate strategy {cls.name}: {e}")
        return strategies

    def detect(
        self,
        ts_code: str,
        daily_df: Optional[pd.DataFrame],
        context: Optional[Dict] = None,
    ) -> ResonanceResult:
        """
        对单只股票运行所有策略，统计 BUY 信号。

        Args:
            ts_code: 股票代码
            daily_df: 日线数据（至少 30 天）
            context: 额外上下文

        Returns:
            ResonanceResult
        """
        result = ResonanceResult(ts_code=ts_code)

        if daily_df is None or daily_df.empty or len(daily_df) < 10:
            return result

        buy_strategies = []
        all_signals = {}

        for strategy in self.strategies:
            try:
                sig = strategy.signal(daily_df, context)
                all_signals[strategy.name] = {
                    "action": sig.action,
                    "confidence": sig.confidence,
                    "category": strategy.category,
                }
                if sig.action == "BUY":
                    buy_strategies.append(strategy.name)
            except Exception as e:
                logger.debug(f"Strategy {strategy.name} skipped for {ts_code}: {e}")

        count = len(buy_strategies)
        bonus = self.BONUS_MAP.get(count, self.MAX_BONUS)

        result.resonance_count = count
        result.resonance_bonus = bonus
        result.resonating_strategies = buy_strategies
        result.details = all_signals

        if count >= 2:
            logger.info(
                f"Resonance detected for {ts_code}: "
                f"{count} strategies ({', '.join(buy_strategies)}), bonus +{bonus}"
            )

        return result

    def batch_detect(
        self,
        candidates: list,
        daily_data: Dict[str, pd.DataFrame],
        context: Optional[Dict] = None,
    ) -> Dict[str, ResonanceResult]:
        """
        批量共振检测。

        Args:
            candidates: 候选列表（需有 ts_code 属性/键）
            daily_data: ts_code → daily_df
            context: 共享上下文

        Returns:
            ts_code → ResonanceResult 的字典
        """
        results = {}
        for cand in candidates:
            ts_code = cand.ts_code if hasattr(cand, "ts_code") else cand.get("ts_code", "")
            df = daily_data.get(ts_code)
            results[ts_code] = self.detect(ts_code, df, context)
        return results
