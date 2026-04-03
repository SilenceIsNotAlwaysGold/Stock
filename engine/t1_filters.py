"""
T+1 策略 v2 - 多维度市场过滤器

独立模块，不侵入现有子策略逻辑。
包含：大盘环境评分、资金流向确认、板块热度排名、市场情绪指标。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MarketEnvironment:
    """大盘环境评估结果"""

    score: float = 0.0  # 0-100
    is_tradable: bool = True
    ma20_above: bool = False
    macd_bullish: bool = False
    advance_decline_ratio: float = 1.0
    limit_up_count: int = 0
    limit_down_count: int = 0
    mood: str = "neutral"
    reasons: List[str] = field(default_factory=list)


@dataclass
class StockFilter:
    """个股过滤结果"""

    ts_code: str
    passed: bool = True
    capital_flow_score: float = 0.0  # 资金流向评分
    sector_heat_score: float = 0.0  # 板块热度评分
    composite_bonus: float = 0.0  # 综合加分
    reject_reasons: List[str] = field(default_factory=list)


class MarketEnvironmentFilter:
    """
    大盘环境过滤器 (R-001 + R-003)

    评分维度（满分 100）：
    - 指数位置 (30分): 收盘价 vs MA5/MA10/MA20
    - 趋势动能 (25分): MACD 方向 + DIF/DEA 位置
    - 市场宽度 (25分): 涨跌比 + 涨停/跌停数
    - 量能配合 (20分): 成交量 vs 均量
    """

    # 可配置阈值
    DEFAULT_PARAMS = {
        "min_score_to_trade": 45,  # 最低可交易评分
        "strong_market_score": 70,  # 强势市场评分
        "weak_market_score": 35,  # 弱势市场评分（暂停交易）
        "ad_ratio_pause": 0.5,  # 涨跌比低于此值暂停
        "limit_down_pause": 50,  # 跌停数超过此值暂停
    }

    def __init__(self, **overrides):
        self.params = {**self.DEFAULT_PARAMS, **overrides}

    def evaluate(
        self,
        index_df: pd.DataFrame,
        market_stats: Optional[Dict] = None,
    ) -> MarketEnvironment:
        """
        评估大盘环境。

        Args:
            index_df: 上证指数日线数据（需含 close/volume 列，按日期正序）
            market_stats: 市场统计 {up_count, down_count, limit_up, limit_down, total}
        """
        env = MarketEnvironment()
        if index_df is None or len(index_df) < 30:
            env.is_tradable = False
            env.reasons.append("指数数据不足30天")
            return env

        close = index_df["close"].astype(float)
        volume = (
            index_df["volume"].astype(float) if "volume" in index_df.columns else None
        )
        latest = close.iloc[-1]

        # === 1. 指数位置评分 (30分) ===
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]

        pos_score = 0.0
        if latest > ma5:
            pos_score += 10
        if latest > ma10:
            pos_score += 10
        if latest > ma20:
            pos_score += 10
            env.ma20_above = True

        # === 2. 趋势动能评分 (25分) ===
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9).mean()
        macd_val = (dif - dea) * 2

        trend_score = 0.0
        if dif.iloc[-1] > dea.iloc[-1]:
            trend_score += 12
            env.macd_bullish = True
        if dif.iloc[-1] > 0:
            trend_score += 8
        if macd_val.iloc[-1] > macd_val.iloc[-2]:
            trend_score += 5  # MACD 柱放大

        # === 3. 市场宽度评分 (25分) ===
        width_score = 0.0
        if market_stats:
            up = market_stats.get("up_count", 0)
            down = market_stats.get("down_count", 1)
            total = market_stats.get("total", 1)
            limit_up = market_stats.get("limit_up", 0)
            limit_down = market_stats.get("limit_down", 0)

            ad_ratio = up / max(down, 1)
            env.advance_decline_ratio = ad_ratio
            env.limit_up_count = limit_up
            env.limit_down_count = limit_down

            # 涨跌比评分
            if ad_ratio >= 2.0:
                width_score += 15
            elif ad_ratio >= 1.2:
                width_score += 10
            elif ad_ratio >= 0.8:
                width_score += 5

            # 涨停/跌停评分
            if limit_up > 80 and limit_down < 20:
                width_score += 10
            elif limit_up > 50:
                width_score += 5
            elif limit_down > 50:
                width_score -= 5
        else:
            width_score = 12  # 无数据时给中间值

        # === 4. 量能配合评分 (20分) ===
        vol_score = 0.0
        if volume is not None and len(volume) >= 20:
            vol_ma20 = volume.rolling(20).mean().iloc[-1]
            vol_latest = volume.iloc[-1]
            vol_ratio = vol_latest / max(vol_ma20, 1)

            if vol_ratio >= 1.3:
                vol_score = 20
            elif vol_ratio >= 1.0:
                vol_score = 15
            elif vol_ratio >= 0.7:
                vol_score = 10
            else:
                vol_score = 5
        else:
            vol_score = 10

        # === 综合评分 ===
        env.score = max(0, min(100, pos_score + trend_score + width_score + vol_score))

        # === 交易决策 ===
        min_score = self.params["min_score_to_trade"]
        weak_score = self.params["weak_market_score"]
        ad_pause = self.params["ad_ratio_pause"]
        ld_pause = self.params["limit_down_pause"]

        if env.score < weak_score:
            env.is_tradable = False
            env.mood = "极度悲观"
            env.reasons.append(f"综合评分 {env.score:.0f} < {weak_score}（弱势阈值）")
        elif env.advance_decline_ratio < ad_pause:
            env.is_tradable = False
            env.mood = "恐慌"
            env.reasons.append(f"涨跌比 {env.advance_decline_ratio:.2f} < {ad_pause}")
        elif env.limit_down_count > ld_pause:
            env.is_tradable = False
            env.mood = "恐慌"
            env.reasons.append(f"跌停 {env.limit_down_count} 家 > {ld_pause}")
        elif env.score < min_score:
            env.is_tradable = False
            env.mood = "偏空"
            env.reasons.append(
                f"综合评分 {env.score:.0f} < {min_score}（最低交易阈值）"
            )
        elif env.score >= self.params["strong_market_score"]:
            env.mood = "强势"
            env.reasons.append(f"综合评分 {env.score:.0f}，强势市场")
        else:
            env.mood = "中性偏多"
            env.reasons.append(f"综合评分 {env.score:.0f}，可交易")

        return env


class CapitalFlowFilter:
    """
    资金流向过滤器 (R-002)

    排除主力净流出的股票，对净流入大的股票加分。
    """

    DEFAULT_PARAMS = {
        "reject_if_outflow": True,
        "strong_inflow_amount": 500e4,
        "strong_inflow_pct": 0.03,
        "bonus_score": 0.1,
    }

    def __init__(self, **overrides):
        self.params = {**self.DEFAULT_PARAMS, **overrides}

    def filter_stock(
        self,
        ts_code: str,
        main_net_inflow: float,
        total_amount: float,
    ) -> StockFilter:
        result = StockFilter(ts_code=ts_code)

        if main_net_inflow < 0 and self.params["reject_if_outflow"]:
            result.passed = False
            result.reject_reasons.append(f"主力净流出 {main_net_inflow/1e4:.0f}万")
            return result

        inflow_pct = main_net_inflow / max(total_amount, 1)
        if (
            main_net_inflow >= self.params["strong_inflow_amount"]
            and inflow_pct >= self.params["strong_inflow_pct"]
        ):
            result.capital_flow_score = self.params["bonus_score"]

        return result


class SectorHeatFilter:
    """
    板块热度过滤器 (R-004)

    只做热门板块的股票，冷门板块直接排除。
    """

    DEFAULT_PARAMS = {
        "top_sector_pct": 0.20,
        "sector_limit_up_bonus": 3,
        "bonus_score": 0.1,
    }

    def __init__(self, **overrides):
        self.params = {**self.DEFAULT_PARAMS, **overrides}

    def filter_stock(
        self,
        ts_code: str,
        sector_rank: Optional[int],
        total_sectors: int,
        sector_limit_up_count: int = 0,
    ) -> StockFilter:
        result = StockFilter(ts_code=ts_code)

        if sector_rank is None:
            return result

        top_n = max(1, int(total_sectors * self.params["top_sector_pct"]))
        if sector_rank > top_n:
            result.passed = False
            result.reject_reasons.append(
                f"板块排名 {sector_rank}/{total_sectors}，不在前 {self.params['top_sector_pct']*100:.0f}%"
            )
            return result

        if sector_limit_up_count >= self.params["sector_limit_up_bonus"]:
            result.sector_heat_score = self.params["bonus_score"]

        return result


class StockPoolFilter:
    """
    股票池过滤器 (R-006)

    仅保留沪深主板，排除 ST、次新股、科创板、北交所。
    """

    @staticmethod
    def is_eligible(
        ts_code: str,
        stock_name: str,
        list_date: Optional[str] = None,
        min_list_days: int = 60,
    ) -> Tuple[bool, str]:
        code = ts_code.split(".")[0] if "." in ts_code else ts_code

        if code.startswith("688"):
            return False, "科创板"

        if code.startswith("8") or code.startswith("4"):
            return False, "北交所"

        if "ST" in stock_name.upper():
            return False, "ST股票"

        if list_date:
            try:
                from datetime import datetime, timedelta

                ld = datetime.strptime(list_date.replace("-", ""), "%Y%m%d")
                if (datetime.now() - ld).days < min_list_days:
                    return False, f"上市不足{min_list_days}天"
            except (ValueError, TypeError):
                pass

        return True, ""


class PositionManager:
    """
    仓位管理器 (R-007)

    按评分排序，选取 Top N 只。
    """

    DEFAULT_PARAMS = {
        "max_positions": 5,
        "min_positions": 3,
    }

    def __init__(self, **overrides):
        self.params = {**self.DEFAULT_PARAMS, **overrides}

    def select_top(
        self,
        candidates: List[Dict],
        score_key: str = "score",
    ) -> List[Dict]:
        sorted_candidates = sorted(
            candidates, key=lambda x: x.get(score_key, 0), reverse=True
        )
        return sorted_candidates[: self.params["max_positions"]]
