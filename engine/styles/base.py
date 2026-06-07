"""
交易风格抽象基类 + 注册表
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

import pandas as pd


@dataclass
class StylePick:
    """风格选出的一只候选"""
    ts_code: str
    name: str
    score: float
    reason: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class StyleExit:
    """单日退出决策"""
    sell: bool                 # True = 今日卖出
    price: float = 0.0         # 卖出价（未含滑点，框架统一加）
    reason: str = "hold"
    stuck: bool = False        # 一字封死无法成交 → 框架顺延持有


@dataclass
class DayContext:
    """某交易日的截面上下文（由 StyleBacktester 构建并传给风格）"""
    date: str                                  # YYYYMMDD
    slices: Dict[str, pd.DataFrame]            # ts_code -> 截至今日的日线切片(升序)
    stock_info: Dict[str, dict]                # ts_code -> {name, industry, list_date}
    market_stats: dict                         # {up_count, down_count, total_amount}
    index_slice: Optional[pd.DataFrame] = None
    fast: Optional[dict] = None                 # 高速索引(numpy列数组+lu/ld/cons)，按需用


class TradingStyle(ABC):
    """
    交易风格基类。

    子类需定义：
      - 元信息：key/name/desc/target_hold_days/top_n/position_pct/max_hold_days
      - select(day): 当日选股
      - should_exit(holding, bar, hold_days, prev_close): 单日退出判断
    """

    key: str = ""
    name: str = ""
    desc: str = ""
    # 诚实判决（8年逐年样本外+真实成本严格验证后的结论，产品风险拦截用）
    # 取值：验证为正 / 打平被动 / 样本外证伪 / 封板幻觉 / 未独立验证
    verdict: str = "未独立验证"
    verdict_note: str = ""          # 一句话事实依据（含关键数字）
    target_hold_days: int = 1       # 目标持仓交易日
    top_n: int = 2                  # 每日最多买入数
    position_pct: float = 0.6       # 总仓位上限（其余留现金）
    max_hold_days: int = 8          # 顺延/兜底强平上限（应 ≥ target_hold_days）
    min_lookback: int = 30          # 选股所需最小历史窗口（指标最长周期）
    emotion_gated: bool = False     # 是否受情绪周期 gating（短线/打板=True）
    needs_slices: bool = True       # False=只用 fast 索引，回测器跳过昂贵切片构建
    entry_at: str = "close"         # 进场价：close=T日收盘 / next_open=T+1开盘(打板防封板买不进)

    def __init__(self, **overrides):
        self.params: dict = dict(overrides)

    def p(self, key: str, default=None):
        return self.params.get(key, default)

    @abstractmethod
    def select(self, day: DayContext) -> List[StylePick]:
        """返回当日候选（已按优先级排序，框架取前 top_n）。"""
        raise NotImplementedError

    @abstractmethod
    def should_exit(
        self, holding: dict, bar: dict, hold_days: int, prev_close: float
    ) -> StyleExit:
        """
        持仓单日退出判断。
          holding: {ts_code, name, buy_px, buy_close_raw, ref_close, shares, score, ...}
          bar:     今日 OHLC dict {open, high, low, close}
          hold_days: 已持有交易日数（买入日记为 1，到今日）
          prev_close: 今日前收（用于涨跌停判定）
        """
        raise NotImplementedError


# ── 注册表 ──────────────────────────────────────────────────

STYLE_REGISTRY: Dict[str, Type[TradingStyle]] = {}


def register_style(cls: Type[TradingStyle]) -> Type[TradingStyle]:
    if not cls.key:
        raise ValueError(f"{cls.__name__} 缺少 key")
    STYLE_REGISTRY[cls.key] = cls
    return cls


def get_style(key: str, **overrides) -> Optional[TradingStyle]:
    cls = STYLE_REGISTRY.get(key)
    return cls(**overrides) if cls else None


def list_styles() -> List[dict]:
    return [
        {
            "key": c.key,
            "name": c.name,
            "desc": c.desc,
            "verdict": c.verdict,
            "verdict_note": c.verdict_note,
            "target_hold_days": c.target_hold_days,
            "top_n": c.top_n,
        }
        for c in STYLE_REGISTRY.values()
    ]
