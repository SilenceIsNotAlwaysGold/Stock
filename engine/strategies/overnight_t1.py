"""
T+1 隔夜策略 - 尾盘买入早盘卖出

3个子策略:
- T1LimitReopenReseal: 涨停回封
- T1TailSurgeVolume: 尾盘拉升
- T1SectorLeader: 板块龙头
"""

from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class T1LimitReopenReseal(BaseStrategy):
    """涨停回封策略: 日内触及涨停→回落→再封板，量比>1.5"""

    name = "t1_limit_reopen_reseal"
    description = "涨停回封：触及涨停后回落再封板，量比>1.5"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "volume_ratio_min": 1.5,
        "limit_up_pct": 0.098,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        if len(df) < 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        latest = df.iloc[-1]
        prev_close = df.iloc[-2]["close"]
        if prev_close == 0:
            return StrategySignal("HOLD", 0.0, "前收盘价异常")

        limit_pct = self.get_param("limit_up_pct")
        vol_min = self.get_param("volume_ratio_min")

        # 计算涨幅
        change_pct = (latest["close"] - prev_close) / prev_close
        high_pct = (latest["high"] - prev_close) / prev_close

        # 量比：当天成交量 / 前N天平均成交量
        today_vol = latest["volume"]
        prev_vol_avg = df["volume"].iloc[:-1].mean() if len(df) > 1 else today_vol
        vol_ratio = today_vol / max(prev_vol_avg, 1)

        # 条件: 最高价触及涨停 + 收盘封板 + 量比达标
        touched_limit = high_pct >= limit_pct
        closed_at_limit = change_pct >= limit_pct
        had_pullback = latest["low"] < latest["high"] * 0.97

        if touched_limit and closed_at_limit and had_pullback and vol_ratio >= vol_min:
            confidence = min(0.9, 0.6 + vol_ratio * 0.1)
            turnover = latest.get("turnover_rate", 0) or 0
            return StrategySignal(
                "BUY",
                confidence,
                f"涨停回封，量比{vol_ratio:.1f}，涨幅{change_pct*100:.1f}%",
                metadata={
                    "criterion": "limit_reopen",
                    "volume_ratio": vol_ratio,
                    "change_pct": change_pct * 100,
                    "turnover_rate": turnover,
                },
            )

        return StrategySignal("HOLD", 0.0, "不满足涨停回封条件")


@StrategyRegistry.register
class T1TailSurgeVolume(BaseStrategy):
    """尾盘拉升策略: 收盘涨3%-7%，量比>2.0，上影线<1%"""

    name = "t1_tail_surge_volume"
    description = "尾盘拉升：收盘涨3%-7%，量比>2.0，上影线<1%"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "change_min": 0.03,
        "change_max": 0.07,
        "volume_ratio_min": 1.3,
        "upper_shadow_max": 0.01,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        if len(df) < 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        latest = df.iloc[-1]
        prev_close = df.iloc[-2]["close"]
        if prev_close == 0:
            return StrategySignal("HOLD", 0.0, "前收盘价异常")

        change_pct = (latest["close"] - prev_close) / prev_close
        upper_shadow = (latest["high"] - latest["close"]) / max(latest["close"], 0.01)

        # 量比：当天成交量 / 前N天平均成交量
        today_vol = latest["volume"]
        prev_vol_avg = df["volume"].iloc[:-1].mean() if len(df) > 1 else today_vol
        vol_ratio = today_vol / max(prev_vol_avg, 1)

        c_min = self.get_param("change_min")
        c_max = self.get_param("change_max")
        v_min = self.get_param("volume_ratio_min")
        u_max = self.get_param("upper_shadow_max")

        if (
            c_min <= change_pct <= c_max
            and vol_ratio >= v_min
            and upper_shadow <= u_max
        ):
            confidence = min(0.85, 0.5 + change_pct * 5)
            turnover = latest.get("turnover_rate", 0) or 0
            return StrategySignal(
                "BUY",
                confidence,
                f"尾盘拉升，涨{change_pct*100:.1f}%，量比{vol_ratio:.1f}，上影线{upper_shadow*100:.2f}%",
                metadata={
                    "criterion": "tail_surge",
                    "volume_ratio": vol_ratio,
                    "change_pct": change_pct * 100,
                    "turnover_rate": turnover,
                },
            )

        return StrategySignal("HOLD", 0.0, "不满足尾盘拉升条件")


@StrategyRegistry.register
class T1SectorLeader(BaseStrategy):
    """板块龙头策略: 所属板块涨幅前3，换手率>5%，涨幅2%-7%"""

    name = "t1_sector_leader"
    description = "板块龙头：板块涨幅前3，换手率>5%，涨幅2%-7%"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "change_min": 0.02,
        "change_max": 0.07,
        "turnover_min": 5.0,
        "sector_rank_max": 3,
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        if len(df) < 5:
            return StrategySignal("HOLD", 0.0, "数据不足")

        latest = df.iloc[-1]
        prev_close = df.iloc[-2]["close"]
        if prev_close == 0:
            return StrategySignal("HOLD", 0.0, "前收盘价异常")

        change_pct = (latest["close"] - prev_close) / prev_close
        turnover = latest.get("turnover_rate", 0) or 0

        # 量比
        n = min(5, len(df))
        vol_recent = df["volume"].tail(n).mean()
        vol_avg = df["volume"].mean()
        vol_ratio = vol_recent / max(vol_avg, 1)

        c_min = self.get_param("change_min")
        c_max = self.get_param("change_max")
        t_min = self.get_param("turnover_min")

        # 板块排名从 context 获取，无 context 时用换手率+涨幅综合判断
        sector_rank = (context or {}).get("sector_rank", None)
        rank_max = self.get_param("sector_rank_max")

        rank_ok = sector_rank is not None and sector_rank <= rank_max
        # 无板块排名时，用高换手率(>8%) + 适中涨幅作为替代条件
        fallback_ok = sector_rank is None and turnover >= 8.0

        if (
            c_min <= change_pct <= c_max
            and turnover >= t_min
            and (rank_ok or fallback_ok)
        ):
            rank_info = (
                f"板块排名{sector_rank}" if sector_rank else f"高换手{turnover:.1f}%"
            )
            confidence = min(0.85, 0.5 + turnover * 0.02)
            return StrategySignal(
                "BUY",
                confidence,
                f"板块龙头，涨{change_pct*100:.1f}%，换手率{turnover:.1f}%，{rank_info}",
                metadata={
                    "criterion": "sector_leader",
                    "volume_ratio": round(vol_ratio, 2),
                    "turnover_rate": turnover,
                    "change_pct": change_pct * 100,
                },
            )

        return StrategySignal("HOLD", 0.0, "不满足板块龙头条件")
