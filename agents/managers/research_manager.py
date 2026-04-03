"""
研究经理 - 综合多空论点做出判断
"""

import logging
from typing import Dict

from agents.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)

MANAGER_PROMPT = """你是一位资深的研究经理。请综合以下多空双方的研究报告，做出客观的投资判断。

## 多头论点
{bull_argument}

## 空头论点
{bear_argument}

## 要求
1. 客观评估多空双方论点的强度和逻辑性
2. 指出双方论点中的关键分歧
3. 给出你的综合判断（买入/卖出/持有）
4. 给出置信度（0-100%）
5. 给出目标价位和止损价位建议

请用中文输出结构化的研究结论。格式：
- 综合判断: [买入/卖出/持有]
- 置信度: [0-100]%
- 核心理由: [简要说明]
- 目标价位: [价格]
- 止损价位: [价格]
- 详细分析: [完整分析]
"""


class ResearchManager:
    name = "research_manager"

    def __init__(self, llm: BaseLLMAdapter):
        self.llm = llm

    async def conclude(self, bull_argument: str, bear_argument: str) -> str:
        prompt = MANAGER_PROMPT.format(
            bull_argument=bull_argument,
            bear_argument=bear_argument,
        )
        messages = [
            {"role": "system", "content": "你是客观公正的研究经理，擅长综合分析。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.3)
