"""
策略注册表 - 自动发现和注册策略
"""

import importlib
import pkgutil
import logging
from typing import Dict, Type

from engine.base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """策略注册表"""

    _strategies: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, strategy_cls: Type[BaseStrategy]):
        cls._strategies[strategy_cls.name] = strategy_cls
        logger.info(f"Strategy registered: {strategy_cls.name}")
        return strategy_cls

    @classmethod
    def get(cls, name: str) -> Type[BaseStrategy] | None:
        return cls._strategies.get(name)

    @classmethod
    def all(cls) -> Dict[str, Type[BaseStrategy]]:
        return dict(cls._strategies)

    @classmethod
    def auto_discover(cls):
        """自动发现 engine/strategies/ 下的策略"""
        import engine.strategies as pkg

        for importer, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
            module = importlib.import_module(f"engine.strategies.{modname}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                    and attr.name
                ):
                    cls.register(attr)
