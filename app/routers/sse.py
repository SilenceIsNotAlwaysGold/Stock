"""SSE 进度推送"""

import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.core.progress import get_progress

router = APIRouter()


@router.get("/analysis/progress")
async def analysis_progress(task_id: str):
    """SSE 推送分析进度"""

    async def event_generator():
        max_wait = 300  # 最多等 5 分钟
        waited = 0
        while waited < max_wait:
            p = get_progress(task_id)
            if p is None:
                # 任务不存在，等一下再看
                yield json.dumps({
                    "task_id": task_id,
                    "status": "pending",
                    "progress": 0,
                    "message": "等待任务启动...",
                })
                await asyncio.sleep(1)
                waited += 1
                continue

            yield json.dumps({
                "task_id": task_id,
                "status": p.status,
                "progress": p.progress,
                "current": p.current,
                "total": p.total,
                "message": p.message,
            })

            if p.status in ("completed", "failed"):
                break

            await asyncio.sleep(0.5)
            waited += 0.5

    return EventSourceResponse(event_generator())
