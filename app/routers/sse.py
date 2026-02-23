"""SSE 进度推送"""

import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

router = APIRouter()


@router.get("/analysis/progress")
async def analysis_progress(task_id: str):
    """SSE 推送分析进度"""

    async def event_generator():
        # TODO: T-011 接入真实进度追踪
        yield json.dumps({"task_id": task_id, "status": "pending", "progress": 0})
        await asyncio.sleep(1)
        yield json.dumps({"task_id": task_id, "status": "completed", "progress": 100})

    return EventSourceResponse(event_generator())
