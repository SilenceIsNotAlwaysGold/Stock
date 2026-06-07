"""多交易风格 API：列出风格 + 按风格回测"""

import logging
from collections import defaultdict
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.pg_models import DailyBar, Stock
from engine.styles import get_style, list_styles
from engine.styles.style_backtester import StyleBacktester

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/list")
async def styles_list():
    """列出所有交易风格"""
    return {"styles": list_styles()}


@router.post("/{style_key}/backtest")
async def style_backtest(
    style_key: str,
    start_date: str = Query("2025-10-01"),
    end_date: str = Query("2026-04-14"),
    initial_cash: float = Query(100000.0),
    db: AsyncSession = Depends(get_db),
):
    """
    按指定风格做成交现实化回测。

    风格：short_t1(短线隔夜) / daban(打板) / swing(波段) / long(长线)
    口径与阶段1 一致：无未来函数 + 涨跌停不成交 + 印花税/滑点 + 持仓顺延。
    """
    style = get_style(style_key)
    if style is None:
        return {"error": f"未知风格 '{style_key}'，可选：{[s['key'] for s in list_styles()]}"}

    result = await db.execute(
        select(DailyBar)
        .where(DailyBar.trade_date >= date.fromisoformat(start_date))
        .where(DailyBar.trade_date <= date.fromisoformat(end_date))
        .order_by(DailyBar.ts_code, DailyBar.trade_date)
    )
    all_bars = result.scalars().all()
    if not all_bars:
        return {"error": "无日线数据，请先 /api/t1/sync-data 同步"}

    bars_by_code = defaultdict(list)
    for b in all_bars:
        bars_by_code[b.ts_code].append({
            "date": str(b.trade_date).replace("-", ""),
            "open": float(b.open or 0), "high": float(b.high or 0),
            "low": float(b.low or 0), "close": float(b.close or 0),
            "volume": b.volume or 0, "amount": float(b.amount or 0),
            "turnover_rate": float(b.turnover_rate or 0),
        })
    all_daily_data = {c: pd.DataFrame(r) for c, r in bars_by_code.items()}

    stocks_result = await db.execute(
        select(Stock.ts_code, Stock.name, Stock.industry, Stock.list_date)
        .where(Stock.is_active == True)
    )
    stock_info = {
        r.ts_code: {"name": r.name, "industry": r.industry,
                    "list_date": str(r.list_date) if r.list_date else None}
        for r in stocks_result.all()
    }

    dates_result = await db.execute(
        select(DailyBar.trade_date)
        .where(DailyBar.trade_date >= date.fromisoformat(start_date))
        .where(DailyBar.trade_date <= date.fromisoformat(end_date))
        .group_by(DailyBar.trade_date).order_by(DailyBar.trade_date)
    )
    trade_dates = [str(r[0]).replace("-", "") for r in dates_result.all()]

    # 回看窗口由风格自身声明（StyleBacktester 内部 max(lookback, style.min_lookback)）
    bt = StyleBacktester(style=style, initial_cash=initial_cash)
    r = bt.run(all_daily_data=all_daily_data, stock_info=stock_info,
               trade_dates=trade_dates, lookback=style.min_lookback)

    return {
        "style": {"key": style.key, "name": style.name, "desc": style.desc,
                  "target_hold_days": style.target_hold_days},
        "period": f"{start_date} ~ {end_date}",
        "initial_cash": r.initial_cash, "final_cash": r.final_cash,
        "total_return_pct": r.total_return_pct,
        "annual_return_pct": r.annual_return_pct,
        "max_drawdown_pct": r.max_drawdown_pct,
        "sharpe_ratio": r.sharpe_ratio, "sortino_ratio": r.sortino_ratio,
        "profit_factor": r.profit_factor, "expectancy_pct": r.expectancy_pct,
        "total_trades": r.total_trades, "win_count": r.win_count,
        "loss_count": r.loss_count, "win_rate": r.win_rate,
        "avg_win_pct": r.avg_win_pct, "avg_loss_pct": r.avg_loss_pct,
        "avg_pnl_pct": r.avg_pnl_pct, "avg_holding_days": r.avg_holding_days,
        "annual_turnover": r.annual_turnover, "cost_drag_pct": r.cost_drag_pct,
        "score_ic": r.score_ic, "score_icir": r.score_icir,
        "stuck_events": r.stuck_events, "trading_days": r.trading_days,
        "no_trade_days": r.no_trade_days, "live_decay": r.live_decay,
        "expected_live_return_pct": r.expected_live_return_pct,
        "event_study": r.event_study, "realism_notes": r.realism_notes,
        "monthly_returns": r.monthly_returns,
        "emotion_gated": style.emotion_gated,
        "emotion_series": r.emotion_series,
        "recent_trades": [
            {"buy_date": t.buy_date, "sell_date": t.sell_date,
             "ts_code": t.ts_code, "stock_name": t.stock_name,
             "buy_price": t.buy_price, "sell_price": t.sell_price,
             "pnl_pct": t.pnl_pct, "gross_pnl_pct": t.gross_pnl_pct,
             "cost_pct": t.cost_pct, "hold_days": t.hold_days,
             "sell_reason": t.sell_reason, "score": t.score, "is_win": t.is_win}
            for t in r.trades[-30:]
        ],
        "equity_curve": r.equity_curve[::max(1, len(r.equity_curve) // 120)],
    }
