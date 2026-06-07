"""模拟盘 API — 持久化到 PostgreSQL"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.pg_models import PaperAccount, PaperPosition, PaperOrder, Stock

logger = logging.getLogger(__name__)
router = APIRouter()


_DEFAULT_USER = "default"
_INITIAL_CASH = Decimal("1000000")
_FEE_RATE = Decimal("0.0003")  # 万三手续费


async def get_db():
    async with async_session() as db:
        yield db


class PaperOrderRequest(BaseModel):
    ts_code: str
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)


async def _get_or_create_account(db: AsyncSession, user_id: str = _DEFAULT_USER) -> PaperAccount:
    r = await db.execute(select(PaperAccount).where(PaperAccount.user_id == user_id))
    acc = r.scalar_one_or_none()
    if acc is None:
        acc = PaperAccount(
            user_id=user_id,
            name="默认模拟账户",
            initial_cash=_INITIAL_CASH,
            current_cash=_INITIAL_CASH,
        )
        db.add(acc)
        await db.commit()
        await db.refresh(acc)
    return acc


async def _stock_name(db: AsyncSession, ts_code: str) -> str:
    r = await db.execute(select(Stock.name).where(Stock.ts_code == ts_code))
    n = r.scalar_one_or_none()
    return n or ts_code


@router.get("/account")
async def get_account(account_id: str = "default", db: AsyncSession = Depends(get_db)):
    """获取模拟账户"""
    acc = await _get_or_create_account(db, account_id)
    pr = await db.execute(select(PaperPosition).where(PaperPosition.account_id == acc.id))
    positions = pr.scalars().all()
    total_mv = sum(float(p.market_value or 0) for p in positions)
    cash = float(acc.current_cash)
    return {
        "id": acc.user_id,
        "initial_cash": float(acc.initial_cash),
        "cash": round(cash, 2),
        "total_market_value": round(total_mv, 2),
        "total_equity": round(cash + total_mv, 2),
        "total_pnl": round(cash + total_mv - float(acc.initial_cash), 2),
    }


@router.post("/order")
async def place_order(
    req: PaperOrderRequest,
    account_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """模拟下单"""
    acc = await _get_or_create_account(db, account_id)
    qty = req.quantity
    price = Decimal(str(req.price))
    cost = price * qty
    fee = cost * _FEE_RATE

    pr = await db.execute(
        select(PaperPosition).where(
            PaperPosition.account_id == acc.id,
            PaperPosition.ts_code == req.ts_code,
        )
    )
    pos = pr.scalar_one_or_none()

    if req.direction == "BUY":
        total = cost + fee
        if acc.current_cash < total:
            raise HTTPException(400, "资金不足")
        acc.current_cash -= total

        if pos is None:
            stock_name = await _stock_name(db, req.ts_code)
            pos = PaperPosition(
                account_id=acc.id,
                ts_code=req.ts_code,
                stock_name=stock_name,
                quantity=qty,
                avg_cost=price,
                current_price=price,
                market_value=cost,
                unrealized_pnl=Decimal("0"),
                unrealized_pnl_pct=Decimal("0"),
            )
            db.add(pos)
        else:
            new_qty = pos.quantity + qty
            pos.avg_cost = (pos.avg_cost * pos.quantity + cost) / new_qty
            pos.quantity = new_qty
            pos.current_price = price
            pos.market_value = price * new_qty
            pos.unrealized_pnl = (price - pos.avg_cost) * new_qty
            pos.unrealized_pnl_pct = (price - pos.avg_cost) / pos.avg_cost * 100

    else:  # SELL
        if pos is None or pos.quantity < qty:
            raise HTTPException(400, "持仓不足")
        revenue = cost - fee
        acc.current_cash += revenue
        pos.quantity -= qty
        if pos.quantity == 0:
            await db.delete(pos)
        else:
            pos.current_price = price
            pos.market_value = price * pos.quantity
            pos.unrealized_pnl = (price - pos.avg_cost) * pos.quantity
            pos.unrealized_pnl_pct = (price - pos.avg_cost) / pos.avg_cost * 100

    stock_name = pos.stock_name if pos else (await _stock_name(db, req.ts_code))
    order = PaperOrder(
        account_id=acc.id,
        ts_code=req.ts_code,
        stock_name=stock_name,
        direction=req.direction,
        quantity=qty,
        price=price,
        amount=cost,
        commission=fee,
        status="FILLED",
        filled_at=datetime.utcnow(),
    )
    db.add(order)
    await db.commit()

    return {
        "status": "filled",
        "order": {
            "id": order.id,
            "ts_code": order.ts_code,
            "direction": order.direction,
            "quantity": order.quantity,
            "price": float(order.price),
            "fee": float(order.commission),
            "time": order.created_at.isoformat() if order.created_at else None,
        },
    }


@router.get("/positions")
async def get_positions(account_id: str = "default", db: AsyncSession = Depends(get_db)):
    """获取持仓"""
    acc = await _get_or_create_account(db, account_id)
    r = await db.execute(select(PaperPosition).where(PaperPosition.account_id == acc.id))
    positions = r.scalars().all()
    return [
        {
            "ts_code": p.ts_code,
            "stock_name": p.stock_name,
            "quantity": p.quantity,
            "avg_cost": float(p.avg_cost),
            "current_price": float(p.current_price),
            "market_value": round(float(p.market_value), 2),
            "unrealized_pnl": round(float(p.unrealized_pnl), 2),
            "unrealized_pnl_pct": round(float(p.unrealized_pnl_pct), 2),
        }
        for p in positions
    ]


@router.get("/orders")
async def get_orders(
    account_id: str = "default",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取交易记录"""
    acc = await _get_or_create_account(db, account_id)
    r = await db.execute(
        select(PaperOrder)
        .where(PaperOrder.account_id == acc.id)
        .order_by(PaperOrder.created_at.desc())
        .limit(limit)
    )
    orders = r.scalars().all()
    return [
        {
            "id": o.id,
            "ts_code": o.ts_code,
            "stock_name": o.stock_name,
            "direction": o.direction,
            "quantity": o.quantity,
            "price": float(o.price),
            "fee": float(o.commission),
            "time": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]


@router.post("/reset")
async def reset_account(account_id: str = "default", db: AsyncSession = Depends(get_db)):
    """重置模拟账户"""
    r = await db.execute(select(PaperAccount).where(PaperAccount.user_id == account_id))
    acc = r.scalar_one_or_none()
    if acc:
        await db.execute(delete(PaperPosition).where(PaperPosition.account_id == acc.id))
        await db.execute(delete(PaperOrder).where(PaperOrder.account_id == acc.id))
        acc.current_cash = acc.initial_cash
        await db.commit()
    return {"status": "reset", "account_id": account_id}
