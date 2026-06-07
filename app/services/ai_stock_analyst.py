"""
AI 个股分析（量化 + 消息面 + LLM 叙事，含规则兜底）

设计参考竞品 stock-scanner：显式权重打分 + LLM 不可用时规则兜底，
保证 DeepSeek 无余额/超时也能给出可用结论。

合成 0-100：技术面 40 / 资金面 25 / 消息面 25 / 趋势结构 10
输出结构化决策卡：评分 / 评级 / 买入区 / 止损 / 目标 / 催化剂 / 风险 / 叙事 / 新闻
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── 消息面规则词典（LLM 不可用时的兜底情感） ──
_POS = ["利好", "中标", "中标", "签约", "订单", "增长", "扭亏", "预增", "涨停", "突破",
        "合作", "获批", "提价", "回购", "增持", "新高", "放量", "龙头", "超预期",
        "投产", "量产", "并购", "重组利好", "高景气", "提速", "需求旺盛"]
_NEG = ["减持", "亏损", "下滑", "预减", "问询", "违规", "处罚", "跌停", "风险",
        "质押", "诉讼", "退市", "商誉减值", "解禁", "套现", "下调", "不及预期",
        "停产", "事故", "造假", "立案", "爆雷", "踩雷", "利空"]


def _safe(v, d=0.0):
    try:
        f = float(v)
        return f if f == f else d
    except Exception:
        return d


def _tech_score(df: pd.DataFrame) -> tuple:
    """技术面 0-40：均线多头 + 动量 + 量价 + 形态"""
    c = df["close"].astype(float)
    if len(c) < 21:
        return 20.0, "数据不足，技术面取中性"
    ma5, ma10, ma20 = c.tail(5).mean(), c.tail(10).mean(), c.tail(20).mean()
    last = float(c.iloc[-1])
    prev = float(c.iloc[-2])
    s, notes = 0.0, []
    # 均线多头排列 0-15
    if last > ma5 > ma10 > ma20:
        s += 15; notes.append("均线多头排列")
    elif last > ma20:
        s += 9; notes.append("站上20日线")
    else:
        s += 3; notes.append("均线空头")
    # 动量（5日涨幅）0-12
    r5 = (last - float(c.iloc[-6])) / float(c.iloc[-6]) if len(c) >= 6 and c.iloc[-6] > 0 else 0
    s += float(np.clip((r5 + 0.05) / 0.15 * 12, 0, 12))
    # 量价 0-8
    if "volume" in df.columns and len(df) >= 6:
        v = df["volume"].astype(float)
        vr = v.iloc[-1] / max(v.tail(5).mean(), 1)
        chg = (last - prev) / prev if prev > 0 else 0
        if chg > 0 and vr > 1.1:
            s += 8; notes.append("放量上涨")
        elif chg > 0:
            s += 5
        else:
            s += 2
    else:
        s += 4
    # 波动控制 0-5（ATR 适中）
    hl = (df["high"].astype(float) - df["low"].astype(float)).tail(10).mean()
    atr_pct = hl / last if last > 0 else 0.1
    s += 5 if 0.02 <= atr_pct <= 0.06 else (3 if atr_pct < 0.02 else 1)
    return round(min(s, 40.0), 1), "、".join(notes)


def _capital_score(df: pd.DataFrame) -> tuple:
    """资金面 0-25：换手 + 成交额趋势"""
    if len(df) < 6:
        return 12.5, "数据不足"
    s, notes = 0.0, []
    tr = _safe(df.iloc[-1].get("turnover_rate", 0))
    if 3 <= tr <= 12:
        s += 13; notes.append(f"换手{tr:.1f}%健康")
    elif tr > 12:
        s += 6; notes.append(f"换手{tr:.1f}%偏高")
    else:
        s += 7 if tr > 0 else 8
    amt = df["amount"].astype(float) if "amount" in df.columns else None
    if amt is not None and len(amt) >= 6:
        if amt.iloc[-1] > amt.tail(5).mean() * 1.1:
            s += 12; notes.append("成交额放大")
        elif amt.iloc[-1] > amt.tail(5).mean() * 0.8:
            s += 8
        else:
            s += 4; notes.append("成交萎缩")
    else:
        s += 6
    return round(min(s, 25.0), 1), "、".join(notes)


def news_sentiment(news: List[dict]) -> tuple:
    """消息面 0-25 + 极性 + 催化剂/风险列表（规则兜底）"""
    if not news:
        return 12.0, "中性", [], ["近期无明显消息面催化"]
    pos_hits, neg_hits = [], []
    for n in news[:15]:
        text = (n.get("title", "") + " " + n.get("content", ""))[:300]
        for kw in _POS:
            if kw in text:
                pos_hits.append((kw, n.get("title", "")[:40]))
        for kw in _NEG:
            if kw in text:
                neg_hits.append((kw, n.get("title", "")[:40]))
    net = len(pos_hits) - len(neg_hits)
    score = float(np.clip(12 + net * 2.2, 0, 25))
    if net >= 2:
        polarity = "偏多"
    elif net <= -2:
        polarity = "偏空"
    else:
        polarity = "中性"
    catalysts = list(dict.fromkeys(f"{t}（{k}）" for k, t in pos_hits))[:4]
    risks = list(dict.fromkeys(f"{t}（{k}）" for k, t in neg_hits))[:4]
    if not catalysts and polarity != "偏空":
        catalysts = [news[0].get("title", "")[:40]] if news else []
    if not risks:
        risks = ["注意大盘系统性风险与个股流动性"]
    return round(score, 1), polarity, catalysts, risks


def _trend_struct(df: pd.DataFrame) -> tuple:
    """趋势结构 0-10：20日斜率"""
    c = df["close"].astype(float)
    if len(c) < 21:
        return 5.0
    ma20_now = c.tail(20).mean()
    ma20_old = c.iloc[-25:-5].mean() if len(c) >= 25 else ma20_now
    slope = (ma20_now - ma20_old) / ma20_old if ma20_old > 0 else 0
    return round(float(np.clip(5 + slope * 100, 0, 10)), 1)


def _zones(df: pd.DataFrame) -> dict:
    """买入区 / 止损 / 目标（基于近 20 日结构 + ATR）"""
    c = df["close"].astype(float)
    last = float(c.iloc[-1])
    hl = (df["high"].astype(float) - df["low"].astype(float)).tail(14).mean()
    atr = hl if hl > 0 else last * 0.03
    low20 = float(df["low"].astype(float).tail(20).min())
    return {
        "current": round(last, 2),
        "buy_zone": [round(max(last - atr, low20), 2), round(last + atr * 0.3, 2)],
        "stop_loss": round(min(last - atr * 2.0, low20 * 0.98), 2),
        "target": round(last + atr * 3.0, 2),
    }


def rule_narrative(name, score, rating, tech_n, cap_n, pol, catalysts, risks) -> str:
    return (f"{name} 综合评分 {score:.0f}（{rating}）。技术面：{tech_n or '中性'}；"
            f"资金面：{cap_n or '一般'}；消息面{pol}。"
            f"{'催化：' + '；'.join(catalysts[:2]) if catalysts else '暂无明确催化'}。"
            f"主要风险：{risks[0] if risks else '系统性风险'}。"
            f"（规则引擎生成，未启用 LLM）")


async def analyze(ts_code: str, name: str, df: pd.DataFrame,
                  news: List[dict], llm=None) -> dict:
    """主入口：组装决策卡。llm 为 None 或调用失败则规则兜底。"""
    if df is None or len(df) < 6:
        return {"error": "日线数据不足", "ts_code": ts_code}

    tech, tech_n = _tech_score(df)
    cap, cap_n = _capital_score(df)
    news_s, polarity, catalysts, risks = news_sentiment(news)
    trend = _trend_struct(df)
    total = round(tech + cap + news_s + trend, 1)

    if total >= 78:
        rating, action = "强烈推荐", "BUY"
    elif total >= 62:
        rating, action = "推荐", "BUY"
    elif total >= 45:
        rating, action = "中性", "HOLD"
    else:
        rating, action = "回避", "AVOID"

    zones = _zones(df)

    narrative = None
    llm_used = False
    if llm is not None:
        try:
            news_brief = "；".join(n.get("title", "")[:40] for n in (news or [])[:6])
            msg = [
                {"role": "system", "content": "你是A股资深分析师，基于给定量化与真实新闻给出50-120字客观点评，有观点不套话，不编造。"},
                {"role": "user", "content":
                    f"股票:{name}({ts_code}) 综合{total}分({rating}) "
                    f"技术{tech}/40({tech_n}) 资金{cap}/25({cap_n}) "
                    f"消息面{news_s}/25({polarity}) 趋势{trend}/10。"
                    f"近期新闻:{news_brief or '无'}。给出操作点评。"},
            ]
            narrative = (await llm.chat(msg, temperature=0.6, max_tokens=300)).strip()
            llm_used = bool(narrative)
        except Exception as e:
            logger.warning(f"AI分析 LLM 调用失败，转规则兜底: {e}")
    if not narrative:
        narrative = rule_narrative(name, total, rating, tech_n, cap_n,
                                   polarity, catalysts, risks)

    return {
        "ts_code": ts_code, "name": name,
        "score": total, "rating": rating, "action": action,
        "breakdown": {"technical": tech, "capital": cap,
                      "news": news_s, "trend": trend},
        "breakdown_max": {"technical": 40, "capital": 25, "news": 25, "trend": 10},
        "news_polarity": polarity,
        "catalysts": catalysts, "risks": risks,
        "price_zones": zones,
        "narrative": narrative, "llm_used": llm_used,
        "news": [{"title": n.get("title", ""), "pub_time": n.get("pub_time", ""),
                  "content": (n.get("content", "") or "")[:160]}
                 for n in (news or [])[:8]],
    }
