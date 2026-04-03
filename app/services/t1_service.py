"""
T+1 隔夜策略核心业务逻辑
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
from engine.registry import StrategyRegistry

logger = logging.getLogger(__name__)

# T1 策略名称到 criterion 的映射
STRATEGY_CRITERION_MAP = {
    "t1_limit_reopen_reseal": "limit_reopen",
    "t1_tail_surge_volume": "tail_surge",
    "t1_sector_leader": "sector_leader",
}

CRITERION_LABELS = {
    "limit_reopen": "涨停回封",
    "tail_surge": "尾盘拉升",
    "sector_leader": "板块龙头",
}


async def scan_candidates(db: AsyncSession, scan_date: date) -> List[Dict]:
    """扫描全市场，运行3个T1子策略，存入t1_candidates"""
    import pandas as pd

    # 加载 T1 策略
    t1_strategies = [
        cls()
        for name, cls in StrategyRegistry.all().items()
        if getattr(cls, "category", "") == "t1_overnight"
    ]

    if not t1_strategies:
        StrategyRegistry.auto_discover()
        t1_strategies = [
            cls()
            for name, cls in StrategyRegistry.all().items()
            if getattr(cls, "category", "") == "t1_overnight"
        ]

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
        select(Stock.ts_code, Stock.name, Stock.industry).where(Stock.is_active == True)
    )
    stocks = result.all()
    logger.info(
        f"T1 scan: {len(stocks)} active stocks, {len(t1_strategies)} strategies"
    )

    # 预计算板块排名：按行业分组，计算每只股票的涨幅，取板块内排名
    sector_ranks = {}
    industry_changes = {}
    for ts_code, stock_name, industry in stocks:
        bars_result = await db.execute(
            select(DailyBar)
            .where(DailyBar.ts_code == ts_code)
            .order_by(DailyBar.trade_date.desc())
            .limit(2)
        )
        bars = bars_result.scalars().all()
        if len(bars) >= 2:
            change = (float(bars[0].close or 0) - float(bars[1].close or 0)) / max(
                float(bars[1].close or 1), 0.01
            )
            if industry:
                industry_changes.setdefault(industry, []).append((ts_code, change))

    # 计算每个行业内的排名
    for industry, items in industry_changes.items():
        sorted_items = sorted(items, key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(sorted_items, 1):
            sector_ranks[code] = rank

    candidates = []
    for ts_code, stock_name, industry in stocks:
        # 跳过当天已买入的股票
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

        # 转为 DataFrame（按日期正序）
        bars = list(reversed(bars))
        df = pd.DataFrame(
            [
                {
                    "trade_date": b.trade_date,
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

        # 构建 context（含板块排名）
        ctx = {"sector_rank": sector_ranks.get(ts_code)}

        for strategy in t1_strategies:
            try:
                sig = strategy.signal(df, context=ctx)
                if sig.action == "BUY" and sig.confidence >= 0.5:
                    criterion = sig.metadata.get(
                        "criterion",
                        STRATEGY_CRITERION_MAP.get(strategy.name, strategy.name),
                    )
                    candidate = T1Candidate(
                        scan_date=scan_date,
                        ts_code=ts_code,
                        stock_name=stock_name,
                        criterion=criterion,
                        score=round(sig.confidence, 3),
                        close_price=Decimal(str(df.iloc[-1]["close"])),
                        change_pct=sig.metadata.get("change_pct"),
                        volume_ratio=sig.metadata.get("volume_ratio"),
                        turnover_rate=sig.metadata.get("turnover_rate"),
                        status="pending",
                        reason=sig.reason,
                        created_at=datetime.utcnow(),
                    )
                    db.add(candidate)
                    candidates.append(
                        {
                            "ts_code": ts_code,
                            "stock_name": stock_name,
                            "criterion": criterion,
                            "score": sig.confidence,
                            "reason": sig.reason,
                        }
                    )
            except Exception as e:
                logger.warning(f"T1 strategy {strategy.name} failed on {ts_code}: {e}")

    await db.commit()
    logger.info(f"T1 scan complete: {len(candidates)} candidates found")
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
    """早盘自动卖出检查（由定时任务调用）"""
    result = await db.execute(select(T1Position).where(T1Position.status == "holding"))
    positions = result.scalars().all()
    results = []

    for pos in positions:
        # 获取今日最新价格
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
        open_price = float(bar.open or 0)
        current_price = float(bar.close or bar.open or 0)

        # 分档卖出规则
        if open_price >= buy_price * 1.05:
            sell_result = await execute_morning_sell(
                db, pos.id, open_price, "take_profit"
            )
            results.append(sell_result)
        elif current_price <= buy_price * 0.97:
            sell_result = await execute_morning_sell(
                db, pos.id, current_price, "stop_loss"
            )
            results.append(sell_result)
        else:
            # 10:30 超时卖出（由定时任务在10:30触发时执行）
            high_pct = (float(bar.high or 0) - buy_price) / buy_price
            if high_pct < 0.098:  # 未涨停
                sell_result = await execute_morning_sell(
                    db, pos.id, current_price, "timeout_sell"
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
