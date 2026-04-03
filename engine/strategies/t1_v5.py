"""
T1 v5 隔夜策略 - 基于公开验证的选股逻辑 + tushare daily_basic 真实数据

两个子策略（硬过滤，非评分）：
A. 尾盘动量：涨幅3-5% + 量比>1.5 + 换手率5-10% + 均线多头 + 流通市值50-200亿
B. RSI(2)超卖反弹：RSI(2)<10 + 趋势向上

数据来源：tushare daily + daily_basic（换手率/量比/流通市值）

参考：
- 东方财富/知乎：尾盘选股条件
- Larry Connors RSI(2) Mean Reversion
- QuantifiedStrategies: Overnight Trading Portfolio
"""

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


@StrategyRegistry.register
class T1V5Overnight(BaseStrategy):
    """
    T+1 v5 隔夜策略

    子策略A - 尾盘动量选股（硬过滤）：
      1. 当日涨幅 3%-5%（pct_chg）
      2. 量比 > 1.5（volume_ratio from daily_basic）
      3. 换手率 5%-10%（turnover_rate from daily_basic）
      4. MA5 > MA10 > MA20（均线多头）
      5. 近3天量能递增
      6. 上影线 < 1%
      7. 流通市值 50亿-200亿（circ_mv from daily_basic）

    子策略B - RSI(2) 超卖反弹：
      1. RSI(2) < 10
      2. 收盘价 > MA60（大趋势向上）
      3. 当日非涨停（可买入）
      4. 流通市值 > 30亿（排除小盘垃圾股）

    任一子策略触发即买入。
    """

    name = "t1_v5_overnight"
    description = "v5隔夜：尾盘动量+RSI超卖反弹，硬过滤选股"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        # 大盘过滤
        "require_bullish_market": True,
        # 子策略A: 尾盘动量
        "enable_momentum": True,
        "min_pct_chg": 3.0,
        "max_pct_chg": 5.0,
        "min_volume_ratio": 1.5,  # 量比下限（tushare volume_ratio）
        "min_turnover_rate": 5.0,  # 换手率下限（%）
        "max_turnover_rate": 10.0,  # 换手率上限（%）
        "require_ma_bullish": True,  # 均线多头
        "require_volume_increase": True,  # 3天量递增
        "max_upper_shadow_pct": 1.0,  # 上影线上限
        "min_circ_mv": 500000.0,  # 流通市值下限（万元）= 50亿
        "max_circ_mv": 2000000.0,  # 流通市值上限（万元）= 200亿
        # 子策略B: RSI超卖反弹
        "enable_rsi_reversion": True,
        "rsi2_threshold": 10,  # RSI(2) < 10 触发
        "rsi_trend_ma": 60,  # 趋势判断均线
        "max_limit_pct": 9.5,  # 非涨停
        "rsi_min_circ_mv": 300000.0,  # RSI策略最低市值（万元）= 30亿
    }

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        if len(df) < 61:
            return StrategySignal("HOLD", 0.0, "数据不足")

        ctx = context or {}

        # === 大盘过滤 ===
        if self.get_param("require_bullish_market"):
            market_bullish = ctx.get("market_bullish", None)
            if market_bullish is False:
                return StrategySignal("HOLD", 0.0, "大盘偏弱")

        i = len(df) - 1
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)
        row = df.iloc[i]

        # 子策略A: 尾盘动量
        sig_a = self._check_momentum(df, i, close, volume, row)

        # 子策略B: RSI(2) 超卖反弹
        sig_b = self._check_rsi_reversion(df, i, close, row)

        # 任一触发
        if sig_a is not None:
            return sig_a
        if sig_b is not None:
            return sig_b

        return StrategySignal("HOLD", 0.0, "无信号")

    def _check_momentum(
        self,
        df: pd.DataFrame,
        i: int,
        close: pd.Series,
        volume: pd.Series,
        row,
    ) -> Optional[StrategySignal]:
        """子策略A: 尾盘动量选股"""
        if not self.get_param("enable_momentum"):
            return None

        # 1. 涨幅 3%-5%
        pct_chg = self._get_pct_chg(df, i)
        min_pct = self.get_param("min_pct_chg")
        max_pct = self.get_param("max_pct_chg")
        if pct_chg is None or not (min_pct <= pct_chg <= max_pct):
            return None

        # 2. 量比 > 1.5（优先用 tushare volume_ratio，否则手动算）
        min_vr = self.get_param("min_volume_ratio")
        if "volume_ratio" in df.columns and pd.notna(row.get("volume_ratio")):
            vol_ratio = float(row["volume_ratio"])
        else:
            if i < 5:
                return None
            vol_today = float(volume.iloc[i])
            vol_5avg = float(volume.iloc[i - 5 : i].mean())
            if vol_5avg <= 0:
                return None
            vol_ratio = vol_today / vol_5avg
        if vol_ratio < min_vr:
            return None

        # 3. 换手率 5%-10%
        min_tr = self.get_param("min_turnover_rate")
        max_tr = self.get_param("max_turnover_rate")
        if "turnover_rate" in df.columns and pd.notna(row.get("turnover_rate")):
            turnover = float(row["turnover_rate"])
            if not (min_tr <= turnover <= max_tr):
                return None
        # 如果没有换手率数据则跳过此过滤

        # 4. 均线多头 MA5 > MA10 > MA20
        if self.get_param("require_ma_bullish"):
            if i < 20:
                return None
            ma5 = float(close.iloc[i - 4 : i + 1].mean())
            ma10 = float(close.iloc[i - 9 : i + 1].mean())
            ma20 = float(close.iloc[i - 19 : i + 1].mean())
            if not (ma5 > ma10 > ma20):
                return None

        # 5. 近3天量能递增
        if self.get_param("require_volume_increase"):
            if i < 3:
                return None
            v1 = float(volume.iloc[i - 2])
            v2 = float(volume.iloc[i - 1])
            v3 = float(volume.iloc[i])
            if not (v3 > v2 > v1):
                return None

        # 6. 上影线 < 1%
        max_shadow = self.get_param("max_upper_shadow_pct")
        high_val = float(row["high"])
        close_val = float(close.iloc[i])
        if close_val > 0:
            shadow_pct = (high_val - close_val) / close_val * 100
            if shadow_pct > max_shadow:
                return None

        # 7. 流通市值 50亿-200亿
        min_mv = self.get_param("min_circ_mv")
        max_mv = self.get_param("max_circ_mv")
        if "circ_mv" in df.columns and pd.notna(row.get("circ_mv")):
            circ_mv = float(row["circ_mv"])
            if not (min_mv <= circ_mv <= max_mv):
                return None

        return StrategySignal(
            "BUY",
            0.80,
            f"动量: 涨{pct_chg:.1f}% 量比{vol_ratio:.1f}",
            metadata={
                "sub_strategy": "momentum",
                "pct_chg": pct_chg,
                "vol_ratio": round(vol_ratio, 2),
                "turnover_rate": (
                    float(row.get("turnover_rate", 0))
                    if "turnover_rate" in df.columns
                    else 0
                ),
                "circ_mv": (
                    float(row.get("circ_mv", 0)) if "circ_mv" in df.columns else 0
                ),
            },
        )

    def _check_rsi_reversion(
        self,
        df: pd.DataFrame,
        i: int,
        close: pd.Series,
        row,
    ) -> Optional[StrategySignal]:
        """子策略B: RSI(2) 超卖反弹"""
        if not self.get_param("enable_rsi_reversion"):
            return None
        if i < 61:
            return None

        # 0. 流通市值 > 30亿（排除垃圾股）
        rsi_min_mv = self.get_param("rsi_min_circ_mv")
        if "circ_mv" in df.columns and pd.notna(row.get("circ_mv")):
            if float(row["circ_mv"]) < rsi_min_mv:
                return None

        # 1. RSI(2) < threshold
        threshold = self.get_param("rsi2_threshold")
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(2).mean()
        loss_s = (-delta.where(delta < 0, 0)).rolling(2).mean()
        rs = gain / loss_s.replace(0, np.nan)
        rsi2 = 100 - (100 / (1 + rs))
        rsi_val = float(rsi2.iloc[i]) if pd.notna(rsi2.iloc[i]) else 50
        if rsi_val >= threshold:
            return None

        # 2. 收盘 > MA60
        ma_period = self.get_param("rsi_trend_ma")
        ma_val = float(close.iloc[i - ma_period + 1 : i + 1].mean())
        current = float(close.iloc[i])
        if current <= ma_val:
            return None

        # 3. 非涨停
        pct_chg = self._get_pct_chg(df, i)
        max_limit = self.get_param("max_limit_pct")
        if pct_chg is not None and pct_chg >= max_limit:
            return None

        # 4. 非大跌
        if pct_chg is not None and pct_chg < -7:
            return None

        return StrategySignal(
            "BUY",
            0.75,
            f"RSI反弹: RSI(2)={rsi_val:.0f} 价格>MA{ma_period}",
            metadata={
                "sub_strategy": "rsi_reversion",
                "rsi2": round(rsi_val, 1),
                "ma_period": ma_period,
            },
        )

    def _get_pct_chg(self, df: pd.DataFrame, i: int) -> Optional[float]:
        """获取当日涨跌幅"""
        if "pct_chg" in df.columns:
            val = df.iloc[i]["pct_chg"]
            if pd.notna(val):
                return float(val)
        close_val = float(df.iloc[i]["close"])
        if i > 0:
            prev = float(df.iloc[i - 1]["close"])
            if prev > 0:
                return (close_val - prev) / prev * 100
        return None
