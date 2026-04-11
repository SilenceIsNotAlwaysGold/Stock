"""简单的进程内进度追踪"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TaskProgress:
    task_id: str
    status: str = "pending"    # pending / running / completed / failed
    progress: int = 0          # 0-100
    message: str = ""
    current: int = 0           # 当前处理数
    total: int = 0             # 总数
    started_at: float = 0.0
    completed_at: float = 0.0


# 全局进度存储（简单方案，进程内字典）
_progress_store: Dict[str, TaskProgress] = {}


def create_task(task_id: str, total: int = 0) -> TaskProgress:
    p = TaskProgress(
        task_id=task_id,
        status="running",
        total=total,
        started_at=time.time(),
    )
    _progress_store[task_id] = p
    return p


def update_progress(task_id: str, current: int, message: str = ""):
    p = _progress_store.get(task_id)
    if p:
        p.current = current
        p.progress = int(current / max(p.total, 1) * 100)
        p.message = message


def complete_task(task_id: str, message: str = ""):
    p = _progress_store.get(task_id)
    if p:
        p.status = "completed"
        p.progress = 100
        p.message = message
        p.completed_at = time.time()


def fail_task(task_id: str, message: str = ""):
    p = _progress_store.get(task_id)
    if p:
        p.status = "failed"
        p.message = message
        p.completed_at = time.time()


def get_progress(task_id: str) -> Optional[TaskProgress]:
    return _progress_store.get(task_id)


def cleanup_old(max_age: int = 3600):
    """清理超过 max_age 秒的已完成任务"""
    now = time.time()
    to_delete = [
        tid for tid, p in _progress_store.items()
        if p.status in ("completed", "failed") and now - p.completed_at > max_age
    ]
    for tid in to_delete:
        del _progress_store[tid]
