"""定时任务系统 (APScheduler)"""

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Dict

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

_scheduler_running = False
_task_logs: deque = deque(maxlen=500)
_task_status: Dict[str, Dict] = {}


async def _persist_log(log_entry: dict):
    """尝试持久化到 MongoDB（可选，失败不影响主流程）"""
    try:
        from app.core.database import get_mongo_db

        mongo_db = get_mongo_db()
        if mongo_db is not None:
            collection = mongo_db["scheduler_logs"]
            await collection.insert_one(log_entry)
    except Exception as e:
        logger.debug(f"MongoDB 日志持久化失败（可忽略）: {e}")


def add_task_log(task_name: str, status: str, message: str = "", duration: float = 0):
    """添加任务执行日志"""
    entry = {
        "task_name": task_name,
        "status": status,
        "message": message,
        "duration": round(duration, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
    _task_logs.append(entry)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist_log(entry))
    except RuntimeError:
        pass

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

    add_task_log(
        task_name=task_id,
        status=_task_status[task_id]["status"],
        message=_task_status[task_id].get("message", ""),
    )

    return _task_status[task_id]


@router.get("/logs")
async def task_logs(limit: int = 50):
    """获取任务日志"""
    return list(_task_logs)[-limit:]


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
        await _job_data_sync()
    elif task_id == "paper_settlement":
        await _job_paper_settlement()
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


async def _job_data_sync():
    """定时数据同步：从 Tushare 同步最新日线到数据库"""
    from datetime import date, timedelta
    import asyncio

    logger.info("定时任务: data_sync 开始")
    try:
        import tushare as ts
        from app.config import settings

        if not settings.TUSHARE_TOKEN:
            logger.warning("data_sync: TUSHARE_TOKEN 未配置，跳过")
            return

        ts.set_token(settings.TUSHARE_TOKEN)
        api = ts.pro_api()

        end_date = date.today().strftime("%Y%m%d")

        df = await asyncio.to_thread(
            api.daily_basic,
            trade_date=end_date,
            fields="ts_code,trade_date,turnover_rate,pe,pb,total_mv,circ_mv",
        )
        if df is not None:
            logger.info(f"data_sync: 获取 daily_basic {len(df)} 行")

        logger.info("定时任务: data_sync 完成")
    except Exception as e:
        logger.error(f"data_sync 失败: {e}")


async def _job_paper_settlement():
    """早盘自动卖出检查"""
    from app.core.database import async_session
    from app.services.t1_service import check_and_sell_positions

    logger.info("定时任务: paper_settlement 开始")
    try:
        async with async_session() as db:
            results = await check_and_sell_positions(db)
            logger.info(f"paper_settlement: 处理 {len(results)} 笔卖出")
    except Exception as e:
        logger.error(f"paper_settlement 失败: {e}")


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
