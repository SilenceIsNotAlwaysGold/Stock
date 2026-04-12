"""T+1 隔夜策略 API 路由"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import T1StrategyError
from app.models.pg_models import T1Candidate, T1Position, T1Trade, T1CriteriaStats
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


@router.post("/sync-data")
async def sync_stock_data(
    top_n: int = Query(settings.T1_TOP_N * 10, description="同步前N只活跃股票的日线数据"),
    days: int = Query(settings.T1_SCAN_DAYS, description="同步最近N天数据"),
    db: AsyncSession = Depends(get_db),
):
    """用 Tushare 同步股票列表和日线数据到数据库"""
    import asyncio
    from datetime import datetime, timedelta
    from decimal import Decimal

    from app.config import settings
    from app.models.pg_models import Stock, DailyBar

    if not settings.TUSHARE_TOKEN:
        return {"success": False, "error": "TUSHARE_TOKEN 未配置"}

    import tushare as ts

    ts.set_token(settings.TUSHARE_TOKEN)
    api = ts.pro_api()

    # 1. 同步股票列表
    stock_df = await asyncio.to_thread(
        api.stock_basic,
        exchange="",
        list_status="L",
        fields="ts_code,name,industry,area,market,list_date",
    )
    def _safe_str(val, default=""):
        """NaN/None → 空字符串"""
        if val is None or (isinstance(val, float) and val != val):
            return default
        return str(val)

    stock_count = 0
    for _, row in stock_df.iterrows():
        existing = await db.get(Stock, row["ts_code"])
        if not existing:
            db.add(
                Stock(
                    ts_code=row["ts_code"],
                    name=_safe_str(row["name"]),
                    industry=_safe_str(row.get("industry")),
                    area=_safe_str(row.get("area")),
                    market=_safe_str(row.get("market")),
                    list_date=(
                        datetime.strptime(row["list_date"], "%Y%m%d").date()
                        if row.get("list_date")
                        else None
                    ),
                    is_active=True,
                )
            )
            stock_count += 1
    await db.commit()
    logger.info(f"Synced {stock_count} new stocks (total {len(stock_df)})")

    # 2. 同步日线数据 - 取成交额最大的 top_n 只
    end_date_str = date.today().strftime("%Y%m%d")
    start_date_str = (date.today() - timedelta(days=days)).strftime("%Y%m%d")

    # 获取最近交易日活跃股票
    try:
        daily_basic = await asyncio.to_thread(
            api.daily_basic,
            trade_date=end_date_str,
            fields="ts_code,turnover_rate,volume_ratio",
        )
        if daily_basic is None or daily_basic.empty:
            # 尝试前一个交易日
            prev_date = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
            daily_basic = await asyncio.to_thread(
                api.daily_basic,
                trade_date=prev_date,
                fields="ts_code,turnover_rate,volume_ratio",
            )
    except Exception:
        daily_basic = None

    if daily_basic is not None and not daily_basic.empty:
        active_codes = daily_basic.nlargest(top_n, "turnover_rate")["ts_code"].tolist()
    else:
        active_codes = stock_df.head(top_n)["ts_code"].tolist()

    bar_count = 0
    errors = []
    for i, code in enumerate(active_codes):
        try:
            bars = await asyncio.to_thread(
                ts.pro_bar,
                ts_code=code,
                start_date=start_date_str,
                end_date=end_date_str,
                adj="qfq",
            )
            if bars is None or bars.empty:
                continue

            # 获取该股票的 daily_basic 数据（含换手率、量比）
            try:
                basic = await asyncio.to_thread(
                    api.daily_basic,
                    ts_code=code,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    fields="ts_code,trade_date,turnover_rate,volume_ratio",
                )
                basic_map = {}
                if basic is not None and not basic.empty:
                    for _, br in basic.iterrows():
                        basic_map[br["trade_date"]] = {
                            "turnover_rate": float(br.get("turnover_rate", 0) or 0),
                            "volume_ratio": float(br.get("volume_ratio", 0) or 0),
                        }
            except Exception:
                basic_map = {}

            for _, b in bars.iterrows():
                td = datetime.strptime(b["trade_date"], "%Y%m%d").date()
                from sqlalchemy import and_

                exists = await db.scalar(
                    select(func.count(DailyBar.id)).where(
                        and_(DailyBar.ts_code == code, DailyBar.trade_date == td)
                    )
                )
                extra = basic_map.get(b["trade_date"], {})
                if not exists:
                    db.add(
                        DailyBar(
                            ts_code=code,
                            trade_date=td,
                            open=Decimal(str(b.get("open", 0) or 0)),
                            high=Decimal(str(b.get("high", 0) or 0)),
                            low=Decimal(str(b.get("low", 0) or 0)),
                            close=Decimal(str(b.get("close", 0) or 0)),
                            volume=int(b.get("vol", 0) or 0),
                            amount=Decimal(str(b.get("amount", 0) or 0)),
                            turnover_rate=extra.get("turnover_rate", 0),
                        )
                    )
                    bar_count += 1
                elif extra.get("turnover_rate", 0) > 0:
                    # 更新已有记录的换手率
                    from sqlalchemy import update as sql_update

                    await db.execute(
                        sql_update(DailyBar)
                        .where(
                            and_(DailyBar.ts_code == code, DailyBar.trade_date == td)
                        )
                        .values(turnover_rate=extra["turnover_rate"])
                    )
            await db.commit()
            # Tushare 限流
            if (i + 1) % 10 == 0:
                await asyncio.sleep(1)
        except Exception as e:
            errors.append(f"{code}: {str(e)[:50]}")
            continue

    return {
        "success": True,
        "stocks_synced": stock_count,
        "stocks_total": len(stock_df),
        "bars_synced": bar_count,
        "active_codes_count": len(active_codes),
        "errors": errors[:10],
    }
