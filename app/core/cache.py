"""
Multi-level cache manager: Redis → MongoDB → miss
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.database import get_redis, get_mongo_db

logger = logging.getLogger(__name__)

# 全局 Redis 连接（由 database.py 初始化）
_redis = None


def set_redis(redis_client):
    global _redis
    _redis = redis_client


async def cache_get(key: str) -> Optional[Any]:
    """从 Redis 获取缓存"""
    if not _redis:
        return None
    try:
        data = await _redis.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.debug(f"Cache get error: {e}")
    return None


async def cache_set(key: str, value: Any, ttl: int = 300):
    """设置 Redis 缓存"""
    if not _redis:
        return
    try:
        await _redis.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as e:
        logger.debug(f"Cache set error: {e}")


async def cache_delete(pattern: str):
    """删除匹配的缓存"""
    if not _redis:
        return
    try:
        keys = []
        async for key in _redis.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            await _redis.delete(*keys)
    except Exception as e:
        logger.debug(f"Cache delete error: {e}")


class CacheManager:
    """Multi-level cache: Redis (5min) → MongoDB (1day) → miss"""

    REDIS_TTL = 300  # 5 minutes
    MONGO_TTL = 86400  # 1 day
    MONGO_COLLECTION = "cache_store"

    def __init__(self):
        self.redis = get_redis()
        self.mongo_db = get_mongo_db()

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache (Redis → MongoDB → miss)"""
        # Level 1: Redis
        try:
            redis_value = await self.redis.get(key)
            if redis_value:
                logger.debug(f"Cache hit (Redis): {key}")
                return json.loads(redis_value)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")

        # Level 2: MongoDB
        try:
            collection = self.mongo_db[self.MONGO_COLLECTION]
            doc = await collection.find_one({"_id": key})
            if doc and doc.get("expires_at") > datetime.utcnow():
                value = doc.get("value")
                logger.debug(f"Cache hit (MongoDB): {key}")
                # Promote to Redis
                await self._set_redis(key, value)
                return value
            elif doc:
                # Expired, delete it
                await collection.delete_one({"_id": key})
        except Exception as e:
            logger.warning(f"MongoDB get error: {e}")

        logger.debug(f"Cache miss: {key}")
        return None

    async def set(self, key: str, value: Any) -> bool:
        """Set value in both Redis and MongoDB"""
        try:
            # Set in Redis
            await self._set_redis(key, value)

            # Set in MongoDB
            await self._set_mongo(key, value)

            logger.debug(f"Cache set: {key}")
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from both Redis and MongoDB"""
        try:
            # Delete from Redis
            await self.redis.delete(key)

            # Delete from MongoDB
            collection = self.mongo_db[self.MONGO_COLLECTION]
            await collection.delete_one({"_id": key})

            logger.debug(f"Cache deleted: {key}")
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False

    async def _set_redis(self, key: str, value: Any) -> None:
        """Set value in Redis with TTL"""
        try:
            await self.redis.setex(key, self.REDIS_TTL, json.dumps(value, default=str))
        except Exception as e:
            logger.warning(f"Redis set error: {e}")

    async def _set_mongo(self, key: str, value: Any) -> None:
        """Set value in MongoDB with TTL"""
        try:
            collection = self.mongo_db[self.MONGO_COLLECTION]
            await collection.update_one(
                {"_id": key},
                {
                    "$set": {
                        "value": value,
                        "expires_at": datetime.utcnow()
                        + timedelta(seconds=self.MONGO_TTL),
                        "updated_at": datetime.utcnow(),
                    }
                },
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"MongoDB set error: {e}")
