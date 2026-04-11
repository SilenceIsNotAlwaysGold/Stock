"""
批量数据预加载器

设计目标：
1. 一次性加载全市场当日数据，避免逐只请求
2. 分级缓存 TTL 策略
3. 支持增量更新
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PreloadedData:
    """预加载的全市场数据快照"""

    trade_date: str
    daily_basic: Optional[pd.DataFrame] = None      # 全市场基本指标
    sector_list: Optional[pd.DataFrame] = None       # 行业板块列表
    north_flow: Optional[pd.DataFrame] = None        # 北向资金
    index_daily: Optional[pd.DataFrame] = None       # 指数日线(上证)
    stock_sectors: Dict[str, str] = field(default_factory=dict)  # ts_code -> sector_name
    money_flow_cache: Dict[str, pd.DataFrame] = field(default_factory=dict)  # ts_code -> moneyflow df
    fina_cache: Dict[str, pd.DataFrame] = field(default_factory=dict)  # ts_code -> fina df


class BatchPreloader:
    """
    批量预加载器

    使用方式：
        preloader = BatchPreloader(source_manager)
        data = await preloader.preload(trade_date="20260410")
        # data.daily_basic 就是全市场数据
        # data.sector_list 就是板块列表
    """

    # 缓存 TTL 配置（秒）
    CACHE_TTL = {
        "daily_basic": 4 * 3600,       # 日频数据 4小时
        "sector_list": 1 * 3600,       # 板块数据 1小时
        "north_flow": 4 * 3600,        # 北向资金 4小时
        "index_daily": 4 * 3600,       # 指数日线 4小时
        "fina_indicator": 30 * 86400,  # 财务数据 30天
        "money_flow": 4 * 3600,        # 资金流向 4小时
    }

    def __init__(self, source_manager):
        """source_manager 是 DataSourceManager 实例"""
        self.source_manager = source_manager
        self._cache: Dict[str, PreloadedData] = {}  # trade_date -> PreloadedData

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def preload(
        self,
        trade_date: str,
        stock_pool: Optional[List[str]] = None,
    ) -> PreloadedData:
        """
        预加载指定日期的全市场数据

        Args:
            trade_date: 交易日期 YYYYMMDD
            stock_pool: 可选，只预加载指定股票的个股数据（资金流、财务）

        Returns:
            PreloadedData 对象
        """
        # 1. 检查内存缓存
        if trade_date in self._cache:
            logger.debug(f"BatchPreloader: memory cache hit for {trade_date}")
            return self._cache[trade_date]

        # 2. 并行加载批量数据
        daily_basic, sector_list, north_flow, index_daily = await asyncio.gather(
            self._load_daily_basic(trade_date),
            self._load_sector_list(trade_date),
            self._load_north_flow(trade_date),
            self._load_index_daily(trade_date),
        )

        # 3. 构建 stock_sectors 映射
        stock_sectors = self._build_stock_sectors(sector_list)

        # 4. 构造 PreloadedData（个股数据先为空）
        data = PreloadedData(
            trade_date=trade_date,
            daily_basic=daily_basic,
            sector_list=sector_list,
            north_flow=north_flow,
            index_daily=index_daily,
            stock_sectors=stock_sectors,
        )

        # 5. 如果提供了 stock_pool，批量加载个股数据（限流 20 并发）
        if stock_pool:
            await self._preload_stock_pool(data, stock_pool, trade_date)

        # 6. 写入内存缓存
        self._cache[trade_date] = data
        return data

    async def preload_stock_detail(
        self,
        data: PreloadedData,
        ts_code: str,
        trade_date: str,
    ):
        """
        懒加载单只股票的详细数据（资金流、财务指标）
        如果已在缓存中直接返回，否则按需加载。
        """
        if ts_code not in data.money_flow_cache:
            money_flow = await self._load_money_flow(ts_code, trade_date)
            if money_flow is not None:
                data.money_flow_cache[ts_code] = money_flow

        if ts_code not in data.fina_cache:
            fina = await self._load_fina_indicator(ts_code, trade_date)
            if fina is not None:
                data.fina_cache[ts_code] = fina

    async def get_redis_cached(self, key: str, ttl_key: str) -> Optional[pd.DataFrame]:
        """从 Redis 获取缓存数据，使用 source_manager.cache"""
        cache = self.source_manager.cache
        if cache is None:
            return None
        try:
            raw = await cache.get(key)
            if raw is not None:
                return pd.DataFrame(raw)
        except Exception as e:
            logger.debug(f"Redis get failed for {key}: {e}")
        return None

    async def set_redis_cached(self, key: str, value: Any, ttl_key: str):
        """设置 Redis 缓存，使用 CACHE_TTL 中定义的 TTL"""
        cache = self.source_manager.cache
        if cache is None:
            return
        try:
            ttl = self.CACHE_TTL.get(ttl_key, 3600)
            # CacheManager.set 不直接支持自定义 TTL；
            # 尝试调用底层 Redis（若可用）以使用精确 TTL。
            # 若 Redis 不可用则回退到标准 cache.set。
            redis_client = getattr(cache, "redis", None)
            if redis_client is not None:
                serialized = json.dumps(value, default=str)
                await redis_client.set(key, serialized, ex=ttl)
            else:
                await cache.set(key, value)
        except Exception as e:
            logger.debug(f"Redis set failed for {key}: {e}")

    def clear_cache(self, trade_date: Optional[str] = None):
        """清除内存缓存"""
        if trade_date:
            self._cache.pop(trade_date, None)
        else:
            self._cache.clear()

    # ------------------------------------------------------------------
    # 私有：批量加载辅助
    # ------------------------------------------------------------------

    async def _load_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """加载全市场基本指标，先查 Redis 缓存"""
        redis_key = f"preload:daily_basic:{trade_date}"
        cached = await self.get_redis_cached(redis_key, "daily_basic")
        if cached is not None:
            return cached
        try:
            df = await self.source_manager.get_daily_basic(trade_date)
            if df is not None and not df.empty:
                await self.set_redis_cached(
                    redis_key, df.to_dict(orient="records"), "daily_basic"
                )
            return df
        except Exception as e:
            logger.warning(f"Failed to load daily_basic for {trade_date}: {e}")
            return None

    async def _load_sector_list(self, trade_date: str) -> Optional[pd.DataFrame]:
        """加载行业板块列表"""
        redis_key = f"preload:sector_list:{trade_date}"
        cached = await self.get_redis_cached(redis_key, "sector_list")
        if cached is not None:
            return cached
        try:
            df = await self.source_manager.get_sector_list(trade_date)
            if df is not None and not df.empty:
                await self.set_redis_cached(
                    redis_key, df.to_dict(orient="records"), "sector_list"
                )
            return df
        except Exception as e:
            logger.warning(f"Failed to load sector_list for {trade_date}: {e}")
            return None

    async def _load_north_flow(self, trade_date: str) -> Optional[pd.DataFrame]:
        """加载北向资金数据"""
        redis_key = f"preload:north_flow:{trade_date}"
        cached = await self.get_redis_cached(redis_key, "north_flow")
        if cached is not None:
            return cached
        try:
            df = await self.source_manager.get_north_flow(trade_date)
            if df is not None and not df.empty:
                await self.set_redis_cached(
                    redis_key, df.to_dict(orient="records"), "north_flow"
                )
            return df
        except Exception as e:
            logger.warning(f"Failed to load north_flow for {trade_date}: {e}")
            return None

    async def _load_index_daily(
        self, trade_date: str, index_code: str = "000001.SH", lookback_days: int = 60
    ) -> Optional[pd.DataFrame]:
        """加载指数日线（默认上证，取最近 lookback_days 天）"""
        redis_key = f"preload:index_daily:{index_code}:{trade_date}"
        cached = await self.get_redis_cached(redis_key, "index_daily")
        if cached is not None:
            return cached
        try:
            from datetime import datetime, timedelta

            end_dt = datetime.strptime(trade_date.replace("-", ""), "%Y%m%d")
            start_dt = end_dt - timedelta(days=lookback_days)
            start_str = start_dt.strftime("%Y%m%d")
            end_str = end_dt.strftime("%Y%m%d")
            df = await self.source_manager.get_index_daily(
                index_code, start_str, end_str
            )
            if df is not None and not df.empty:
                await self.set_redis_cached(
                    redis_key, df.to_dict(orient="records"), "index_daily"
                )
            return df
        except Exception as e:
            logger.warning(f"Failed to load index_daily for {trade_date}: {e}")
            return None

    async def _load_money_flow(
        self, ts_code: str, trade_date: str, lookback_days: int = 5
    ) -> Optional[pd.DataFrame]:
        """加载单只股票资金流向（取近 lookback_days 天）"""
        redis_key = f"preload:money_flow:{ts_code}:{trade_date}"
        cached = await self.get_redis_cached(redis_key, "money_flow")
        if cached is not None:
            return cached
        try:
            from datetime import datetime, timedelta

            end_dt = datetime.strptime(trade_date.replace("-", ""), "%Y%m%d")
            start_dt = end_dt - timedelta(days=lookback_days)
            start_str = start_dt.strftime("%Y%m%d")
            end_str = end_dt.strftime("%Y%m%d")
            df = await self.source_manager.get_money_flow(ts_code, start_str, end_str)
            if df is not None and not df.empty:
                await self.set_redis_cached(
                    redis_key, df.to_dict(orient="records"), "money_flow"
                )
            return df
        except Exception as e:
            logger.warning(f"Failed to load money_flow for {ts_code}: {e}")
            return None

    async def _load_fina_indicator(
        self, ts_code: str, trade_date: str
    ) -> Optional[pd.DataFrame]:
        """加载单只股票财务指标（季度数据，TTL 较长）"""
        redis_key = f"preload:fina_indicator:{ts_code}:{trade_date}"
        cached = await self.get_redis_cached(redis_key, "fina_indicator")
        if cached is not None:
            return cached
        try:
            df = await self.source_manager.get_fina_indicator(ts_code, trade_date)
            if df is not None and not df.empty:
                await self.set_redis_cached(
                    redis_key, df.to_dict(orient="records"), "fina_indicator"
                )
            return df
        except Exception as e:
            logger.warning(f"Failed to load fina_indicator for {ts_code}: {e}")
            return None

    async def _preload_stock_pool(
        self,
        data: PreloadedData,
        stock_pool: List[str],
        trade_date: str,
    ):
        """批量加载 stock_pool 的个股数据，使用 Semaphore(20) 限流"""
        sem = asyncio.Semaphore(20)

        async def load_one(ts_code: str):
            async with sem:
                money_flow = await self._load_money_flow(ts_code, trade_date)
                if money_flow is not None:
                    data.money_flow_cache[ts_code] = money_flow

                fina = await self._load_fina_indicator(ts_code, trade_date)
                if fina is not None:
                    data.fina_cache[ts_code] = fina

        await asyncio.gather(*[load_one(code) for code in stock_pool])
        logger.info(
            f"BatchPreloader: preloaded {len(stock_pool)} stocks "
            f"for {trade_date} "
            f"(money_flow={len(data.money_flow_cache)}, "
            f"fina={len(data.fina_cache)})"
        )

    # ------------------------------------------------------------------
    # 私有：辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _build_stock_sectors(sector_list: Optional[pd.DataFrame]) -> Dict[str, str]:
        """从 sector_list DataFrame 构建 ts_code -> sector_name 映射

        假设 sector_list 中包含 'ts_code' 和 'name'（板块名）列。
        若列名不符则返回空字典并记录 warning。
        """
        if sector_list is None or sector_list.empty:
            return {}

        # 尝试常见列名
        code_col = None
        for candidate in ("ts_code", "stock_code", "code"):
            if candidate in sector_list.columns:
                code_col = candidate
                break

        name_col = None
        for candidate in ("name", "sector_name", "industry"):
            if candidate in sector_list.columns:
                name_col = candidate
                break

        if code_col is None or name_col is None:
            logger.warning(
                f"Cannot build stock_sectors: expected columns not found. "
                f"Available columns: {list(sector_list.columns)}"
            )
            return {}

        return dict(zip(sector_list[code_col], sector_list[name_col]))
