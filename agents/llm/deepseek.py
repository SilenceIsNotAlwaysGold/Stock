"""
DeepSeek LLM 适配器 - 兼容 OpenAI 格式
"""

import logging
import time
from typing import List, Dict, AsyncIterator

from openai import AsyncOpenAI

from agents.llm.base import BaseLLMAdapter
from app.config import settings

logger = logging.getLogger(__name__)


class DeepSeekAdapter(BaseLLMAdapter):
    """DeepSeek API 适配器（兼容 OpenAI 格式）"""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        max_retries: int = 3,
        timeout: float = 120.0,
    ):
        self.api_key = api_key or settings.DEEPSEEK_API_KEY
        self.base_url = base_url or settings.DEEPSEEK_BASE_URL
        self.model = model or settings.DEEPSEEK_MODEL
        self.max_retries = max_retries
        self.timeout = timeout

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

        # Token usage tracking
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_requests = 0

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        """发送对话请求，返回回复文本"""
        start = time.time()
        try:
            response = await self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096),
            )

            # Track usage
            self.total_requests += 1
            if response.usage:
                self.total_prompt_tokens += response.usage.prompt_tokens
                self.total_completion_tokens += response.usage.completion_tokens

            elapsed = time.time() - start
            logger.info(
                f"DeepSeek chat completed in {elapsed:.2f}s "
                f"(tokens: {response.usage.prompt_tokens}+{response.usage.completion_tokens})"
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"DeepSeek chat failed after {elapsed:.2f}s: {e}")
            raise

    async def chat_stream(self, messages: List[Dict], **kwargs) -> AsyncIterator[str]:
        """流式对话"""
        try:
            stream = await self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096),
                stream=True,
            )

            self.total_requests += 1
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"DeepSeek stream failed: {e}")
            raise

    def get_usage_stats(self) -> Dict:
        """获取 Token 使用统计"""
        return {
            "total_requests": self.total_requests,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }
