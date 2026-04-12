"""
quant-platform-v8 数据库连接管理
"""

import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from motor.motor_asyncio import AsyncIOMotorClient
from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)


# ---- SQLAlchemy (PostgreSQL) ----
class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.pg_dsn,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency: get async DB session"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# ---- MongoDB ----
_mongo_client: AsyncIOMotorClient | None = None
_mongo_db = None


def get_mongo_client() -> AsyncIOMotorClient:
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(settings.mongo_dsn)
    return _mongo_client


def get_mongo_db():
    global _mongo_db
    if _mongo_db is None:
        _mongo_db = get_mongo_client()[settings.MONGO_DATABASE]
    return _mongo_db


# ---- Redis ----
_redis_client: Redis | None = None


def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


# ---- Lifecycle ----
async def init_db():
    """Initialize database connections — graceful degradation"""
    logger.info("Initializing database connections...")

    # PostgreSQL（核心，必须成功）
    async with engine.begin() as conn:
        logger.info(
            f"PostgreSQL connected: {settings.PG_HOST}:{settings.PG_PORT}/{settings.PG_DATABASE}"
        )

    # MongoDB（可选，失败降级）
    try:
        client = get_mongo_client()
        await client.admin.command("ping")
        logger.info(
            f"MongoDB connected: {settings.MONGO_HOST}:{settings.MONGO_PORT}/{settings.MONGO_DATABASE}"
        )
    except Exception as e:
        logger.warning(f"MongoDB connection failed (non-critical, will retry on use): {e}")

    # Redis（可选，失败降级）
    try:
        r = get_redis()
        await r.ping()
        logger.info(f"Redis connected: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        from app.core.cache import set_redis
        set_redis(r)
    except Exception as e:
        logger.warning(f"Redis connection failed (non-critical, cache disabled): {e}")


async def close_db():
    """Close all database connections"""
    global _mongo_client, _mongo_db, _redis_client

    await engine.dispose()
    logger.info("PostgreSQL connection closed")

    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None
        _mongo_db = None
        logger.info("MongoDB connection closed")

    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis connection closed")
