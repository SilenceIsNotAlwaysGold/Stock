"""
T+1 策略 v3 - 高胜率隔夜策略

核心逻辑：多策略共振 + 大盘过滤 + RSI防超买 + MA20趋势 + ATR波动控制
         + 量比确认 + 上影线过滤 + 前日涨幅控制 + 连涨天数限制

4 个子策略：
- BreakoutNewHigh: 首次突破20日新高 + 量价确认
- MAAlignmentSurge: 均线多头排列 + 首次放量上涨
- PullbackBounce: 强势回踩MA5反弹
- VolumeExpansion: 缩量整理后放量突破

入场条件（必须同时满足）：
1. 至少 2 个子策略同时触发（共振）
2. 大盘当天上涨（指数环境正向）
3. RSI < 68（防超买回调）
4. MA20 上升趋势（趋势确认）
5. ATR(14)/close < 4%（过滤高波动）
6. 量比 > 1.2（量能确认）
7. 上影线 < 1%（避免高位抛压，最强单因子）
8. 前日涨幅 < 3%（避免追高连板）
9. 连涨天数 <= 2（避免过热追高）

回测验证（500只主板股，2025.02-2026.02，G12最优组合）：
- 63笔交易，66.7%胜率，+26.54%总收益，夏普3.70，回撤-4.36%
- 相比基线(59.6%胜率)提升7.1个百分点，回撤从-11.03%降至-4.36%
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from engine.base import BaseStrategy, StrategySignal
from engine.registry import StrategyRegistry


class T1V3SubSignal:
    """子策略信号（内部使用，不注册到全局）"""

    def __init__(self, name: str, hit: bool, confidence: float = 0.0, reason: str = ""):
        self.name = name
        self.hit = hit
        self.confidence = confidence
        self.reason = reason


def _check_breakout_new_high(df: pd.DataFrame, i: int) -> T1V3SubSignal:
    """子策略A: 首次突破20日新高 + 量价确认"""
    row = df.iloc[i]
    prev = df.iloc[i - 1]
    buy_price = float(row["close"])
    prev_close = float(prev["close"])
    change_pct = (buy_price - prev_close) / prev_close * 100

    if change_pct < 2 or change_pct > 7:
        return T1V3SubSignal("breakout_new_high", False)

    # 20日最高价（不含当天）
    high_20d = float(df["high"].iloc[max(0, i - 20) : i].max())
    if buy_price <= high_20d:
        return T1V3SubSignal("breakout_new_high", False, reason="未突破20日新高")

    # 量比
    vol_avg = float(df["volume"].iloc[max(0, i - 20) : i].mean())
    vol_ratio = float(row["volume"]) / max(vol_avg, 1)
    if vol_ratio < 1.3:
        return T1V3SubSignal("breakout_new_high", False, reason="量比不足")

    # 收盘在日内高位
    day_range = float(row["high"]) - float(row["low"])
    close_pos = (buy_price - float(row["low"])) / max(day_range, 0.01)
    upper_shadow = (float(row["high"]) - buy_price) / max(buy_price, 0.01)
    if close_pos < 0.85 or upper_shadow > 0.01:
        return T1V3SubSignal("breakout_new_high", False, reason="收盘位置不够强")

    conf = min(0.9, 0.6 + vol_ratio * 0.05 + close_pos * 0.1)
    return T1V3SubSignal(
        "breakout_new_high",
        True,
        conf,
        f"突破20日新高，涨{change_pct:.1f}%，量比{vol_ratio:.1f}",
    )


def _check_ma_alignment_surge(df: pd.DataFrame, i: int) -> T1V3SubSignal:
    """子策略B: 均线多头排列 + 首次放量上涨"""
    row = df.iloc[i]
    prev = df.iloc[i - 1]
    buy_price = float(row["close"])
    prev_close = float(prev["close"])
    change_pct = (buy_price - prev_close) / prev_close * 100

    if change_pct < 2 or change_pct > 6:
        return T1V3SubSignal("ma_alignment_surge", False)

    ma5 = float(df["close"].rolling(5).mean().iloc[i])
    ma10 = float(df["close"].rolling(10).mean().iloc[i])
    ma20 = float(df["close"].rolling(20).mean().iloc[i])

    if not (buy_price > ma5 > ma10 > ma20):
        return T1V3SubSignal("ma_alignment_surge", False, reason="均线非多头排列")

    # MACD 多头
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    dif = (ema12 - ema26).iloc[i]
    dea = (ema12 - ema26).ewm(span=9).mean().iloc[i]
    if dif <= dea:
        return T1V3SubSignal("ma_alignment_surge", False, reason="MACD非多头")

    # 量比
    vol_avg = float(df["volume"].iloc[max(0, i - 20) : i].mean())
    vol_ratio = float(row["volume"]) / max(vol_avg, 1)
    if vol_ratio < 1.5:
        return T1V3SubSignal("ma_alignment_surge", False, reason="量比不足1.5")

    # 连涨天数 <= 2
    streak = 0
    for j in range(i, max(i - 10, 0), -1):
        if float(df.iloc[j]["close"]) > float(df.iloc[j - 1]["close"]):
            streak += 1
        else:
            break
    if streak > 2:
        return T1V3SubSignal("ma_alignment_surge", False, reason=f"连涨{streak}天过热")

    conf = min(0.85, 0.55 + vol_ratio * 0.05 + change_pct * 0.03)
    return T1V3SubSignal(
        "ma_alignment_surge",
        True,
        conf,
        f"均线多头+放量，涨{change_pct:.1f}%，量比{vol_ratio:.1f}",
    )


def _check_pullback_bounce(df: pd.DataFrame, i: int) -> T1V3SubSignal:
    """子策略C: 强势回踩MA5反弹"""
    row = df.iloc[i]
    prev = df.iloc[i - 1]
    buy_price = float(row["close"])
    prev_close = float(prev["close"])
    change_pct = (buy_price - prev_close) / prev_close * 100

    if change_pct < 2 or change_pct > 5:
        return T1V3SubSignal("pullback_bounce", False)

    ma5 = float(df["close"].rolling(5).mean().iloc[i])
    if buy_price <= ma5:
        return T1V3SubSignal("pullback_bounce", False, reason="未站上MA5")

    # 前一天低点不破MA5
    prev_ma5 = float(df["close"].rolling(5).mean().iloc[i - 1])
    if float(prev["low"]) < prev_ma5 * 0.99:
        return T1V3SubSignal("pullback_bounce", False, reason="前日跌破MA5")

    # 前5日有过回调（高点到前收盘跌幅>=2%）
    high_5d = float(df["high"].iloc[max(0, i - 5) : i].max())
    pullback = (high_5d - prev_close) / high_5d * 100
    if pullback < 2:
        return T1V3SubSignal("pullback_bounce", False, reason="无明显回调")

    # 量比
    vol_avg = float(df["volume"].iloc[max(0, i - 20) : i].mean())
    vol_ratio = float(row["volume"]) / max(vol_avg, 1)
    if vol_ratio < 1.2:
        return T1V3SubSignal("pullback_bounce", False, reason="量比不足")

    # MACD 多头
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    dif = (ema12 - ema26).iloc[i]
    dea = (ema12 - ema26).ewm(span=9).mean().iloc[i]
    if dif <= dea:
        return T1V3SubSignal("pullback_bounce", False, reason="MACD非多头")

    conf = min(0.85, 0.55 + pullback * 0.03 + vol_ratio * 0.05)
    return T1V3SubSignal(
        "pullback_bounce",
        True,
        conf,
        f"回踩MA5反弹，涨{change_pct:.1f}%，回调{pullback:.1f}%",
    )


def _check_volume_expansion(df: pd.DataFrame, i: int) -> T1V3SubSignal:
    """子策略D: 缩量整理后放量突破"""
    row = df.iloc[i]
    prev = df.iloc[i - 1]
    buy_price = float(row["close"])
    prev_close = float(prev["close"])
    change_pct = (buy_price - prev_close) / prev_close * 100

    if change_pct < 3 or change_pct > 7:
        return T1V3SubSignal("volume_expansion", False)

    ma20 = float(df["close"].rolling(20).mean().iloc[i])
    if buy_price <= ma20:
        return T1V3SubSignal("volume_expansion", False, reason="未站上MA20")

    # 前3天缩量
    vol_3d = float(df["volume"].iloc[max(0, i - 3) : i].mean())
    vol_20d = float(df["volume"].iloc[max(0, i - 20) : i].mean())
    if vol_3d / max(vol_20d, 1) >= 0.8:
        return T1V3SubSignal("volume_expansion", False, reason="前3天未缩量")

    # 今天放量
    vol_ratio = float(row["volume"]) / max(vol_20d, 1)
    if vol_ratio < 1.8:
        return T1V3SubSignal("volume_expansion", False, reason="放量不够")

    # 收盘在高位
    day_range = float(row["high"]) - float(row["low"])
    close_pos = (buy_price - float(row["low"])) / max(day_range, 0.01)
    if close_pos < 0.85:
        return T1V3SubSignal("volume_expansion", False, reason="收盘位置不够强")

    conf = min(0.9, 0.6 + vol_ratio * 0.05)
    return T1V3SubSignal(
        "volume_expansion",
        True,
        conf,
        f"缩量后放量突破，涨{change_pct:.1f}%，量比{vol_ratio:.1f}",
    )


@StrategyRegistry.register
class T1V3Resonance(BaseStrategy):
    """
    T+1 v3 高胜率隔夜策略 - 多策略共振

    入场条件：
    1. 至少 2 个子策略同时触发（共振）
    2. RSI(14) < 68（防超买）
    3. 大盘环境正向（通过 context 传入）
    4. 当日涨幅 < 5%（温和上涨更安全）
    5. 距 MA60 < 10%（不追涨幅过大的股票）
    6. MA20 上升趋势（趋势确认）
    7. ATR(14)/close < 4%（过滤高波动）
    8. 量比 > 1.2（量能确认）
    9. 上影线 < 1%（避免高位抛压，回测最强单因子）
    10. 前日涨幅 < 3%（避免追高连板）
    11. 连涨天数 <= 2（避免过热追高）

    回测（500只主板股，2025.02-2026.02，G12最优组合）：
    - 63笔交易，66.7%胜率，+26.54%总收益
    - 夏普比率 3.70，最大回撤 -4.36%
    - 每笔均收益 +0.42%
    """

    name = "t1_v3_resonance"
    description = "v3高胜率隔夜：多策略共振+RSI防超买+大盘过滤+涨幅控制"
    category = "t1_overnight"

    default_params: Dict[str, Any] = {
        "min_resonance": 2,  # 最少共振策略数
        "rsi_max": 68,  # RSI 上限
        "require_bullish_market": True,  # 是否要求大盘正向
        "max_change_pct": 5.0,  # 当日最大涨幅%
        "max_dist_ma60_pct": 10.0,  # 距MA60最大偏离%
        "require_ma20_rising": True,  # 要求MA20上升趋势（趋势确认）
        "max_atr_pct": 4.0,  # ATR(14)/close 最大波动率%（控制波动风险）
        "min_close_strength": None,  # 收盘强度（回测验证拖累表现，关闭）
        "min_turnover_pct": None,  # 最低换手率%（暂不启用，数据不全）
        "max_turnover_pct": None,  # 最高换手率%
        "min_volume_ratio": 1.2,  # 最低量比（量能确认，1.2为最优值）
        "min_market_cap": None,  # 最低流通市值（亿元）
        "max_market_cap": None,  # 最高流通市值（亿元）
        # ── 高胜率过滤器（G12组合，回测验证66.7%胜率） ──
        "max_prev_change_pct": 3.0,  # 前一日最大涨幅%（避免追高连板，G2验证）
        "require_macd_above_zero": False,  # MACD>0（回测验证反而拖累，不启用）
        "min_change_pct": None,  # 当日最低涨幅%（过滤弱势股）
        "max_upper_shadow_pct": 1.0,  # 上影线最大比例%（最强单因子，G5验证65.2%胜率）
        "max_consecutive_up": 2,  # 最大连涨天数（避免追高，G6验证）
        "require_close_above_vwap": False,  # 收盘>均价线（回测验证无效，不启用）
    }

    SUB_CHECKS = [
        _check_breakout_new_high,
        _check_ma_alignment_surge,
        _check_pullback_bounce,
        _check_volume_expansion,
    ]

    def signal(
        self, df: pd.DataFrame, context: Optional[Dict] = None
    ) -> StrategySignal:
        if len(df) < 60:
            return StrategySignal("HOLD", 0.0, "数据不足60天")

        i = len(df) - 1
        ctx = context or {}

        # === 大盘过滤 ===
        if self.get_param("require_bullish_market"):
            market_bullish = ctx.get("market_bullish", None)
            if market_bullish is False:
                return StrategySignal("HOLD", 0.0, "大盘偏弱，跳过")

        # === RSI 过滤 ===
        close = df["close"].astype(float)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = 100 - (100 / (1 + gain / loss_s))
        rsi_val = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50

        rsi_max = self.get_param("rsi_max")
        if rsi_val >= rsi_max:
            return StrategySignal(
                "HOLD", 0.0, f"RSI {rsi_val:.0f} >= {rsi_max}，超买风险"
            )

        # === 涨幅过滤 ===
        latest_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])
        change_pct = (latest_close - prev_close) / prev_close * 100
        max_change = self.get_param("max_change_pct")
        if change_pct >= max_change:
            return StrategySignal(
                "HOLD", 0.0, f"涨幅 {change_pct:.1f}% >= {max_change}%，涨幅过大"
            )

        # === MA60 距离过滤 ===
        if len(close) >= 60:
            ma60 = float(close.rolling(60).mean().iloc[-1])
            if ma60 > 0:
                dist_ma60 = (latest_close - ma60) / ma60 * 100
                max_dist = self.get_param("max_dist_ma60_pct")
                if dist_ma60 >= max_dist:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"距MA60 {dist_ma60:.1f}% >= {max_dist}%，偏离过大",
                    )

        # === MA20 趋势过滤 ===
        if self.get_param("require_ma20_rising") and len(close) >= 25:
            ma20 = close.rolling(20).mean()
            ma20_now = float(ma20.iloc[-1])
            ma20_5ago = float(ma20.iloc[-5])
            if ma20_now <= ma20_5ago:
                return StrategySignal("HOLD", 0.0, "MA20未上升，趋势不明确")

        # === 波动率过滤（ATR） ===
        max_atr_pct = self.get_param("max_atr_pct")
        if max_atr_pct and len(df) >= 20:
            high_s = df["high"].astype(float)
            low_s = df["low"].astype(float)
            tr = pd.concat(
                [
                    high_s - low_s,
                    (high_s - close.shift(1)).abs(),
                    (low_s - close.shift(1)).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr14 = float(tr.rolling(14).mean().iloc[-1])
            atr_pct = atr14 / latest_close * 100
            if atr_pct >= max_atr_pct:
                return StrategySignal(
                    "HOLD",
                    0.0,
                    f"ATR波动率 {atr_pct:.1f}% >= {max_atr_pct}%，波动过大",
                )

        # === 收盘强度过滤 ===
        min_cs = self.get_param("min_close_strength")
        if min_cs and len(df) >= 5:
            strengths = []
            for k in range(max(0, i - 2), i + 1):
                r = df.iloc[k]
                rng = float(r["high"]) - float(r["low"])
                if rng > 0:
                    strengths.append((float(r["close"]) - float(r["low"])) / rng)
            if strengths:
                avg_strength = np.mean(strengths)
                if avg_strength < min_cs:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"近3日收盘强度 {avg_strength:.2f} < {min_cs}，收盘偏弱",
                    )

        # === 换手率过滤 ===
        min_tr = self.get_param("min_turnover_pct")
        max_tr = self.get_param("max_turnover_pct")
        if min_tr or max_tr:
            turnover = ctx.get("turnover_pct")
            if turnover is not None:
                if min_tr and turnover < min_tr:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"换手率 {turnover:.1f}% < {min_tr}%，不够活跃",
                    )
                if max_tr and turnover > max_tr:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"换手率 {turnover:.1f}% > {max_tr}%，可能出货",
                    )

        # === 量比过滤 ===
        min_vr = self.get_param("min_volume_ratio")
        if min_vr and len(df) >= 6:
            vol = df["volume"].astype(float)
            vol_today = float(vol.iloc[-1])
            vol_5avg = float(vol.iloc[-6:-1].mean())
            if vol_5avg > 0:
                volume_ratio = vol_today / vol_5avg
                if volume_ratio < min_vr:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"量比 {volume_ratio:.2f} < {min_vr}，缩量无力",
                    )

        # === 前一日涨幅过滤（避免追高连板） ===
        max_prev_chg = self.get_param("max_prev_change_pct")
        if max_prev_chg is not None and len(close) >= 3:
            prev2_close = float(close.iloc[-3])
            if prev2_close > 0:
                prev_change = (prev_close - prev2_close) / prev2_close * 100
                if prev_change >= max_prev_chg:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"前日涨幅 {prev_change:.1f}% >= {max_prev_chg}%，避免追高",
                    )

        # === MACD 0轴上方过滤（中期趋势确认） ===
        if self.get_param("require_macd_above_zero") and len(close) >= 30:
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            dif_val = float((ema12 - ema26).iloc[-1])
            if dif_val <= 0:
                return StrategySignal(
                    "HOLD", 0.0, f"MACD DIF={dif_val:.3f}<=0，中期趋势偏弱"
                )

        # === 最低涨幅过滤（过滤弱势股） ===
        min_change = self.get_param("min_change_pct")
        if min_change is not None:
            if change_pct < min_change:
                return StrategySignal(
                    "HOLD",
                    0.0,
                    f"涨幅 {change_pct:.1f}% < {min_change}%，涨幅不足",
                )

        # === 上影线过滤（避免高位抛压） ===
        max_shadow = self.get_param("max_upper_shadow_pct")
        if max_shadow is not None:
            high_val = float(df["high"].iloc[-1])
            if latest_close > 0:
                upper_shadow_pct = (high_val - latest_close) / latest_close * 100
                if upper_shadow_pct > max_shadow:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"上影线 {upper_shadow_pct:.2f}% > {max_shadow}%，抛压明显",
                    )

        # === 连涨天数过滤（避免追高） ===
        max_consec = self.get_param("max_consecutive_up")
        if max_consec is not None and len(close) >= 10:
            consec_up = 0
            for j in range(len(close) - 1, 0, -1):
                if float(close.iloc[j]) > float(close.iloc[j - 1]):
                    consec_up += 1
                else:
                    break
            if consec_up > max_consec:
                return StrategySignal(
                    "HOLD",
                    0.0,
                    f"连涨 {consec_up} 天 > {max_consec}，追高风险",
                )

        # === 收盘价>均价线过滤（强势确认） ===
        if self.get_param("require_close_above_vwap"):
            row_last = df.iloc[-1]
            vwap_approx = (
                float(row_last["open"])
                + float(row_last["high"])
                + float(row_last["low"])
                + float(row_last["close"])
            ) / 4
            if latest_close < vwap_approx:
                return StrategySignal(
                    "HOLD",
                    0.0,
                    f"收盘 {latest_close:.2f} < 均价 {vwap_approx:.2f}，尾盘偏弱",
                )

        # === 流通市值过滤 ===
        min_cap = self.get_param("min_market_cap")
        max_cap = self.get_param("max_market_cap")
        if min_cap or max_cap:
            market_cap = ctx.get("market_cap_yi")
            if market_cap is not None:
                if min_cap and market_cap < min_cap:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"流通市值 {market_cap:.0f}亿 < {min_cap}亿，太小",
                    )
                if max_cap and market_cap > max_cap:
                    return StrategySignal(
                        "HOLD",
                        0.0,
                        f"流通市值 {market_cap:.0f}亿 > {max_cap}亿，弹性不足",
                    )

        # === 运行 4 个子策略 ===
        sub_signals: List[T1V3SubSignal] = []
        for check_fn in self.SUB_CHECKS:
            sig = check_fn(df, i)
            if sig.hit:
                sub_signals.append(sig)

        # === 共振判断 ===
        min_res = self.get_param("min_resonance")
        if len(sub_signals) < min_res:
            names = [s.name for s in sub_signals] if sub_signals else ["无"]
            return StrategySignal(
                "HOLD",
                0.0,
                f"共振不足: {len(sub_signals)}/{min_res}，命中: {','.join(names)}",
            )

        # === 生成买入信号 ===
        avg_conf = np.mean([s.confidence for s in sub_signals])
        resonance_bonus = min(0.15, (len(sub_signals) - min_res) * 0.05)
        final_conf = min(0.95, avg_conf + resonance_bonus)

        reasons = [s.reason for s in sub_signals]
        strategy_names = [s.name for s in sub_signals]

        return StrategySignal(
            "BUY",
            final_conf,
            f"共振{len(sub_signals)}策略: {'; '.join(reasons)}",
            metadata={
                "criterion": "v3_resonance",
                "sub_strategies": strategy_names,
                "resonance_count": len(sub_signals),
                "rsi": rsi_val,
                "change_pct": float(
                    (float(df.iloc[-1]["close"]) - float(df.iloc[-2]["close"]))
                    / float(df.iloc[-2]["close"])
                    * 100
                ),
                "volume_ratio": float(df.iloc[-1]["volume"])
                / max(float(df["volume"].iloc[-21:-1].mean()), 1),
            },
        )
