"""Health check router"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.core.metrics import metrics

router = APIRouter()


@router.get("/health")
async def health_check():
    """服务健康检查 — 检测 PG/MongoDB/Redis"""
    checks = {}
    overall = "ok"

    # PostgreSQL
    try:
        from app.core.database import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {str(e)[:100]}"
        overall = "degraded"

    # MongoDB
    try:
        from app.core.database import get_mongo_client
        client = get_mongo_client()
        await client.admin.command("ping")
        checks["mongodb"] = "ok"
    except Exception as e:
        checks["mongodb"] = f"error: {str(e)[:100]}"
        overall = "degraded"

    # Redis
    try:
        from app.core.database import get_redis
        r = get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"
        overall = "degraded"

    status_code = 200 if overall == "ok" else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": overall, "checks": checks},
    )


@router.get("/metrics")
async def get_metrics():
    return metrics.get_summary()
