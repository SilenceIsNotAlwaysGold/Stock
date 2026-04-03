"""
风控 Agent - 三种风格 + 风控经理
"""

import logging
from typing import Dict

from agents.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)

RISK_PROMPT = """你是一位{style}风格的风控分析师。请基于以下研究结论进行风险评估。

## 研究结论
{research_conclusion}

## 多头论点摘要
{bull_summary}

## 空头论点摘要
{bear_summary}

## 风控要求（{style}风格）
{style_instruction}

请用中文输出风险评估报告，包含：
- 风险等级: [低/中/高/极高]
- 建议仓位: [0-100]%
- 核心风险点: [列举]
- 风控建议: [具体措施]
"""

STYLE_INSTRUCTIONS = {
    "aggressive": "你倾向于承担更多风险以获取更高收益。只要基本面没有重大问题，你愿意给出较高仓位建议。关注上行空间。",
    "conservative": "你极度厌恶风险，宁可错过机会也不愿承受损失。任何不确定性都应该降低仓位。关注下行风险。",
    "neutral": "你追求风险和收益的平衡。根据胜率和赔率综合判断，给出合理的仓位建议。",
}


class RiskAgent:
    """风控 Agent 基类"""

    def __init__(self, llm: BaseLLMAdapter, style: str):
        self.llm = llm
        self.style = style
        self.name = f"risk_{style}"

    async def assess(
        self,
        research_conclusion: str,
        bull_summary: str,
        bear_summary: str,
    ) -> str:
        prompt = RISK_PROMPT.format(
            style=self.style,
            research_conclusion=research_conclusion,
            bull_summary=bull_summary,
            bear_summary=bear_summary,
            style_instruction=STYLE_INSTRUCTIONS[self.style],
        )
        messages = [
            {"role": "system", "content": f"你是{self.style}风格的风控分析师。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.3)


RISK_MANAGER_PROMPT = """你是首席风控官。请综合以下三位风控分析师的评估，做出最终风控裁决。

## 激进派评估
{aggressive}

## 保守派评估
{conservative}

## 中性派评估
{neutral}

## 要求
给出最终裁决，包含：
- 最终风险等级: [低/中/高/极高]
- 建议仓位: [0-100]%
- 止损价位建议
- 最终风控意见（2-3句话）
"""


class RiskManager:
    name = "risk_manager"

    def __init__(self, llm: BaseLLMAdapter):
        self.llm = llm
        self.agents = {
            style: RiskAgent(llm, style)
            for style in ["aggressive", "conservative", "neutral"]
        }

    async def full_assessment(
        self,
        research_conclusion: str,
        bull_summary: str,
        bear_summary: str,
    ) -> Dict[str, str]:
        """运行三个风控 Agent 并综合裁决"""
        assessments = {}
        for style, agent in self.agents.items():
            assessments[style] = await agent.assess(
                research_conclusion, bull_summary, bear_summary
            )

        # 综合裁决
        verdict = await self._final_verdict(assessments)
        assessments["final_verdict"] = verdict
        return assessments

    async def _final_verdict(self, assessments: Dict[str, str]) -> str:
        prompt = RISK_MANAGER_PROMPT.format(
            aggressive=assessments.get("aggressive", ""),
            conservative=assessments.get("conservative", ""),
            neutral=assessments.get("neutral", ""),
        )
        messages = [
            {"role": "system", "content": "你是首席风控官，做出最终裁决。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.2)
