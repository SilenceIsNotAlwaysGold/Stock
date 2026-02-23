"""
LLM 适配器基类
"""

from abc import ABC, abstractmethod
from typing import List, Dict


class BaseLLMAdapter(ABC):
    """LLM 适配器基类 - 统一接口"""

    @abstractmethod
    async def chat(self, messages: List[Dict], **kwargs) -> str:
        """发送对话请求，返回回复文本"""
        pass

    @abstractmethod
    async def chat_stream(self, messages: List[Dict], **kwargs):
        """流式对话"""
        pass
