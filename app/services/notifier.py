"""
推送通知服务 — 飞书 / 钉钉 webhook

调用方：scheduler 的 daily_push 任务
"""

import json
import logging
from typing import List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def _post_webhook(url: str, payload: dict, name: str) -> bool:
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            # 飞书：errcode = 0 OK；钉钉：errcode = 0 OK
            ok = data.get("code", data.get("StatusCode", 0)) == 0 or data.get("errcode", 0) == 0
            if not ok:
                logger.warning(f"{name} 推送返回异常: {data}")
            return ok
    except Exception as e:
        logger.error(f"{name} 推送失败: {e}")
        return False


async def send_feishu(text: str, title: str = "📊 量化每日推送") -> bool:
    """
    飞书机器人 — 富文本卡片消息
    """
    url = settings.FEISHU_WEBHOOK
    if not url:
        return False

    # 富文本卡片
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": text,
                    },
                }
            ],
        },
    }
    return await _post_webhook(url, payload, "飞书")


async def send_dingtalk(text: str, title: str = "📊 量化每日推送") -> bool:
    """钉钉机器人 — markdown 消息"""
    url = settings.DINGTALK_WEBHOOK
    if not url:
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    return await _post_webhook(url, payload, "钉钉")


async def send_to_all(text: str, title: str = "📊 量化每日推送") -> dict:
    """
    向所有已配置的渠道推送。
    Returns:
        {channel: success_bool}
    """
    return {
        "feishu": await send_feishu(text, title),
        "dingtalk": await send_dingtalk(text, title),
    }


# ───────── 业务封装 ─────────

def format_daily_brief(
    sector_recommendations: List[dict],
    t1_candidates: List[dict],
    market_emotion: Optional[dict] = None,
) -> str:
    """
    格式化每日早盘简报为飞书 lark_md 文本。
    """
    lines = []

    # 1. 市场情绪
    if market_emotion:
        score = market_emotion.get("score", 0)
        status = market_emotion.get("status", "")
        emoji = "🟢" if score >= 60 else "🟡" if score >= 40 else "🔴"
        lines.append(f"{emoji} **市场情绪**: {score:.1f} 分 — {status}")
        lines.append("")

    # 2. 板块推荐
    if sector_recommendations:
        lines.append("**🔥 今日热门板块 TOP 3**")
        for i, item in enumerate(sector_recommendations[:3], 1):
            sec = item.get("sector", {})
            name = sec.get("name", "")
            heat = sec.get("heat_score", 0)
            ret = sec.get("stats", {}).get("period_return_pct", 0)
            inflow = sec.get("stats", {}).get("net_inflow_bn", 0)
            leader = sec.get("leader_stock", "")
            lines.append(
                f"{i}. **{name}** 热度{heat:.0f} | 5日{ret:+.1f}% | 净流入{inflow:.1f}亿 | 龙头{leader}"
            )
            # LLM 解读
            an = item.get("analysis")
            if an:
                lines.append(f"   _催化_: {an.get('catalyst', '')}")
                lines.append(f"   _建议_: {an.get('pick_direction', '')}")
        lines.append("")

    # 3. T1 候选
    if t1_candidates:
        lines.append(f"**🎯 T1 隔夜候选 TOP {min(5, len(t1_candidates))}**")
        for i, c in enumerate(t1_candidates[:5], 1):
            name = c.get("stock_name", "")
            code = c.get("ts_code", "")
            score = c.get("score", 0)
            pct = c.get("suggested_pct")
            pct_str = f" | 建议仓位{pct*100:.0f}%" if pct else ""
            lines.append(f"{i}. **{name}** ({code}) 综合分{score:.1f}{pct_str}")

    if not lines:
        return "今日暂无数据"
    return "\n".join(lines)
