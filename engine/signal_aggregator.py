"""
信号聚合器 - 多策略信号合并 + 共振检测
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry

logger = logging.getLogger(__name__)


class SignalAggregator:
    """多策略信号聚合器"""

    def __init__(self, strategies: Optional[List[BaseStrategy]] = None):
        if strategies:
            self.strategies = strategies
        else:
            # 从注册表加载所有策略（排除T1隔夜策略，防止污染通用推荐）
            self.strategies = [
                cls()
                for cls in StrategyRegistry.all().values()
                if getattr(cls, "category", "") != "t1_overnight"
            ]

    def aggregate(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Dict:
        """运行所有策略并聚合信号"""
        signals: List[Dict] = []
        buy_count = 0
        sell_count = 0
        total_confidence = 0.0

        for strategy in self.strategies:
            try:
                sig = strategy.signal(df, context)
                signals.append(
                    {
                        "strategy": strategy.name,
                        "category": strategy.category,
                        "action": sig.action,
                        "confidence": sig.confidence,
                        "reason": sig.reason,
                    }
                )
                if sig.action == "BUY":
                    buy_count += 1
                    total_confidence += sig.confidence
                elif sig.action == "SELL":
                    sell_count += 1
                    total_confidence -= sig.confidence
            except Exception as e:
                logger.warning(f"Strategy {strategy.name} failed: {e}")

        total = len(signals)
        resonance = self._detect_resonance(signals)

        # 综合评分: [-1, 1]
        if total > 0:
            score = total_confidence / total
        else:
            score = 0.0

        # 综合决策
        if buy_count >= 3 and buy_count > sell_count * 2:
            action = "BUY"
        elif sell_count >= 3 and sell_count > buy_count * 2:
            action = "SELL"
        else:
            action = "HOLD"

        return {
            "action": action,
            "score": round(score, 3),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": total - buy_count - sell_count,
            "total_strategies": total,
            "resonance": resonance,
            "signals": signals,
        }

    def _detect_resonance(self, signals: List[Dict]) -> Dict:
        """检测多策略共振"""
        buy_strategies = [s["strategy"] for s in signals if s["action"] == "BUY"]
        sell_strategies = [s["strategy"] for s in signals if s["action"] == "SELL"]

        # 跨类别共振检测
        buy_categories = set(s["category"] for s in signals if s["action"] == "BUY")
        sell_categories = set(s["category"] for s in signals if s["action"] == "SELL")

        return {
            "buy_resonance": len(buy_categories) >= 2,
            "sell_resonance": len(sell_categories) >= 2,
            "buy_strategies": buy_strategies,
            "sell_strategies": sell_strategies,
            "buy_categories": list(buy_categories),
            "sell_categories": list(sell_categories),
        }
