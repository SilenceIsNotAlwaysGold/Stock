"""股票分析 API + SSE 进度推送"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import AnalyzeRequest, AnalysisReport
from agents.graph.trading_graph import run_analysis

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存任务存储（生产环境应使用 Redis）
_tasks: Dict[str, Dict] = {}
_reports: Dict[str, Dict] = {}


@router.post("/analyze")
async def analyze_stock(req: AnalyzeRequest):
    """触发单股 Agent 分析"""
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "task_id": task_id,
        "stock_code": req.stock_code,
        "stock_name": req.stock_name,
        "status": "running",
        "progress": 0,
        "current_node": "start",
        "created_at": datetime.now().isoformat(),
    }

    # 后台运行分析
    asyncio.create_task(_run_analysis_task(task_id, req))

    return {
        "task_id": task_id,
        "status": "running",
        "stock_code": req.stock_code,
    }


async def _run_analysis_task(task_id: str, req: AnalyzeRequest):
    """后台执行分析任务"""
    try:
        result = await run_analysis(
            stock_code=req.stock_code,
            stock_name=req.stock_name,
        )
        _reports[task_id] = result
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["progress"] = 100
        _tasks[task_id]["report_id"] = result["id"]
    except Exception as e:
        logger.error(f"Analysis failed for {req.stock_code}: {e}")
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = str(e)


@router.get("/report/{task_id}")
async def get_report(task_id: str):
    """获取分析报告"""
    if task_id in _reports:
        return _reports[task_id]
    task = _tasks.get(task_id)
    if task:
        return {"task_id": task_id, "status": task["status"]}
    raise HTTPException(status_code=404, detail="Report not found")


@router.get("/progress/{task_id}")
async def get_progress_sse(task_id: str):
    """SSE 进度推送"""

    async def event_stream():
        while True:
            task = _tasks.get(task_id)
            if not task:
                yield f"data: {json.dumps({'error': 'task not found'})}\n\n"
                break
            yield f"data: {json.dumps(task, default=str)}\n\n"
            if task["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/tasks")
async def list_tasks():
    """列出所有分析任务"""
    return list(_tasks.values())
