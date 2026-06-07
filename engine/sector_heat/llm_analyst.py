"""
LLM 分析层 — 调用 DeepSeek 对已评分的 Top 板块做基本面+消息面解读。

输入：板块量化数据 + 真实财联社电报
输出：催化剂 / 所处阶段 / 选股方向 / 风险提示 / 一句话总结

LLM 不参与选股决策，只负责解读"为什么"。
"""

import json
import logging
import re
from typing import Dict, List

from agents.llm.factory import get_llm
from engine.sector_heat.models import LLMAnalysis, SectorScore
from engine.sector_heat.news_fetcher import fetch_telegraph_news, filter_news_by_keywords

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一位专注A股市场的资深行业研究员，擅长结合政策面、产业动态和量化数据识别热点板块机会。
分析时要接地气、有观点，避免套话。请严格按照用户要求的JSON格式返回，不要有多余文字。
你看到的新闻是真实的最新财联社电报，请基于这些事实进行分析，不要编造。"""

_USER_TEMPLATE = """以下是今日A股各概念板块的量化热度数据（统计周期：{window_days}个交易日）。

【板块量化数据】
{sector_table}

【近 24 小时财联社电报（按板块筛选后）】
{news_section}

请针对以上每个板块，**优先依据其下方匹配的新闻**结合量化数据，给出以下分析（JSON格式）：

{{
  "sectors": [
    {{
      "name": "板块名称（与输入完全一致）",
      "catalyst": "核心催化剂——必须基于上面的真实新闻，引用具体事件/政策，50字以内",
      "stage": "当前所处阶段，从以下四选一：启动期 / 加速期 / 高位震荡 / 退潮期",
      "pick_direction": "选股方向建议，例如：优先龙头/关注细分赛道XX/寻找低位补涨，50字以内",
      "risks": "主要风险，30字以内",
      "summary": "一句话核心观点，20字以内，有倾向性"
    }}
  ]
}}

只返回JSON，不要任何额外文字。如某个板块没有匹配到新闻，catalyst 写"无明显消息面催化，纯资金推动"。"""


# ────── 板块名 → 关键词扩展 ──────

# 同义词/相关词典：将板块名扩展为多个搜索关键词
_SECTOR_KEYWORDS_EXPAND = {
    "盐湖提锂": ["盐湖", "提锂", "锂矿", "锂电", "碳酸锂"],
    "化肥": ["化肥", "尿素", "复合肥", "钾肥", "磷肥"],
    "化工": ["化工", "聚酯", "PTA", "丙烯"],
    "氟化工": ["氟化工", "氟化氢", "PVDF", "含氟"],
    "PVDF概念": ["PVDF", "氟聚合物", "锂电粘结剂"],
    "光伏": ["光伏", "硅料", "组件", "电池片"],
    "新能源车": ["新能源车", "电动车", "动力电池", "充电桩"],
    "半导体": ["半导体", "芯片", "晶圆", "光刻"],
    "AI算力": ["AI", "算力", "GPU", "大模型", "英伟达"],
    "光模块": ["光模块", "光通信", "数据中心", "800G", "1.6T"],
    "军工": ["军工", "国防", "航空", "导弹"],
    "白酒": ["白酒", "茅台", "五粮液", "酒企"],
    "医药": ["医药", "药品", "创新药", "CXO"],
    "房地产": ["地产", "房产", "楼市", "保交楼"],
    "银行": ["银行", "信贷", "货币政策", "降息"],
    "煤炭": ["煤炭", "动力煤", "焦煤"],
    "钢铁": ["钢铁", "钢材", "铁矿石"],
    "有色金属": ["有色", "铜", "铝", "铅锌"],
    "黄金": ["黄金", "金价", "贵金属"],
    "石油石化": ["石油", "原油", "OPEC", "炼化"],
}


def _expand_keywords(sector_name: str) -> List[str]:
    """板块名扩展为关键词列表"""
    # 基础：板块名本身
    keywords = [sector_name]
    # 查表扩展
    for k, v in _SECTOR_KEYWORDS_EXPAND.items():
        if k in sector_name or sector_name in k:
            keywords.extend(v)
    # 去重
    return list(set(keywords))


def _build_sector_table(sectors: List[SectorScore], window_days: int) -> str:
    lines = [
        f"{'板块':<14} {'热度':>5} {'{w}日涨幅':>8} {'今日涨幅':>8} {'净流入(亿)':>10} "
        f"{'上涨比':>7} {'换手率':>7} {'趋势':>8} {'领涨股':>10}".format(w=window_days)
    ]
    lines.append("-" * 90)
    for s in sectors:
        lines.append(
            f"{s.name:<14} {s.heat_score:>5.1f} {s.period_return:>+8.1f}% "
            f"{s.today_change:>+7.1f}% {s.net_inflow:>10.1f} "
            f"{s.up_ratio:>6.0%} {s.turnover_rate:>6.1f}% {s.trend:>8} {s.leader_stock:>10}"
        )
    return "\n".join(lines)


def _build_news_section(sectors: List[SectorScore], news_df) -> str:
    """为每个板块构建匹配新闻的展示段。未匹配则附上最新热门电报作为市场背景"""
    if news_df is None or news_df.empty:
        return "（暂无新闻数据）"

    sorted_df = news_df.sort_values("timestamp", ascending=False)
    market_recent = []
    for _, row in sorted_df.head(8).iterrows():
        t = str(row.get("timestamp", ""))[:16]
        market_recent.append(f"  • [{t}] {row.get('title', '')}")
    market_block = "## 【近期市场要闻】\n" + "\n".join(market_recent)

    blocks = [market_block]
    for s in sectors:
        keywords = _expand_keywords(s.name)
        matched = filter_news_by_keywords(news_df, keywords, max_items=5)
        if matched:
            lines = [f"## 【{s.name}】 关键词={','.join(keywords[:3])}"]
            for n in matched:
                t = n.get("pub_time", "")[:16]
                lines.append(f"  • [{t}] {n['title']}")
            blocks.append("\n".join(lines))
        else:
            blocks.append(
                f"## 【{s.name}】（未匹配到专项新闻，请参考上方近期市场要闻 + 量化数据推断）"
            )
    return "\n\n".join(blocks)


def _parse_llm_json(text: str) -> List[dict]:
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        data = json.loads(text)
        return data.get("sectors", [])
    except json.JSONDecodeError:
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
    批量分析 Top 板块。
    流程：拉财联社近 24h 电报 → 按板块关键词过滤 → 喂给 LLM → 解析结构化输出
    """
    if not sectors:
        return {}

    try:
        llm = get_llm()
    except Exception as e:
        logger.warning(f"LLM 初始化失败：{e}")
        return {}

    # 拉新闻
    news_df = await fetch_telegraph_news(hours=24)
    news_count = 0 if news_df is None else len(news_df)
    logger.info(f"LLM 分析：拉到 {news_count} 条财联社近 24h 电报")

    sector_table = _build_sector_table(sectors, window_days)
    news_section = _build_news_section(sectors, news_df)

    user_msg = _USER_TEMPLATE.format(
        window_days=window_days,
        sector_table=sector_table,
        news_section=news_section,
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
