#!/usr/bin/env python3
"""因子重排 A/B 测试：daban 风格 use_factors False vs True（真实 DB 数据）"""
import asyncio
import sys
import os
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import select
from app.core.database import async_session
from app.models.pg_models import DailyBar, Stock
from engine.styles.daban import DabanStyle
from engine.styles.style_backtester import StyleBacktester

START, END = "2026-02-11", "2026-04-24"


async def load():
    async with async_session() as db:
        r = await db.execute(
            select(DailyBar).where(DailyBar.trade_date >= date.fromisoformat(START))
            .where(DailyBar.trade_date <= date.fromisoformat(END))
            .order_by(DailyBar.ts_code, DailyBar.trade_date))
        bars = r.scalars().all()
        by = defaultdict(list)
        for b in bars:
            by[b.ts_code].append({
                "date": str(b.trade_date).replace("-", ""),
                "open": float(b.open or 0), "high": float(b.high or 0),
                "low": float(b.low or 0), "close": float(b.close or 0),
                "volume": b.volume or 0, "amount": float(b.amount or 0),
                "turnover_rate": float(b.turnover_rate or 0)})
        data = {c: pd.DataFrame(v) for c, v in by.items()}
        r2 = await db.execute(select(Stock.ts_code, Stock.name, Stock.industry,
                                     Stock.list_date).where(Stock.is_active == True))
        info = {x.ts_code: {"name": x.name, "industry": x.industry,
                "list_date": str(x.list_date) if x.list_date else None}
                for x in r2.all()}
        r3 = await db.execute(select(DailyBar.trade_date)
            .where(DailyBar.trade_date >= date.fromisoformat(START))
            .where(DailyBar.trade_date <= date.fromisoformat(END))
            .group_by(DailyBar.trade_date).order_by(DailyBar.trade_date))
        dates = [str(x[0]).replace("-", "") for x in r3.all()]
    return data, info, dates


def run(data, info, dates, use_factors):
    st = DabanStyle(use_factors=use_factors)
    bt = StyleBacktester(style=st, initial_cash=100000)
    return bt.run(all_daily_data=data, stock_info=info,
                  trade_dates=dates, lookback=st.min_lookback)


async def main():
    data, info, dates = await load()
    for label, uf in [("无因子重排", False), ("有因子重排", True)]:
        r = run(data, info, dates, uf)
        es = r.event_study
        ev1 = es[0]["avg_ret_pct"] if es else 0
        print(f"[{label}] 交易{r.total_trades} 胜率{r.win_rate:.3f} "
              f"总收益{r.total_return_pct:.2f}% 期望{r.expectancy_pct:.2f}% "
              f"盈亏比{r.profit_factor} 最大回撤{r.max_drawdown_pct:.2f}% "
              f"保守{r.expected_live_return_pct:.2f}% T+1事件{ev1:+.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
