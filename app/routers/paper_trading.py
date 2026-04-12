"""模拟盘 API"""

import logging
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()

logger.warning(
    "PaperTrading: 模拟盘数据存储在内存中，重启后将丢失。"
    "生产环境请迁移到 PostgreSQL 持久化存储。"
)

# 内存模拟账户（生产环境应使用 PG）
_accounts: Dict[str, Dict] = {}
_default_account_id = "default"


class PaperOrderRequest(BaseModel):
    ts_code: str
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)


def _get_account(account_id: str = "default") -> Dict:
    if account_id not in _accounts:
        _accounts[account_id] = {
            "id": account_id,
            "initial_cash": 1000000.0,
            "cash": 1000000.0,
            "positions": {},
            "orders": [],
            "created_at": datetime.now().isoformat(),
        }
    return _accounts[account_id]


@router.get("/account")
async def get_account(account_id: str = "default"):
    """获取模拟账户"""
    acc = _get_account(account_id)
    total_mv = sum(
        p["quantity"] * p["current_price"] for p in acc["positions"].values()
    )
    return {
        "id": acc["id"],
        "initial_cash": acc["initial_cash"],
        "cash": round(acc["cash"], 2),
        "total_market_value": round(total_mv, 2),
        "total_equity": round(acc["cash"] + total_mv, 2),
        "total_pnl": round(acc["cash"] + total_mv - acc["initial_cash"], 2),
    }


@router.post("/order")
async def place_order(req: PaperOrderRequest, account_id: str = "default"):
    """模拟下单"""
    acc = _get_account(account_id)
    cost = req.quantity * req.price
    fee = cost * 0.0003  # 万三手续费

    if req.direction == "BUY":
        total_cost = cost + fee
        if acc["cash"] < total_cost:
            raise HTTPException(400, "资金不足")
        acc["cash"] -= total_cost

        pos = acc["positions"].get(
            req.ts_code,
            {
                "ts_code": req.ts_code,
                "quantity": 0,
                "avg_cost": 0.0,
                "current_price": req.price,
            },
        )
        total_qty = pos["quantity"] + req.quantity
        pos["avg_cost"] = (
            (pos["avg_cost"] * pos["quantity"] + cost) / total_qty
            if total_qty > 0
            else 0
        )
        pos["quantity"] = total_qty
        pos["current_price"] = req.price
        acc["positions"][req.ts_code] = pos

    elif req.direction == "SELL":
        pos = acc["positions"].get(req.ts_code)
        if not pos or pos["quantity"] < req.quantity:
            raise HTTPException(400, "持仓不足")
        revenue = cost - fee
        acc["cash"] += revenue
        pos["quantity"] -= req.quantity
        if pos["quantity"] == 0:
            del acc["positions"][req.ts_code]
        else:
            pos["current_price"] = req.price

    order = {
        "ts_code": req.ts_code,
        "direction": req.direction,
        "quantity": req.quantity,
        "price": req.price,
        "fee": round(fee, 2),
        "time": datetime.now().isoformat(),
    }
    acc["orders"].append(order)

    return {"status": "filled", "order": order}


@router.get("/positions")
async def get_positions(account_id: str = "default"):
    """获取持仓"""
    acc = _get_account(account_id)
    positions = []
    for pos in acc["positions"].values():
        mv = pos["quantity"] * pos["current_price"]
        cost_total = pos["quantity"] * pos["avg_cost"]
        pnl = mv - cost_total
        positions.append(
            {
                **pos,
                "market_value": round(mv, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl / max(cost_total, 1) * 100, 2),
            }
        )
    return positions


@router.get("/orders")
async def get_orders(account_id: str = "default", limit: int = 50):
    """获取交易记录"""
    acc = _get_account(account_id)
    return acc["orders"][-limit:]


@router.post("/reset")
async def reset_account(account_id: str = "default"):
    """重置模拟账户"""
    if account_id in _accounts:
        del _accounts[account_id]
    return {"status": "reset", "account_id": account_id}
