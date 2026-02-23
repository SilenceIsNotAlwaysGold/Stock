"""股票分析 API"""

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter()


class AnalyzeRequest(BaseModel):
    stock_code: str
    stock_name: str = ""


@router.post("/analyze")
async def analyze_stock(req: AnalyzeRequest, bg: BackgroundTasks):
    """触发单股 Agent 分析"""
    # TODO: T-011 实现完整分析流程
    task_id = f"analysis_{req.stock_code}"
    return {"task_id": task_id, "status": "queued", "stock_code": req.stock_code}


@router.get("/report/{report_id}")
async def get_report(report_id: str):
    """获取分析报告"""
    return {"report_id": report_id, "status": "not_found"}
