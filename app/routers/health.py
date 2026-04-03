"""Health check router"""

import time
from fastapi import APIRouter
from app.core.metrics import metrics

router = APIRouter()

# In-memory cache for health check (30s TTL)
_health_cache = {"data": None, "expires_at": 0}


@router.get("/health")
async def health_check():
    now = time.time()
    if _health_cache["data"] and now < _health_cache["expires_at"]:
        return _health_cache["data"]

    response = {"status": "ok"}
    _health_cache["data"] = response
    _health_cache["expires_at"] = now + 30  # 30s TTL
    return response


@router.get("/metrics")
async def get_metrics():
    return metrics.get_summary()
