"""
quant-platform-v8 FastAPI 应用入口
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.database import init_db, close_db
from app.core.exceptions import AppError
from app.core.metrics import metrics

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(f"Starting {settings.APP_NAME}...")

    await init_db()

    # 初始化定时任务调度器
    try:
        from app.routers.scheduler import init_scheduler

        init_scheduler(app)
        logger.info("Scheduler initialized")
    except Exception as e:
        logger.warning(f"Scheduler init failed: {e}")

    logger.info(f"{settings.APP_NAME} started successfully")

    yield

    await close_db()
    logger.info(f"{settings.APP_NAME} stopped")


app = FastAPI(
    title="Quant Platform v8 API",
    description="A 股智能量化选股平台 - 多 Agent 协作分析",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path in ("/health", "/favicon.ico"):
        return await call_next(request)

    # 生成或读取 request_id
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])

    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start

    logger.info(
        f"[{request_id}] {request.method} {request.url.path} - {response.status_code} ({elapsed:.3f}s)"
    )
    metrics.record(request.url.path, elapsed, response.status_code)

    # 响应头带上 request_id 方便前端排查
    response.headers["X-Request-ID"] = request_id
    return response


# Global exception handlers
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    logger.warning(f"AppError: [{exc.code}] {exc.message}")
    return JSONResponse(
        status_code=400,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = ".".join(str(loc) for loc in first.get("loc", []))
    msg = first.get("msg", "参数验证失败")
    logger.warning(f"Validation error on {request.url.path}: {field} - {msg}")
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"{field}: {msg}" if field else msg,
            }
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}
        },
    )


# --- Routers ---
from app.routers import health, stocks, analysis, sse  # noqa: E402
from app.routers import recommend, backtest, paper_trading  # noqa: E402
from app.routers import emotion, strategy_health  # noqa: E402
from app.routers import aese, auth, config, scheduler  # noqa: E402
from app.routers import t1_strategy  # noqa: E402

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(sse.router, prefix="/api/stream", tags=["streaming"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(paper_trading.router, prefix="/api/paper", tags=["paper_trading"])
app.include_router(emotion.router, prefix="/api/emotion", tags=["emotion"])
app.include_router(
    strategy_health.router, prefix="/api/strategy", tags=["strategy_health"]
)
app.include_router(aese.router, prefix="/api/aese", tags=["aese"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["scheduler"])
app.include_router(t1_strategy.router, prefix="/api/t1", tags=["t1_strategy"])


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "0.1.0",
        "status": "running",
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
