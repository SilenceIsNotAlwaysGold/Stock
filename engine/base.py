"""
策略引擎基类 - 借鉴 v7 BaseStrategy 模式
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd


@dataclass
class StrategySignal:
    """标准化策略信号"""

    action: str  # BUY / SELL / HOLD
    confidence: float  # 0-1
    reason: str = ""
    metadata: Dict = field(default_factory=dict)


class BaseStrategy(ABC):
    """策略基类 - 所有策略继承此类"""

    name: str = ""
    description: str = ""
    category: str = ""  # trend / reversion / momentum / volume / breakout

    @abstractmethod
    def signal(self, df: pd.DataFrame, context: Dict = None) -> StrategySignal:
        """分析数据并返回标准化信号"""
        pass
