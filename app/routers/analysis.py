"""股票分析 API + SSE 进度推送"""

import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Dict

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.pg_models import DailyBar, Stock
from app.models.schemas import AnalyzeRequest, AnalysisReport
from app.services import ai_stock_analyst
from agents.graph.trading_graph import run_analysis
from engine.sector_heat.news_fetcher import fetch_stock_news

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存任务存储（生产环境应使用 Redis）
_tasks: Dict[str, Dict] = {}
_reports: Dict[str, Dict] = {}


def normalize_ts_code(code: str) -> str:
    """
    规范化股票代码：裸 6 位自动补交易所后缀。
    601012 → 601012.SH ；000001 → 000001.SZ ；830xxx → 830xxx.BJ
    """
    c = (code or "").strip().upper()
    if "." in c:
        return c
    digits = "".join(ch for ch in c if ch.isdigit())
    if len(digits) != 6:
        return c
    h = digits[0]
    if h in ("6", "9", "5"):          # 沪市 A/B/基金
        suf = "SH"
    elif h in ("4", "8") or digits.startswith("92"):  # 北交所
        suf = "BJ"
    else:                              # 0/2/3 深市
        suf = "SZ"
    return f"{digits}.{suf}"


@router.get("/ai/{ts_code}")
async def ai_stock_analysis(
    ts_code: str,
    news_days: int = 14,
    use_llm: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """
    AI 个股分析决策卡：量化(技术/资金/趋势) + 真实消息面(东财新闻) + LLM 叙事。

    DeepSeek 不可用/超时自动规则兜底，保证始终产出可用结论。
    支持裸 6 位代码（自动补交易所后缀）。
    """
    import time as _t
    _t0 = _t.perf_counter()
    ts_code = normalize_ts_code(ts_code)
    logger.info(f"[AI分析] {ts_code} 开始：查询行情…")
    srow = await db.execute(
        select(Stock.name).where(Stock.ts_code == ts_code)
    )
    name = srow.scalar() or ts_code

    cutoff = date.today() - timedelta(days=120)
    brow = await db.execute(
        select(DailyBar.trade_date, DailyBar.open, DailyBar.high, DailyBar.low,
               DailyBar.close, DailyBar.volume, DailyBar.amount,
               DailyBar.turnover_rate)
        .where(DailyBar.ts_code == ts_code)
        .where(DailyBar.trade_date >= cutoff)
        .order_by(DailyBar.trade_date)
    )
    rows = brow.all()
    if not rows:
        raise HTTPException(404, f"{ts_code} 无日线数据，请先同步")
    _t_db = _t.perf_counter()
    logger.info(f"[AI分析] {ts_code} {name} 行情OK {len(rows)}根 "
                f"(db {(_t_db-_t0)*1000:.0f}ms)；拉取消息面…")
    df = pd.DataFrame([{
        "date": str(r.trade_date).replace("-", ""),
        "open": float(r.open or 0), "high": float(r.high or 0),
        "low": float(r.low or 0), "close": float(r.close or 0),
        "volume": r.volume or 0, "amount": float(r.amount or 0),
        "turnover_rate": float(r.turnover_rate or 0),
    } for r in rows])

    news = []
    try:
        ndf = await fetch_stock_news(ts_code, days=news_days)
        if ndf is not None and not ndf.empty:
            news = [{"title": str(x.get("title", "")),
                     "content": str(x.get("content", "")),
                     "pub_time": str(x.get("timestamp", ""))}
                    for _, x in ndf.head(15).iterrows()]
    except Exception as e:
        logger.warning(f"AI分析拉取新闻失败 {ts_code}: {e}")
    _t_news = _t.perf_counter()
    logger.info(f"[AI分析] {ts_code} 消息面OK {len(news)}条 "
                f"(news {(_t_news-_t_db)*1000:.0f}ms)；"
                f"{'LLM 综合研判中…' if use_llm else '规则研判中…'}")

    llm = None
    if use_llm:
        try:
            from agents.llm.factory import get_llm
            llm = get_llm()
        except Exception as e:
            logger.warning(f"AI分析 LLM 初始化失败，转规则兜底: {e}")

    result = await ai_stock_analyst.analyze(ts_code, name, df, news, llm=llm)
    _t_end = _t.perf_counter()
    logger.info(
        f"[AI分析] {ts_code} {name} 完成 评分{result.get('score')} "
        f"{result.get('rating')} | db {(_t_db-_t0)*1000:.0f}ms "
        f"news {(_t_news-_t_db)*1000:.0f}ms "
        f"{'llm' if result.get('llm_used') else 'rule'} "
        f"{(_t_end-_t_news)*1000:.0f}ms | 总 {(_t_end-_t0):.1f}s"
    )
    return result


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


# 多 Agent（并发编排）硬超时：防止永久挂起（卡进度条）
_MULTI_AGENT_TIMEOUT = 300  # 秒


async def _run_analysis_task(task_id: str, req: AnalyzeRequest):
    """后台执行分析任务（带硬超时，杜绝永久 running）"""
    try:
        result = await asyncio.wait_for(
            run_analysis(stock_code=req.stock_code,
                         stock_name=req.stock_name),
            timeout=_MULTI_AGENT_TIMEOUT,
        )
        _reports[task_id] = result
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["progress"] = 100
        _tasks[task_id]["report_id"] = result.get("id")
    except asyncio.TimeoutError:
        logger.error(f"Analysis timeout for {req.stock_code} "
                     f"(> {_MULTI_AGENT_TIMEOUT}s)")
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = (
            f"多 Agent 分析超时（>{_MULTI_AGENT_TIMEOUT}s）。"
            f"通常因 LLM 响应慢或额度不足，请用上方「AI 决策分析」（秒级，有规则兜底）。"
        )
    except Exception as e:
        logger.error(f"Analysis failed for {req.stock_code}: {e}")
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = str(e)


@router.get("/report/{task_id}")
async def get_report(task_id: str):
    """获取分析报告（含运行态进度与错误，供前端真实反馈）"""
    if task_id in _reports:
        return _reports[task_id]
    task = _tasks.get(task_id)
    if task:
        return {
            "task_id": task_id,
            "status": task["status"],
            "progress": task.get("progress", 0),
            "current_node": task.get("current_node", ""),
            "error": task.get("error", ""),
        }
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


@router.post("/analyze/{stock_code}")
async def run_stock_analysis(stock_code: str):
    """
    触发多 Agent 分析（技术面/基本面/新闻/情绪 → 多空辩论 → 风控）

    路径参数形式，直接同步等待分析完成后返回结果。
    run_analysis 内部通过 DataSourceManager 自行获取行情数据。
    """
    try:
        result = await run_analysis(stock_code=stock_code)
        return result
    except Exception as e:
        logger.error(f"Analysis failed for {stock_code}: {e}")
        return {"error": str(e), "stock_code": stock_code}


@router.get("/tasks")
async def list_tasks():
    """列出所有分析任务"""
    return list(_tasks.values())
