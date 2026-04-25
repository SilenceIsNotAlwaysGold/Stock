"""
LLM 分析层 — 调用 DeepSeek 对已评分的 Top 板块做基本面+消息面解读。

输入：板块量化数据
输出：催化剂 / 所处阶段 / 选股方向 / 风险提示 / 一句话总结

LLM 不参与选股决策，只负责解读"为什么"。
"""

import json
import logging
import re
from typing import Dict, List

from agents.llm.factory import get_llm
from engine.sector_heat.models import LLMAnalysis, SectorScore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一位专注A股市场的资深行业研究员，擅长结合政策面、产业动态和量化数据识别热点板块机会。
分析时要接地气、有观点，避免套话。请严格按照用户要求的JSON格式返回，不要有多余文字。"""

_USER_TEMPLATE = """以下是今日A股各概念板块的量化热度数据（统计周期：{window_days}个交易日）。

{sector_table}

请针对以上每个板块，结合你对近期市场环境、政策动向、产业进展的了解，给出以下分析（JSON格式）：

{{
  "sectors": [
    {{
      "name": "板块名称（与输入完全一致）",
      "catalyst": "核心催化剂——是什么消息/政策/事件在驱动这个板块，50字以内，要具体",
      "stage": "当前所处阶段，从以下四选一：启动期 / 加速期 / 高位震荡 / 退潮期",
      "pick_direction": "选股方向建议，例如：优先龙头/关注细分赛道XX/寻找低位补涨，50字以内",
      "risks": "主要风险，30字以内",
      "summary": "一句话核心观点，20字以内，有倾向性"
    }}
  ]
}}

只返回JSON，不要任何额外文字。"""


def _build_sector_table(sectors: List[SectorScore], window_days: int) -> str:
    lines = [
        f"{'板块':<12} {'热度':>5} {'{w}日涨幅':>8} {'今日涨幅':>8} {'净流入(亿)':>10} "
        f"{'上涨比':>7} {'换手率':>7} {'趋势':>5} {'领涨股':>8}".format(w=window_days)
    ]
    lines.append("-" * 80)
    for s in sectors:
        lines.append(
            f"{s.name:<12} {s.heat_score:>5.1f} {s.period_return:>+8.1f}% "
            f"{s.today_change:>+7.1f}% {s.net_inflow:>10.1f} "
            f"{s.up_ratio:>6.0%} {s.turnover_rate:>6.1f}% {s.trend:>5} {s.leader_stock:>8}"
        )
    return "\n".join(lines)


def _parse_llm_json(text: str) -> List[dict]:
    # 去掉可能的 markdown code block
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        data = json.loads(text)
        return data.get("sectors", [])
    except json.JSONDecodeError:
        # 尝试提取第一个 JSON 对象
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                return data.get("sectors", [])
            except Exception:
                pass
    logger.error(f"LLM JSON 解析失败，原始文本：{text[:300]}")
    return []


async def analyze_sectors(
    sectors: List[SectorScore],
    window_days: int,
) -> Dict[str, LLMAnalysis]:
    """
    批量分析 Top 板块，返回 {板块名: LLMAnalysis}。
    若 LLM 调用失败，返回空字典（不影响主流程）。
    """
    if not sectors:
        return {}

    try:
        llm = get_llm()
    except Exception as e:
        logger.warning(f"LLM 初始化失败（未配置 DEEPSEEK_API_KEY？）：{e}")
        return {}

    sector_table = _build_sector_table(sectors, window_days)
    user_msg = _USER_TEMPLATE.format(
        window_days=window_days,
        sector_table=sector_table,
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        response = await llm.chat(messages, temperature=0.5, max_tokens=2048)
    except Exception as e:
        logger.error(f"LLM 调用失败：{e}")
        return {}

    parsed = _parse_llm_json(response)
    result: Dict[str, LLMAnalysis] = {}
    name_set = {s.name for s in sectors}

    for item in parsed:
        name = item.get("name", "")
        if name not in name_set:
            continue
        result[name] = LLMAnalysis(
            sector_name=name,
            catalyst=item.get("catalyst", ""),
            stage=item.get("stage", ""),
            pick_direction=item.get("pick_direction", ""),
            risks=item.get("risks", ""),
            summary=item.get("summary", ""),
        )

    logger.info(f"LLM 分析完成：{list(result.keys())}")
    return result
