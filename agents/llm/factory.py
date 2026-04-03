"""
LLM 工厂 - 根据配置创建适配器
"""

import logging
from typing import Dict

from agents.llm.base import BaseLLMAdapter
from agents.llm.deepseek import DeepSeekAdapter
from app.config import settings

logger = logging.getLogger(__name__)

# 已注册的适配器类型
_ADAPTERS: Dict[str, type] = {
    "deepseek": DeepSeekAdapter,
}

# 单例缓存
_instances: Dict[str, BaseLLMAdapter] = {}


def get_llm(provider: str = "deepseek", **kwargs) -> BaseLLMAdapter:
    """获取 LLM 适配器实例（单例）"""
    if provider in _instances:
        return _instances[provider]

    adapter_cls = _ADAPTERS.get(provider)
    if adapter_cls is None:
        raise ValueError(
            f"Unknown LLM provider: {provider}. Available: {list(_ADAPTERS.keys())}"
        )

    instance = adapter_cls(**kwargs)
    _instances[provider] = instance
    logger.info(f"LLM adapter created: {provider}")
    return instance


def register_adapter(name: str, adapter_cls: type):
    """注册新的 LLM 适配器"""
    _ADAPTERS[name] = adapter_cls


def reset():
    """重置所有实例（用于测试）"""
    _instances.clear()


# 别名兼容
create_llm = get_llm
