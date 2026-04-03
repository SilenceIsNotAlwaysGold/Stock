"""
策略引擎基类 - 参数管理 + 信号标准化
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

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

    # 子类覆盖此字典定义默认参数
    default_params: Dict[str, Any] = {}

    def __init__(self, **overrides):
        self.params: Dict[str, Any] = {**self.default_params, **overrides}

    def get_param(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def update_params(self, **kwargs):
        self.params.update(kwargs)

    @abstractmethod
    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        """分析数据并返回标准化信号"""
        pass
