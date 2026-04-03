"""
空头研究员 - 基于分析报告构建空头论点
"""

import logging
from typing import Dict

from agents.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)

BEAR_PROMPT = """你是一位谨慎的空头研究员。基于以下分析师报告，请构建尽可能强有力的空头论点。

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
1. 从所有报告中提取不利于做多的证据和风险因素
2. 构建逻辑严密的空头论点（至少3个核心风险）
3. 给出止损价位建议
4. 评估下跌风险（0-100%）

请用中文输出结构化的空头研究报告。
"""


class BearResearcher:
    name = "bear_researcher"

    def __init__(self, llm: BaseLLMAdapter):
        self.llm = llm

    async def research(self, reports: Dict[str, str]) -> str:
        prompt = BEAR_PROMPT.format(
            market_report=reports.get("market_report", "暂无"),
            fundamental_report=reports.get("fundamental_report", "暂无"),
            news_report=reports.get("news_report", "暂无"),
            sentiment_report=reports.get("sentiment_report", "暂无"),
        )
        messages = [
            {"role": "system", "content": "你是谨慎的空头研究员，擅长发现风险。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.4)
