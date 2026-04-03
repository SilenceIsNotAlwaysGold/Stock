"""定时任务系统 (APScheduler)"""

import logging
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

_scheduler_running = False
_task_logs: List[Dict] = []
_task_status: Dict[str, Dict] = {}

# 定时任务定义
SCHEDULED_TASKS = {
    "data_sync": {
        "name": "数据同步",
        "cron": "0 18 * * 1-5",
        "description": "每个交易日 18:00 同步全量 A 股日线数据",
    },
    "emotion_calc": {
        "name": "情绪计算",
        "cron": "0 16 * * 1-5",
        "description": "每个交易日 16:00 计算市场情绪指标",
    },
    "recommendation": {
        "name": "推荐生成",
        "cron": "0 17 * * 1-5",
        "description": "每个交易日 17:00 生成每日推荐",
    },
    "paper_settlement": {
        "name": "模拟盘结算",
        "cron": "30 15 * * 1-5",
        "description": "每个交易日 15:30 结算模拟盘持仓",
    },
    "aese_evaluate": {
        "name": "AESE 评估",
        "cron": "0 20 * * 5",
        "description": "每周五 20:00 执行策略自进化评估",
    },
    "t1_scan": {
        "name": "T1 候选扫描",
        "cron": "30 14 * * 1-5",
        "description": "每个交易日 14:30 扫描T+1隔夜策略候选股",
    },
    "t1_premarket": {
        "name": "T1 盘前准备",
        "cron": "25 9 * * 1-5",
        "description": "每个交易日 9:25 盘前准备，标记待监控持仓",
    },
    "t1_morning_sell": {
        "name": "T1 早盘卖出",
        "cron": "30 10 * * 1-5",
        "description": "每个交易日 10:30 执行T+1超时卖出规则",
    },
}


@router.get("/tasks")
async def list_scheduled_tasks():
    """列出所有定时任务"""
    tasks = []
    for task_id, config in SCHEDULED_TASKS.items():
        status = _task_status.get(task_id, {})
        tasks.append(
            {
                "id": task_id,
                **config,
                "last_run": status.get("last_run"),
                "last_status": status.get("status", "idle"),
                "next_run": status.get("next_run"),
            }
        )
    return {"scheduler_running": _scheduler_running, "tasks": tasks}


@router.post("/trigger/{task_id}")
async def trigger_task(task_id: str):
    """手动触发定时任务"""
    if task_id not in SCHEDULED_TASKS:
        return {"error": f"Unknown task: {task_id}"}

    now = datetime.now().isoformat()
    _task_status[task_id] = {
        "status": "running",
        "last_run": now,
    }

    try:
        await _execute_task(task_id)
        _task_status[task_id]["status"] = "completed"
    except Exception as e:
        _task_status[task_id]["status"] = "failed"
        _task_status[task_id]["error"] = str(e)
        logger.error(f"Task {task_id} failed: {e}")

    _task_logs.append(
        {
            "task_id": task_id,
            "timestamp": now,
            "status": _task_status[task_id]["status"],
        }
    )

    return _task_status[task_id]


@router.get("/logs")
async def task_logs(limit: int = 50):
    """获取任务日志"""
    return _task_logs[-limit:]


async def _execute_task(task_id: str):
    """执行具体任务"""
    if task_id == "emotion_calc":
        from app.routers.emotion import _calculate_emotion

        await _calculate_emotion()
    elif task_id == "recommendation":
        from app.routers.recommend import _generate_recommendations

        await _generate_recommendations(None, 20)
    elif task_id == "aese_evaluate":
        from app.routers.aese import aese_evaluate

        await aese_evaluate()
    elif task_id == "data_sync":
        logger.info("Data sync triggered (placeholder)")
    elif task_id == "paper_settlement":
        logger.info("Paper settlement triggered (placeholder)")
    elif task_id == "t1_scan":
        from datetime import date as _date

        from app.core.database import async_session
        from app.services.t1_service import scan_candidates

        async with async_session() as db:
            result = await scan_candidates(db, _date.today())
            logger.info(f"T1 scan completed: {len(result)} candidates")
    elif task_id == "t1_premarket":
        logger.info("T1 premarket preparation triggered")
    elif task_id == "t1_morning_sell":
        from app.core.database import async_session
        from app.services.t1_service import check_and_sell_positions

        async with async_session() as db:
            result = await check_and_sell_positions(db)
            logger.info(f"T1 morning sell completed: {len(result)} positions sold")
    else:
        logger.warning(f"Unknown task: {task_id}")


def init_scheduler(app):
    """初始化 APScheduler（在 app lifespan 中调用）"""
    global _scheduler_running
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

        for task_id, config in SCHEDULED_TASKS.items():
            parts = config["cron"].split()
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
            scheduler.add_job(
                _execute_task,
                trigger,
                args=[task_id],
                id=task_id,
                name=config["name"],
            )

        scheduler.start()
        _scheduler_running = True
        logger.info("APScheduler started with %d tasks", len(SCHEDULED_TASKS))
    except ImportError:
        logger.warning("APScheduler not installed, scheduled tasks disabled")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
