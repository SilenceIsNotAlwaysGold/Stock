"""
消息面驱动推荐

财联社近 24h 电报 → 板块关键词命中(热度) → 受影响个股(行业/名称匹配)
→ 新闻热度 × 量化强度(近5日动量+换手) 排序 → 推荐。

让"最近的消息面"真正驱动选股，而非仅供 LLM 解读。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pg_models import DailyBar, Stock
from engine.sector_heat.llm_analyst import _SECTOR_KEYWORDS_EXPAND
from engine.sector_heat.news_fetcher import fetch_telegraph_news

logger = logging.getLogger(__name__)


async def recommend_by_news(db: AsyncSession, top_n: int = 15,
                            hours: int = 24) -> dict:
    news_df = await fetch_telegraph_news(hours=hours)
    if news_df is None or news_df.empty:
        return {"error": "暂无电报数据", "hot_sectors": [], "recommendations": []}

    texts = []
    for _, r in news_df.iterrows():
        texts.append((str(r.get("title", "")) + " " + str(r.get("content", "")),
                      str(r.get("title", ""))[:50]))

    # 1. 板块热度（关键词命中）
    hot = []
    for sector, kws in _SECTOR_KEYWORDS_EXPAND.items():
        all_kw = [sector] + kws
        hits, samples = 0, []
        for full, title in texts:
            if any(k in full for k in all_kw):
                hits += 1
                if len(samples) < 3 and title not in samples:
                    samples.append(title)
        if hits > 0:
            hot.append({"sector": sector, "hits": hits,
                        "keywords": all_kw[:4], "sample_news": samples})
    hot.sort(key=lambda x: -x["hits"])
    hot = hot[:8]
    if not hot:
        return {"generated_at": str(date.today()), "hot_sectors": [],
                "recommendations": [], "note": "近24h电报未命中已知板块关键词"}

    # 2. 受影响个股：行业含板块名 或 股名含关键词
    srows = await db.execute(
        select(Stock.ts_code, Stock.name, Stock.industry)
        .where(Stock.is_active == True)
    )
    stocks = srows.all()
    sector_rank = {h["sector"]: i for i, h in enumerate(hot)}
    sector_hits = {h["sector"]: h["hits"] for h in hot}

    matched = {}
    for s in stocks:
        nm = s.name or ""
        ind = s.industry or ""
        for h in hot:
            sec = h["sector"]
            kws = [sec] + _SECTOR_KEYWORDS_EXPAND.get(sec, [])
            if any(k in ind for k in kws) or any(k in nm for k in kws):
                # 取命中度最高(最热)的板块归属
                if s.ts_code not in matched or \
                   sector_rank[sec] < sector_rank[matched[s.ts_code]["sector"]]:
                    matched[s.ts_code] = {"ts_code": s.ts_code, "name": nm,
                                          "industry": ind, "sector": sec}
    if not matched:
        return {"generated_at": str(date.today()), "hot_sectors": hot,
                "recommendations": [], "note": "热门板块无可匹配在册个股"}

    # 3. 量化强度（取每只个股最近若干根，不锚定当天日历日，避免数据滞后导致空集）
    codes = list(matched.keys())
    brows = await db.execute(
        select(DailyBar.ts_code, DailyBar.trade_date, DailyBar.close,
               DailyBar.turnover_rate)
        .where(DailyBar.ts_code.in_(codes))
        .order_by(DailyBar.ts_code, DailyBar.trade_date)
    )
    series = {}
    for r in brows.all():
        series.setdefault(r.ts_code, []).append(
            (float(r.close or 0), float(r.turnover_rate or 0)))
    # 仅保留每只个股最近 12 根
    series = {c: v[-12:] for c, v in series.items()}

    recs: List[dict] = []
    for code, info in matched.items():
        bars = series.get(code, [])
        if len(bars) < 6:
            continue
        closes = [b[0] for b in bars]
        last, p5 = closes[-1], closes[-6]
        if p5 <= 0:
            continue
        ret5 = (last - p5) / p5
        chg1 = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
        turn = bars[-1][1]
        sec = info["sector"]
        # 新闻热度分（0-50）：板块命中数归一 + 排名加权
        news_score = min(50.0, sector_hits[sec] * 6 + (8 - sector_rank[sec]) * 2)
        # 量化强度（0-50）：5日动量 + 换手适中
        q = 25 + ret5 * 250
        if 3 <= turn <= 12:
            q += 12
        elif turn > 12:
            q += 4
        q = max(0.0, min(50.0, q))
        total = round(news_score + q, 1)
        recs.append({
            "ts_code": code, "name": info["name"], "industry": info["industry"],
            "sector": sec, "news_score": round(news_score, 1),
            "quant_score": round(q, 1), "total_score": total,
            "ret5_pct": round(ret5 * 100, 2), "today_chg_pct": round(chg1 * 100, 2),
            "turnover_rate": round(turn, 2),
            "reason": f"{sec}板块近24h电报命中{sector_hits[sec]}条；"
                      f"近5日{ret5*100:+.1f}% 换手{turn:.1f}%",
        })

    recs.sort(key=lambda x: -x["total_score"])
    return {
        "generated_at": str(date.today()),
        "news_count": len(texts),
        "hot_sectors": hot,
        "recommendations": recs[:top_n],
    }
