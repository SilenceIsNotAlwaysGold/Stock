"""
多头研究员 - 基于分析报告构建多头论点
"""

import logging
from typing import Dict, List

from agents.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)

BULL_PROMPT = """你是一位坚定的多头研究员。基于以下分析师报告，请构建尽可能强有力的多头论点。

## 分析师报告
### 技术面分析
{market_report}

### 基本面分析
{fundamental_report}

### 新闻面分析
{news_report}

### 市场情绪分析
{sentiment_report}

## 要求
1. 从所有报告中提取有利于做多的证据
2. 构建逻辑严密的多头论点（至少3个核心论点）
3. 给出目标价位和持有周期建议
4. 评估多头胜率（0-100%）

请用中文输出结构化的多头研究报告。
"""


class BullResearcher:
    name = "bull_researcher"

    def __init__(self, llm: BaseLLMAdapter):
        self.llm = llm

    async def research(self, reports: Dict[str, str]) -> str:
        prompt = BULL_PROMPT.format(
            market_report=reports.get("market_report", "暂无"),
            fundamental_report=reports.get("fundamental_report", "暂无"),
            news_report=reports.get("news_report", "暂无"),
            sentiment_report=reports.get("sentiment_report", "暂无"),
        )
        messages = [
            {"role": "system", "content": "你是坚定的多头研究员，擅长发现投资机会。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.4)
