"""股票数据 API"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/list")
async def stock_list():
    """获取股票列表"""
    return {"stocks": [], "total": 0}


@router.get("/{code}/daily")
async def stock_daily(code: str, start_date: str = "", end_date: str = ""):
    """获取日线数据"""
    return {"code": code, "data": []}


@router.post("/sync")
async def stock_sync():
    """触发数据同步"""
    return {"status": "started", "message": "Data sync triggered"}
