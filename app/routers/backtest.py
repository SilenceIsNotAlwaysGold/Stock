"""回测系统"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import settings
from dataflows.source_manager import DataSourceManager
from dataflows.providers import TushareProvider, AKShareProvider, BaoStockProvider
from engine.base import BaseStrategy
from engine.registry import StrategyRegistry

logger = logging.getLogger(__name__)
router = APIRouter()


class BacktestRequest(BaseModel):
    stock_code: str
    strategy_name: str = ""
    start_date: str = ""
    end_date: str = ""
    initial_cash: float = 100000.0


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    """运行回测"""
    dm = DataSourceManager()
    if settings.TUSHARE_TOKEN and settings.TUSHARE_ENABLED:
        dm.register_provider("tushare", TushareProvider())
    dm.register_provider("akshare", AKShareProvider())
    dm.register_provider("baostock", BaoStockProvider())

    if not req.end_date:
        req.end_date = datetime.now().strftime("%Y-%m-%d")
    if not req.start_date:
        req.start_date = "2024-01-01"

    df = await dm.get_daily_bars(req.stock_code, req.start_date, req.end_date)

    StrategyRegistry.auto_discover()
    strategies = StrategyRegistry.all()

    if req.strategy_name and req.strategy_name in strategies:
        strat_list = [strategies[req.strategy_name]()]
    else:
        strat_list = [cls() for cls in strategies.values()]

    results = []
    for strat in strat_list:
        result = _run_single_backtest(strat, df, req.initial_cash)
        result["strategy"] = strat.name
        results.append(result)

    return {
        "stock_code": req.stock_code,
        "period": f"{req.start_date} ~ {req.end_date}",
        "initial_cash": req.initial_cash,
        "results": results,
    }


def _run_single_backtest(
    strategy: BaseStrategy, df: pd.DataFrame, initial_cash: float
) -> Dict:
    """单策略回测"""
    cash = initial_cash
    position = 0
    trades = []
    equity_curve = []

    window = max(30, len(df) // 10)

    for i in range(window, len(df)):
        slice_df = df.iloc[i - window : i + 1].copy()
        price = float(df.iloc[i]["close"])
        date_str = str(df.iloc[i]["date"])[:10]

        try:
            sig = strategy.signal(slice_df)
        except Exception:
            sig = None

        if sig and sig.action == "BUY" and position == 0 and cash > price * 100:
            shares = int(cash // (price * 100)) * 100
            cost = shares * price
            cash -= cost
            position = shares
            trades.append(
                {
                    "date": date_str,
                    "action": "BUY",
                    "price": price,
                    "shares": shares,
                }
            )
        elif sig and sig.action == "SELL" and position > 0:
            revenue = position * price
            cash += revenue
            trades.append(
                {
                    "date": date_str,
                    "action": "SELL",
                    "price": price,
                    "shares": position,
                }
            )
            position = 0

        total = cash + position * price
        equity_curve.append({"date": date_str, "equity": round(total, 2)})

    # 强制平仓
    if position > 0:
        final_price = float(df.iloc[-1]["close"])
        cash += position * final_price
        position = 0

    final_equity = cash
    total_return = (final_equity - initial_cash) / initial_cash
    trading_days = len(df)
    annual_return = total_return * (252 / max(trading_days, 1))

    # 最大回撤
    max_dd = 0.0
    peak = initial_cash
    for pt in equity_curve:
        if pt["equity"] > peak:
            peak = pt["equity"]
        dd = (peak - pt["equity"]) / peak
        max_dd = max(max_dd, dd)

    # 胜率
    wins = sum(
        1
        for i in range(0, len(trades) - 1, 2)
        if i + 1 < len(trades) and trades[i + 1]["price"] > trades[i]["price"]
    )
    total_trades = len(trades) // 2

    return {
        "final_equity": round(final_equity, 2),
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "total_trades": total_trades,
        "win_rate": round(wins / max(total_trades, 1) * 100, 2),
        "trades": trades[-20:],
        "equity_curve": equity_curve[:: max(1, len(equity_curve) // 100)],
    }


@router.get("/strategies")
async def list_strategies():
    """列出可用策略"""
    StrategyRegistry.auto_discover()
    return [
        {
            "name": cls.name,
            "description": cls.description,
            "category": cls.category,
            "params": cls.default_params,
        }
        for cls in StrategyRegistry.all().values()
    ]
