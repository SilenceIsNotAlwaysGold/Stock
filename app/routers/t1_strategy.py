"""T+1 隔夜策略 API 路由"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, desc, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import T1StrategyError
from app.models.pg_models import T1Candidate, T1Position, T1Trade, T1CriteriaStats, Stock, DailyBar
from app.models.schemas import T1BuyRequest
from app.services import t1_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/candidates")
async def list_candidates(
    scan_date: Optional[str] = None,
    criterion: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """今日候选股列表"""
    target_date = date.fromisoformat(scan_date) if scan_date else date.today()
    query = select(T1Candidate).where(T1Candidate.scan_date == target_date)
    if criterion:
        query = query.where(T1Candidate.criterion == criterion)
    query = query.order_by(desc(T1Candidate.score))

    result = await db.execute(query)
    candidates = result.scalars().all()
    return {
        "scan_date": str(target_date),
        "total": len(candidates),
        "items": [
            {
                "id": c.id,
                "scan_date": str(c.scan_date),
                "ts_code": c.ts_code,
                "stock_name": c.stock_name,
                "criterion": c.criterion,
                "score": c.score,
                "tech_score": c.tech_score,
                "capital_score": c.capital_score,
                "fundamental_score": c.fundamental_score,
                "sector_score": c.sector_score,
                "market_score": c.market_score,
                "score_details": c.score_details,
                "close_price": float(c.close_price) if c.close_price else None,
                "change_pct": c.change_pct,
                "volume_ratio": c.volume_ratio,
                "turnover_rate": c.turnover_rate,
                "status": c.status,
                "reason": c.reason or "",
            }
            for c in candidates
        ],
    }


@router.post("/scan")
async def trigger_scan(
    scan_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """手动触发扫描"""
    import uuid

    target_date = date.fromisoformat(scan_date) if scan_date else date.today()
    task_id = f"t1_scan_{uuid.uuid4().hex[:8]}"
    candidates = await t1_service.scan_candidates(db, target_date, task_id=task_id)
    return {
        "task_id": task_id,
        "scan_date": str(target_date),
        "found": len(candidates),
        "candidates": candidates,
    }


@router.post("/buy")
async def buy_candidate(
    req: T1BuyRequest,
    db: AsyncSession = Depends(get_db),
):
    """买入候选股"""
    try:
        result = await t1_service.execute_buy(db, req.candidate_id, req.quantity)
        return {"success": True, **result}
    except T1StrategyError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})


@router.post("/sell/{position_id}")
async def sell_position(
    position_id: int,
    sell_price: float = Query(..., gt=0, description="卖出价格"),
    sell_reason: str = Query("manual", description="卖出原因"),
    db: AsyncSession = Depends(get_db),
):
    """手动卖出持仓"""
    try:
        result = await t1_service.execute_morning_sell(
            db, position_id, sell_price, sell_reason
        )
        return {"success": True, **result}
    except T1StrategyError as e:
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})


@router.get("/positions")
async def list_positions(
    status: str = "holding",
    db: AsyncSession = Depends(get_db),
):
    """当前持仓列表"""
    query = (
        select(T1Position)
        .where(T1Position.status == status)
        .order_by(desc(T1Position.buy_date))
    )
    result = await db.execute(query)
    positions = result.scalars().all()
    return {
        "total": len(positions),
        "items": [
            {
                "id": p.id,
                "ts_code": p.ts_code,
                "stock_name": p.stock_name,
                "buy_date": str(p.buy_date),
                "buy_price": float(p.buy_price),
                "quantity": p.quantity,
                "criterion": p.criterion,
                "status": p.status,
            }
            for p in positions
        ],
    }


@router.get("/trades")
async def list_trades(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    criterion: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """交易记录（分页）"""
    query = select(T1Trade)
    count_query = select(func.count(T1Trade.id))
    if criterion:
        query = query.where(T1Trade.criterion == criterion)
        count_query = count_query.where(T1Trade.criterion == criterion)

    total = await db.scalar(count_query) or 0
    query = (
        query.order_by(desc(T1Trade.sell_date))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    trades = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": t.id,
                "ts_code": t.ts_code,
                "stock_name": t.stock_name,
                "criterion": t.criterion,
                "buy_date": str(t.buy_date),
                "buy_price": float(t.buy_price),
                "sell_date": str(t.sell_date),
                "sell_price": float(t.sell_price),
                "quantity": t.quantity,
                "sell_reason": t.sell_reason,
                "pnl": float(t.pnl),
                "pnl_pct": t.pnl_pct,
                "is_win": t.is_win,
            }
            for t in trades
        ],
    }


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """各条件胜率统计"""
    overview = await t1_service.get_overview_stats(db)

    result = await db.execute(
        select(T1CriteriaStats).order_by(T1CriteriaStats.criterion)
    )
    stats = result.scalars().all()

    return {
        "overview": overview,
        "criteria": [
            {
                "criterion": s.criterion,
                "period": s.period,
                "total_trades": s.total_trades,
                "win_count": s.win_count,
                "win_rate": s.win_rate,
                "avg_pnl_pct": s.avg_pnl_pct,
                "max_pnl_pct": s.max_pnl_pct,
                "min_pnl_pct": s.min_pnl_pct,
            }
            for s in stats
        ],
    }


@router.post("/backtest-sim")
async def run_backtest_simulation(
    start_date: str = Query("2025-10-01", description="回测开始日期 YYYY-MM-DD"),
    end_date: str = Query("2026-04-14", description="回测结束日期 YYYY-MM-DD"),
    initial_cash: float = Query(100000.0, description="初始资金"),
    db: AsyncSession = Depends(get_db),
):
    """
    T1 v4 策略历史回测模拟（成交现实化）。

    使用当前评分参数(权重/阈值/卖出参数)对历史数据进行完整模拟。
    无未来函数：选股仅用≤T数据，T日收盘买入，T+1卖出。
    成本：佣金双边万2.5(最低5元) + 印花税千0.5(仅卖出) + 滑点8bp双边。
    一字涨停买不进 / 一字跌停卖不出（持仓顺延）。
    """
    from engine.t1_v4.backtester import T1Backtester
    import pandas as pd

    bt = T1Backtester(
        initial_cash=initial_cash,
        top_n=settings.T1_TOP_N,
        market_safe_threshold=settings.T1_MARKET_SAFE_THRESHOLD,
        min_total_score=settings.T1_MIN_TOTAL_SCORE,
    )

    # 从数据库加载日线数据
    result = await db.execute(
        select(DailyBar)
        .where(DailyBar.trade_date >= date.fromisoformat(start_date))
        .where(DailyBar.trade_date <= date.fromisoformat(end_date))
        .order_by(DailyBar.ts_code, DailyBar.trade_date)
    )
    all_bars = result.scalars().all()

    if not all_bars:
        return {"error": "无日线数据，请先执行 /api/t1/sync-data 同步数据"}

    # 按 ts_code 分组构建 DataFrame
    from collections import defaultdict
    bars_by_code = defaultdict(list)
    for bar in all_bars:
        bars_by_code[bar.ts_code].append({
            "date": str(bar.trade_date).replace("-", ""),
            "open": float(bar.open or 0),
            "high": float(bar.high or 0),
            "low": float(bar.low or 0),
            "close": float(bar.close or 0),
            "volume": bar.volume or 0,
            "amount": float(bar.amount or 0),
            "turnover_rate": float(bar.turnover_rate or 0),
        })

    all_daily_data = {
        code: pd.DataFrame(rows) for code, rows in bars_by_code.items()
    }

    # 构建股票信息
    stocks_result = await db.execute(
        select(Stock.ts_code, Stock.name, Stock.industry, Stock.list_date)
        .where(Stock.is_active == True)
    )
    stock_info = {
        row.ts_code: {
            "name": row.name,
            "industry": row.industry,
            "list_date": str(row.list_date) if row.list_date else None,
        }
        for row in stocks_result.all()
    }

    # 获取交易日列表
    trade_dates_result = await db.execute(
        select(DailyBar.trade_date)
        .where(DailyBar.trade_date >= date.fromisoformat(start_date))
        .where(DailyBar.trade_date <= date.fromisoformat(end_date))
        .group_by(DailyBar.trade_date)
        .order_by(DailyBar.trade_date)
    )
    trade_dates = [str(row[0]).replace("-", "") for row in trade_dates_result.all()]

    # 运行回测
    bt_result = bt.run(
        all_daily_data=all_daily_data,
        stock_info=stock_info,
        trade_dates=trade_dates,
    )

    return {
        "period": f"{start_date} ~ {end_date}",
        "initial_cash": bt_result.initial_cash,
        "final_cash": bt_result.final_cash,
        "total_return_pct": bt_result.total_return_pct,
        "annual_return_pct": bt_result.annual_return_pct,
        "max_drawdown_pct": bt_result.max_drawdown_pct,
        "sharpe_ratio": bt_result.sharpe_ratio,
        "profit_factor": bt_result.profit_factor,
        "total_trades": bt_result.total_trades,
        "win_count": bt_result.win_count,
        "win_rate": bt_result.win_rate,
        "avg_pnl_pct": bt_result.avg_pnl_pct,
        "max_win_pct": bt_result.max_win_pct,
        "max_loss_pct": bt_result.max_loss_pct,
        "trading_days": bt_result.trading_days,
        "no_trade_days": bt_result.no_trade_days,
        "monthly_returns": bt_result.monthly_returns,
        # ── 成交现实化新增指标 ──
        "loss_count": bt_result.loss_count,
        "avg_win_pct": bt_result.avg_win_pct,
        "avg_loss_pct": bt_result.avg_loss_pct,
        "payoff_ratio": bt_result.payoff_ratio,
        "expectancy_pct": bt_result.expectancy_pct,
        "avg_holding_days": bt_result.avg_holding_days,
        "annual_turnover": bt_result.annual_turnover,
        "cost_drag_pct": bt_result.cost_drag_pct,
        "sortino_ratio": bt_result.sortino_ratio,
        "score_ic": bt_result.score_ic,
        "score_icir": bt_result.score_icir,
        "stuck_events": bt_result.stuck_events,
        "live_decay": bt_result.live_decay,
        "expected_live_return_pct": bt_result.expected_live_return_pct,
        "event_study": bt_result.event_study,
        "realism_notes": bt_result.realism_notes,
        "recent_trades": [
            {
                "buy_date": t.buy_date,
                "sell_date": t.sell_date,
                "ts_code": t.ts_code,
                "stock_name": t.stock_name,
                "buy_price": t.buy_price,
                "sell_price": t.sell_price,
                "pnl_pct": t.pnl_pct,
                "gross_pnl_pct": t.gross_pnl_pct,
                "cost_pct": t.cost_pct,
                "hold_days": t.hold_days,
                "sell_reason": t.sell_reason,
                "score": t.score,
                "is_win": t.is_win,
            }
            for t in bt_result.trades[-30:]  # 最近30笔
        ],
        "equity_curve": bt_result.equity_curve[::max(1, len(bt_result.equity_curve) // 100)],
    }


@router.post("/backtest")
async def run_backtest(
    req: dict,
    db: AsyncSession = Depends(get_db),
):
    """T1策略历史回测（简化版）"""
    start_date = req.get("start_date", "20240101")
    end_date = req.get("end_date", "20241231")
    criteria = req.get("criteria", ["limit_reopen", "tail_surge", "sector_leader"])

    # 从历史交易记录统计
    from sqlalchemy import and_

    results = {}
    for criterion in criteria:
        trades_result = await db.execute(
            select(T1Trade).where(
                and_(
                    T1Trade.criterion == criterion,
                    T1Trade.buy_date
                    >= date.fromisoformat(
                        f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
                    ),
                    T1Trade.sell_date
                    <= date.fromisoformat(
                        f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
                    ),
                )
            )
        )
        trades = trades_result.scalars().all()
        total = len(trades)
        wins = sum(1 for t in trades if t.is_win)
        total_pnl = sum(float(t.pnl) for t in trades)
        avg_pnl_pct = sum(t.pnl_pct for t in trades) / max(total, 1)

        results[criterion] = {
            "total_trades": total,
            "win_count": wins,
            "win_rate": round(wins / max(total, 1), 4),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_pct": round(avg_pnl_pct, 2),
        }

    return {
        "start_date": start_date,
        "end_date": end_date,
        "criteria": results,
    }


@router.get("/dashboard")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """T1 策略仪表盘 — 一次返回全部概览数据"""
    from datetime import timedelta

    today = date.today()

    # 0. 真实数据截止日（最新日线交易日）
    as_of_row = await db.execute(select(func.max(DailyBar.trade_date)))
    as_of = as_of_row.scalar()

    # 1. 概览统计（复用已有）
    overview = await t1_service.get_overview_stats(db)

    # 2. 最新已扫描日的候选 Top 3（无当天扫描则取最近一次）
    cand_date_row = await db.execute(select(func.max(T1Candidate.scan_date)))
    cand_date = cand_date_row.scalar() or today
    candidates_result = await db.execute(
        select(T1Candidate)
        .where(T1Candidate.scan_date == cand_date)
        .order_by(desc(T1Candidate.score))
        .limit(3)
    )
    top_candidates = [
        {
            "ts_code": c.ts_code,
            "stock_name": c.stock_name,
            "score": c.score,
            "tech_score": c.tech_score,
            "capital_score": c.capital_score,
            "resonance_count": c.resonance_count or 0,
            "suggested_pct": c.suggested_pct,
            "suggested_quantity": c.suggested_quantity,
            "status": c.status,
        }
        for c in candidates_result.scalars().all()
    ]

    # 3. 最近 5 笔交易
    trades_result = await db.execute(
        select(T1Trade)
        .order_by(desc(T1Trade.sell_date))
        .limit(5)
    )
    recent_trades = [
        {
            "ts_code": t.ts_code,
            "stock_name": t.stock_name,
            "buy_date": str(t.buy_date),
            "sell_date": str(t.sell_date),
            "pnl_pct": t.pnl_pct,
            "is_win": t.is_win,
            "sell_reason": t.sell_reason,
        }
        for t in trades_result.scalars().all()
    ]

    # 4. 近 7 日每日胜率（从 trades 表聚合）
    week_ago = today - timedelta(days=7)
    daily_stats_result = await db.execute(
        select(
            T1Trade.sell_date,
            func.count(T1Trade.id).label("total"),
            func.sum(func.cast(T1Trade.is_win, Integer)).label("wins"),
        )
        .where(T1Trade.sell_date >= week_ago)
        .group_by(T1Trade.sell_date)
        .order_by(T1Trade.sell_date)
    )
    daily_win_rates = [
        {
            "date": str(row.sell_date),
            "total": row.total,
            "wins": row.wins or 0,
            "win_rate": round((row.wins or 0) / max(row.total, 1), 4),
        }
        for row in daily_stats_result.all()
    ]

    return {
        "as_of": str(as_of) if as_of else None,
        "candidates_date": str(cand_date),
        "overview": overview,
        "top_candidates": top_candidates,
        "recent_trades": recent_trades,
        "daily_win_rates": daily_win_rates,
    }


@router.get("/report")
async def get_daily_report(
    report_date: Optional[str] = Query(None, description="报告日期 YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    """
    每日扫描报告 — 包含候选股评分、共振状态、仓位建议和风控状态。
    适合早盘前快速查看，决定今日操作。
    """
    if report_date:
        try:
            target_date = date.fromisoformat(report_date)
        except ValueError:
            return {"error": "日期格式错误，请使用 YYYY-MM-DD"}
    else:
        target_date = date.today()

    # 候选列表（含完整信息）
    candidates_result = await db.execute(
        select(T1Candidate)
        .where(T1Candidate.scan_date == target_date)
        .order_by(desc(T1Candidate.score))
    )
    candidates_list = []
    for c in candidates_result.scalars().all():
        candidates_list.append({
            "ts_code": c.ts_code,
            "stock_name": c.stock_name,
            "score": c.score,
            "tech_score": c.tech_score,
            "capital_score": c.capital_score,
            "fundamental_score": c.fundamental_score,
            "sector_score": c.sector_score,
            "market_score": c.market_score,
            "resonance_count": c.resonance_count or 0,
            "resonance_bonus": c.resonance_bonus or 0.0,
            "resonating_strategies": c.resonating_strategies.split(",") if c.resonating_strategies else [],
            "suggested_pct": c.suggested_pct,
            "suggested_quantity": c.suggested_quantity,
            "position_reason": c.position_reason,
            "close_price": float(c.close_price) if c.close_price else None,
            "status": c.status,
        })

    # 近期胜率统计
    recent_stats = await db.execute(
        select(
            func.count(T1Trade.id).label("total"),
            func.sum(func.cast(T1Trade.is_win, Integer)).label("wins"),
            func.avg(T1Trade.pnl_pct).label("avg_pnl"),
        )
    )
    stats_row = recent_stats.one()
    total_trades = stats_row.total or 0
    total_wins = stats_row.wins or 0

    # 风控状态
    consecutive_losses = 0
    recent_trades_result = await db.execute(
        select(T1Trade.is_win)
        .order_by(desc(T1Trade.sell_date))
        .limit(10)
    )
    for row in recent_trades_result.all():
        if not row.is_win:
            consecutive_losses += 1
        else:
            break

    return {
        "report_date": str(target_date),
        "candidates": candidates_list,
        "candidates_count": len(candidates_list),
        "stats": {
            "total_trades": total_trades,
            "win_rate": round(total_wins / max(total_trades, 1), 4),
            "avg_pnl_pct": round(float(stats_row.avg_pnl or 0), 2),
        },
        "risk_control": {
            "consecutive_losses": consecutive_losses,
            "is_paused": consecutive_losses >= settings.T1_CONSECUTIVE_LOSS_LIMIT,
        },
    }


@router.post("/sync-data")
async def sync_stock_data(
    days: int = Query(default=30, ge=5, le=90, description="同步最近N天数据"),
    db: AsyncSession = Depends(get_db),
):
    """
    按交易日批量同步全市场日线数据。

    策略：每个交易日调用一次 api.daily() + api.daily_basic()，
    单次拿到全市场所有股票数据，30天约需 60 次请求，速度远快于逐股拉取。
    """
    import asyncio
    from datetime import datetime, timedelta
    from decimal import Decimal

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.config import settings
    from app.models.pg_models import Stock, DailyBar

    if not settings.TUSHARE_TOKEN:
        return {"success": False, "error": "TUSHARE_TOKEN 未配置，请先在设置页面保存 Token"}

    import tushare as ts
    ts.set_token(settings.TUSHARE_TOKEN)
    api = ts.pro_api()

    def _safe_str(val, default=""):
        if val is None or (isinstance(val, float) and val != val):
            return default
        return str(val)

    # 1. 同步股票列表（一次请求，全量）
    logger.info("开始同步股票列表...")
    try:
        stock_df = await asyncio.to_thread(
            api.stock_basic,
            exchange="", list_status="L",
            fields="ts_code,name,industry,area,market,list_date",
        )
    except Exception as e:
        return {"success": False, "error": f"获取股票列表失败: {e}"}

    stock_count = 0
    for _, row in stock_df.iterrows():
        existing = await db.get(Stock, row["ts_code"])
        if not existing:
            db.add(Stock(
                ts_code=row["ts_code"],
                name=_safe_str(row["name"]),
                industry=_safe_str(row.get("industry")),
                area=_safe_str(row.get("area")),
                market=_safe_str(row.get("market")),
                list_date=(
                    datetime.strptime(row["list_date"], "%Y%m%d").date()
                    if row.get("list_date") else None
                ),
                is_active=True,
            ))
            stock_count += 1
    await db.commit()
    logger.info(f"股票列表同步完成: 新增 {stock_count} 只，共 {len(stock_df)} 只")

    # 2. 获取交易日历
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days + 10)  # 多取几天，过滤非交易日
    end_str = end_dt.strftime("%Y%m%d")
    start_str = start_dt.strftime("%Y%m%d")

    try:
        cal_df = await asyncio.to_thread(
            api.trade_cal,
            exchange="SSE", start_date=start_str, end_date=end_str,
            fields="cal_date,is_open",
        )
        trade_dates = (
            cal_df[cal_df["is_open"] == 1]["cal_date"]
            .sort_values(ascending=False)
            .head(days)
            .tolist()
        )
    except Exception:
        # 降级：自己生成日期（排除周末）
        trade_dates = []
        cur = end_dt
        while len(trade_dates) < days:
            if cur.weekday() < 5:
                trade_dates.append(cur.strftime("%Y%m%d"))
            cur -= timedelta(days=1)

    logger.info(f"待同步交易日: {len(trade_dates)} 天 ({trade_dates[-1]} ~ {trade_dates[0]})")

    # 3. 按交易日批量拉取（每天 2 次请求：daily + daily_basic）
    bar_count = 0
    errors = []

    for i, trade_date in enumerate(trade_dates):
        try:
            # OHLCV
            day_df = await asyncio.to_thread(
                api.daily,
                trade_date=trade_date,
                fields="ts_code,trade_date,open,high,low,close,vol,amount",
            )
            # 换手率
            try:
                basic_df = await asyncio.to_thread(
                    api.daily_basic,
                    trade_date=trade_date,
                    fields="ts_code,trade_date,turnover_rate,volume_ratio",
                )
                turnover_map = {}
                if basic_df is not None and not basic_df.empty:
                    for _, br in basic_df.iterrows():
                        turnover_map[br["ts_code"]] = float(br.get("turnover_rate") or 0)
            except Exception:
                turnover_map = {}

            if day_df is None or day_df.empty:
                logger.warning(f"  {trade_date}: 无数据（可能是非交易日）")
                continue

            td = datetime.strptime(trade_date, "%Y%m%d").date()

            # 批量 upsert（ON CONFLICT DO NOTHING 跳过已有记录）
            rows = []
            for _, b in day_df.iterrows():
                rows.append({
                    "ts_code":      b["ts_code"],
                    "trade_date":   td,
                    "open":         Decimal(str(b.get("open") or 0)),
                    "high":         Decimal(str(b.get("high") or 0)),
                    "low":          Decimal(str(b.get("low") or 0)),
                    "close":        Decimal(str(b.get("close") or 0)),
                    "volume":       int(b.get("vol") or 0),
                    "amount":       Decimal(str(b.get("amount") or 0)),
                    "turnover_rate": turnover_map.get(b["ts_code"], 0.0),
                })

            if rows:
                stmt = pg_insert(DailyBar).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["ts_code", "trade_date"],
                    set_={"turnover_rate": stmt.excluded.turnover_rate},
                )
                result = await db.execute(stmt)
                bar_count += len(rows)
                await db.commit()
                logger.info(f"  {trade_date}: {len(rows)} 条 ({'inserted/updated'})")

            # 限流：每 5 个交易日暂停一次
            if (i + 1) % 5 == 0:
                await asyncio.sleep(1)

        except Exception as e:
            errors.append(f"{trade_date}: {str(e)[:80]}")
            logger.error(f"  {trade_date} 同步失败: {e}")
            continue

    return {
        "success": True,
        "stocks_synced": stock_count,
        "stocks_total": len(stock_df),
        "trade_dates_synced": len(trade_dates) - len(errors),
        "bars_synced": bar_count,
        "errors": errors[:10],
    }
