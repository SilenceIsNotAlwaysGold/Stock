"""
T+1 隔夜策略核心业务逻辑

v4 版本：使用 T1V4Scorer 多维度评分选股 + SellEngineV2 4 阶段卖出。
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import select, func, and_, Integer as SAInteger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pg_models import (
    T1Candidate,
    T1Position,
    T1Trade,
    T1CriteriaStats,
    Stock,
    DailyBar,
)
from app.core.exceptions import T1StrategyError

logger = logging.getLogger(__name__)


async def scan_candidates(
    db: AsyncSession, scan_date: date, top_n: int = 5
) -> List[Dict]:
    """
    扫描全市场，使用 T1V4Scorer 多维度评分选股，存入 t1_candidates。

    v4 流程：VetoFilter → 5维评分 → 排序 Top-N
    """
    import pandas as pd
    from engine.t1_v4.scorer import T1V4Scorer

    scorer = T1V4Scorer(top_n=top_n, market_safe_threshold=0)

    # 清除当天已有的 pending 候选（避免重复扫描累积）
    from sqlalchemy import delete as sql_delete

    await db.execute(
        sql_delete(T1Candidate).where(
            and_(T1Candidate.scan_date == scan_date, T1Candidate.status == "pending")
        )
    )
    await db.commit()

    # 查询当天已买入的股票，扫描时跳过
    bought_result = await db.execute(
        select(T1Candidate.ts_code).where(
            and_(T1Candidate.scan_date == scan_date, T1Candidate.status == "bought")
        )
    )
    bought_codes = {row[0] for row in bought_result.all()}

    # 获取活跃股票列表（带行业信息）
    result = await db.execute(
        select(Stock.ts_code, Stock.name, Stock.industry, Stock.list_date).where(
            Stock.is_active == True
        )
    )
    stocks = result.all()
    logger.info(f"T1 v4 scan: {len(stocks)} active stocks")

    # 预计算板块排名 + 板块涨停数
    sector_ranks = {}
    total_sectors = 0
    sector_limit_up_counts = {}
    industry_changes = {}

    for ts_code, stock_name, industry, list_date in stocks:
        bars_result = await db.execute(
            select(DailyBar)
            .where(DailyBar.ts_code == ts_code)
            .order_by(DailyBar.trade_date.desc())
            .limit(2)
        )
        bars = bars_result.scalars().all()
        if len(bars) >= 2:
            prev_close = float(bars[1].close or 1) or 0.01
            change = (float(bars[0].close or 0) - prev_close) / prev_close
            if industry:
                industry_changes.setdefault(industry, []).append(
                    (ts_code, change)
                )
                # 统计涨停
                if change >= 0.098:
                    sector_limit_up_counts[industry] = (
                        sector_limit_up_counts.get(industry, 0) + 1
                    )

    total_sectors = len(industry_changes)
    for industry, items in industry_changes.items():
        sorted_items = sorted(items, key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(sorted_items, 1):
            sector_ranks[code] = rank

    # 对行业按整体涨幅排名
    industry_avg_change = {
        ind: sum(c for _, c in items) / len(items)
        for ind, items in industry_changes.items()
    }
    sorted_industries = sorted(
        industry_avg_change.items(), key=lambda x: x[1], reverse=True
    )
    industry_rank_map = {ind: i + 1 for i, (ind, _) in enumerate(sorted_industries)}

    # 构建 stock_pool 和 daily_data
    stock_pool = []
    daily_data = {}
    stock_contexts = {}

    for ts_code, stock_name, industry, list_date in stocks:
        if ts_code in bought_codes:
            continue

        # 获取最近30天日线数据
        bars_result = await db.execute(
            select(DailyBar)
            .where(DailyBar.ts_code == ts_code)
            .order_by(DailyBar.trade_date.desc())
            .limit(30)
        )
        bars = bars_result.scalars().all()
        if len(bars) < 5:
            continue

        bars = list(reversed(bars))
        df = pd.DataFrame(
            [
                {
                    "date": b.trade_date,
                    "open": float(b.open or 0),
                    "high": float(b.high or 0),
                    "low": float(b.low or 0),
                    "close": float(b.close or 0),
                    "volume": b.volume or 0,
                    "amount": float(b.amount or 0),
                    "turnover_rate": b.turnover_rate or 0,
                }
                for b in bars
            ]
        )

        stock_pool.append(
            {
                "ts_code": ts_code,
                "name": stock_name,
                "list_date": str(list_date) if list_date else None,
            }
        )
        daily_data[ts_code] = df

        # 个股 context
        last_bar = bars[-1]
        stock_contexts[ts_code] = {
            "turnover_rate": float(last_bar.turnover_rate or 0) or None,
            "sector_rank": industry_rank_map.get(industry),
            "total_sectors": total_sectors,
            "sector_limit_up_count": sector_limit_up_counts.get(industry, 0),
            "is_suspended": False,
            # 以下字段需要额外数据源支撑，当前给 None 降级
            "money_flow_df": None,
            "north_flow_df": None,
            "fina_df": None,
            "pe": None,
            "industry_pe_median": None,
        }

    # 全局 context（指数、市场统计等）
    global_context = {
        "index_df": None,
        "market_stats": None,
    }

    logger.info(
        f"T1 v4 scan: scoring {len(stock_pool)} eligible stocks..."
    )

    # 调用 T1V4Scorer 评分 + 排序
    top_scores = scorer.rank_and_select(
        stock_pool=stock_pool,
        daily_data=daily_data,
        context=global_context,
        stock_contexts=stock_contexts,
        top_n=top_n,
    )

    # 写入数据库
    candidates = []
    for s in top_scores:
        last_close = 0.0
        df = daily_data.get(s.ts_code)
        if df is not None and not df.empty:
            last_close = float(df.iloc[-1]["close"])

        candidate = T1Candidate(
            scan_date=scan_date,
            ts_code=s.ts_code,
            stock_name=s.stock_name,
            criterion="v4_multidim",
            score=round(s.total_score, 2),
            tech_score=round(s.tech_score, 2),
            capital_score=round(s.capital_score, 2),
            fundamental_score=round(s.fundamental_score, 2),
            sector_score=round(s.sector_score, 2),
            market_score=round(s.market_score, 2),
            score_details=s.details,
            close_price=Decimal(str(last_close)),
            status="pending",
            reason=f"v4综合评分{s.total_score:.1f}分",
            created_at=datetime.utcnow(),
        )
        db.add(candidate)
        candidates.append(
            {
                "ts_code": s.ts_code,
                "stock_name": s.stock_name,
                "criterion": "v4_multidim",
                "score": s.total_score,
                "tech_score": s.tech_score,
                "capital_score": s.capital_score,
                "fundamental_score": s.fundamental_score,
                "sector_score": s.sector_score,
                "market_score": s.market_score,
                "reason": f"v4综合评分{s.total_score:.1f}分",
            }
        )

    await db.commit()
    logger.info(f"T1 v4 scan complete: {len(candidates)} candidates found")
    return candidates


async def execute_buy(db: AsyncSession, candidate_id: int, quantity: int = 100) -> Dict:
    """买入候选股，创建 t1_positions"""
    candidate = await db.get(T1Candidate, candidate_id)
    if not candidate:
        raise T1StrategyError(f"候选股 {candidate_id} 不存在")
    if candidate.status != "pending":
        raise T1StrategyError(f"候选股状态为 {candidate.status}，无法买入")

    position = T1Position(
        ts_code=candidate.ts_code,
        stock_name=candidate.stock_name,
        buy_date=candidate.scan_date,
        buy_price=candidate.close_price or Decimal("0"),
        quantity=quantity,
        criterion=candidate.criterion,
        candidate_id=candidate.id,
        status="holding",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(position)
    candidate.status = "bought"
    await db.commit()
    await db.refresh(position)

    return {
        "position_id": position.id,
        "ts_code": position.ts_code,
        "stock_name": position.stock_name,
        "buy_price": float(position.buy_price),
        "quantity": position.quantity,
    }


async def execute_morning_sell(
    db: AsyncSession, position_id: int, sell_price: float, sell_reason: str = "manual"
) -> Dict:
    """执行卖出逻辑"""
    position = await db.get(T1Position, position_id)
    if not position:
        raise T1StrategyError(f"持仓 {position_id} 不存在")
    if position.status != "holding":
        raise T1StrategyError(f"持仓状态为 {position.status}，无法卖出")

    sell_price_d = Decimal(str(sell_price))
    pnl = (sell_price_d - position.buy_price) * position.quantity
    pnl_pct = float((sell_price_d - position.buy_price) / position.buy_price * 100)

    trade = T1Trade(
        position_id=position.id,
        ts_code=position.ts_code,
        stock_name=position.stock_name,
        criterion=position.criterion,
        buy_date=position.buy_date,
        buy_price=position.buy_price,
        sell_date=date.today(),
        sell_price=sell_price_d,
        quantity=position.quantity,
        sell_reason=sell_reason,
        pnl=pnl,
        pnl_pct=round(pnl_pct, 2),
        is_win=pnl > 0,
        created_at=datetime.utcnow(),
    )
    db.add(trade)
    position.status = "sold"
    position.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(trade)

    # 更新统计
    await update_criteria_stats(db, position.criterion)

    return {
        "trade_id": trade.id,
        "ts_code": trade.ts_code,
        "sell_price": float(trade.sell_price),
        "sell_reason": trade.sell_reason,
        "pnl": float(trade.pnl),
        "pnl_pct": trade.pnl_pct,
        "is_win": trade.is_win,
    }


async def check_and_sell_positions(db: AsyncSession) -> List[Dict]:
    """早盘自动卖出检查（由定时任务调用），使用 SellEngineV2 4 阶段决策"""
    from engine.t1_v4.sell_engine_v2 import SellEngineV2

    sell_engine = SellEngineV2()

    result = await db.execute(select(T1Position).where(T1Position.status == "holding"))
    positions = result.scalars().all()
    results = []

    for pos in positions:
        # 获取今日日线数据
        bar_result = await db.execute(
            select(DailyBar).where(
                and_(
                    DailyBar.ts_code == pos.ts_code,
                    DailyBar.trade_date == date.today(),
                )
            )
        )
        bar = bar_result.scalar_one_or_none()
        if not bar:
            continue

        buy_price = float(pos.buy_price)
        next_open = float(bar.open or 0)
        next_high = float(bar.high or 0)
        next_low = float(bar.low or 0)
        next_close = float(bar.close or bar.open or 0)

        if next_open <= 0:
            continue

        # 用 SellEngineV2 做决策
        decision = sell_engine.decide(
            buy_price=buy_price,
            next_open=next_open,
            next_high=next_high,
            next_low=next_low,
            next_close=next_close,
        )

        sell_result = await execute_morning_sell(
            db, pos.id, decision.sell_price, decision.sell_reason
        )
        results.append(sell_result)

    return results


async def update_criteria_stats(db: AsyncSession, criterion: str) -> None:
    """从 t1_trades 重算指定条件的胜率统计"""
    result = await db.execute(
        select(
            func.count(T1Trade.id).label("total"),
            func.sum(func.cast(T1Trade.is_win, SAInteger)).label("wins"),
            func.avg(T1Trade.pnl_pct).label("avg_pnl"),
            func.max(T1Trade.pnl_pct).label("max_pnl"),
            func.min(T1Trade.pnl_pct).label("min_pnl"),
        ).where(T1Trade.criterion == criterion)
    )
    row = result.one()
    total = row.total or 0
    wins = row.wins or 0

    if total == 0:
        return

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(T1CriteriaStats).values(
        criterion=criterion,
        period="all",
        total_trades=total,
        win_count=wins,
        win_rate=round(wins / total, 4),
        avg_pnl_pct=round(float(row.avg_pnl or 0), 2),
        max_pnl_pct=round(float(row.max_pnl or 0), 2) if row.max_pnl else None,
        min_pnl_pct=round(float(row.min_pnl or 0), 2) if row.min_pnl else None,
        updated_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_t1_stats_criterion_period",
        set_={
            "total_trades": total,
            "win_count": wins,
            "win_rate": round(wins / total, 4),
            "avg_pnl_pct": round(float(row.avg_pnl or 0), 2),
            "max_pnl_pct": round(float(row.max_pnl or 0), 2) if row.max_pnl else None,
            "min_pnl_pct": round(float(row.min_pnl or 0), 2) if row.min_pnl else None,
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)
    await db.commit()


async def get_overview_stats(db: AsyncSession) -> Dict:
    """获取T1策略概览统计"""
    today = date.today()

    # 今日候选数
    candidates_count = await db.scalar(
        select(func.count(T1Candidate.id)).where(T1Candidate.scan_date == today)
    )
    # 当前持仓数
    positions_count = await db.scalar(
        select(func.count(T1Position.id)).where(T1Position.status == "holding")
    )
    # 总胜率
    total_trades = await db.scalar(select(func.count(T1Trade.id)))
    total_wins = await db.scalar(
        select(func.count(T1Trade.id)).where(T1Trade.is_win == True)
    )
    win_rate = round(total_wins / max(total_trades, 1), 4)
    # 累计盈亏
    total_pnl = await db.scalar(select(func.sum(T1Trade.pnl))) or 0

    return {
        "candidates_today": candidates_count or 0,
        "positions_holding": positions_count or 0,
        "total_trades": total_trades or 0,
        "win_rate": win_rate,
        "total_pnl": float(total_pnl),
    }
