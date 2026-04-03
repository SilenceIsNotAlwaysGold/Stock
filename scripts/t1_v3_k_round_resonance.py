#!/usr/bin/env python3
"""
T1 v3 K 轮优化：提高买入门槛（共振数优化）
基于 J4 最优大盘过滤（评分>=70）
测试不同共振数要求（2/3/4个子策略触发）
"""

import sys
import time
import random
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import tushare as ts

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.strategies.t1_v3 import T1V3Resonance
from engine.t1_sell_engine import SmartSellEngine
from engine.t1_backtest import T1Backtester, BacktestResult
from engine.t1_filters import StockPoolFilter, MarketEnvironmentFilter
from app.config import Settings

# ── 配置 ──
settings = Settings()
START_DATE = "20250225"
END_DATE = "20260225"
MAX_STOCKS = 1000
INDEX_CODE = "399006.SZ"  # 创业板指

ALL_DAILY_FILE = PROJECT_ROOT / "data" / "yearly" / "all_stocks_daily.csv"
STOCK_LIST_FILE = PROJECT_ROOT / "data" / "stock_list.csv"

# Tushare
ts.set_token(settings.TUSHARE_TOKEN)
pro = ts.pro_api()


def flush_print(msg):
    print(msg, flush=True)


def load_local_data():
    flush_print(f"  读取 {ALL_DAILY_FILE} ...")
    all_df = pd.read_csv(ALL_DAILY_FILE, dtype={"ts_code": str})
    if "trade_date" in all_df.columns:
        all_df = all_df.rename(columns={"trade_date": "date", "vol": "volume"})
    all_df["date"] = all_df["date"].astype(str).str.replace("-", "")
    all_df["date"] = pd.to_datetime(all_df["date"], format="%Y%m%d").dt.strftime(
        "%Y-%m-%d"
    )

    stock_info = {}
    if STOCK_LIST_FILE.exists():
        sl = pd.read_csv(STOCK_LIST_FILE, dtype={"ts_code": str})
        for _, row in sl.iterrows():
            stock_info[row["ts_code"]] = {
                "name": str(row.get("name", "")),
                "market": str(row.get("market", "")),
                "list_date": str(row.get("list_date", "")),
            }
    flush_print(f"  总行数: {len(all_df):,}, 股票数: {all_df['ts_code'].nunique()}")
    return all_df, stock_info


def filter_mainboard_stocks(stock_info, all_df):
    codes = all_df["ts_code"].unique()
    eligible = []
    for code in codes:
        info = stock_info.get(code, {})
        name = info.get("name", "")
        list_date = info.get("list_date", "")
        ok, _ = StockPoolFilter.is_eligible(code, name, list_date)
        if ok:
            eligible.append(code)
    return eligible


def fetch_index_daily(code, start, end):
    try:
        df = pro.index_daily(ts_code=code, start_date=start, end_date=end)
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
    except Exception as e:
        flush_print(f"  指数获取失败: {e}")
    return pd.DataFrame()


def build_market_env_cache(index_df, min_score=40):
    mef = MarketEnvironmentFilter(min_score_to_trade=min_score)
    cache = {}
    dates = index_df["date"].tolist()
    for i in range(30, len(index_df)):
        dt = dates[i]
        dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        slice_df = index_df.iloc[: i + 1].copy()
        env = mef.evaluate(slice_df)
        cache[dt_str] = env
    return cache


def run_backtest(
    stocks,
    stock_info,
    stock_cache,
    market_cache,
    params,
    sell_params,
    market_threshold=70,
    label="",
):
    strategy = T1V3Resonance(**params)
    sell_engine = SmartSellEngine(**sell_params)
    backtester = T1Backtester(strategy=strategy, sell_engine=sell_engine)

    all_trades = []
    for code in stocks:
        df = stock_cache.get(code)
        if df is None:
            continue
        info = stock_info.get(code, {})
        name = info.get("name", code)

        def context_fn(date_val, df_slice):
            dt_str = str(date_val)[:10]
            env = market_cache.get(dt_str)
            if env is None:
                return {"market_bullish": None}
            return {
                "market_bullish": env.is_tradable and env.score >= market_threshold,
                "market_score": env.score,
                "market_mood": env.mood,
            }

        result = backtester.run(
            df, stock_name=name, ts_code=code, context_fn=context_fn
        )
        all_trades.extend(result.trades)

    combined = BacktestResult(
        strategy_name=strategy.name, period=f"{START_DATE}~{END_DATE}"
    )
    combined.trades = all_trades
    combined.total_trades = len(all_trades)

    if all_trades:
        pnls = [t.pnl_pct for t in all_trades]
        combined.win_count = sum(1 for t in all_trades if t.is_win)
        combined.loss_count = combined.total_trades - combined.win_count
        combined.win_rate = combined.win_count / combined.total_trades
        combined.total_return_pct = round(sum(pnls), 2)
        combined.avg_return_pct = round(np.mean(pnls), 2)
        combined.max_return_pct = round(max(pnls), 2)
        combined.min_return_pct = round(min(pnls), 2)
        cumulative = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative)
        drawdown = cumulative - peak
        combined.max_drawdown_pct = round(float(np.min(drawdown)), 2)
        if len(pnls) > 1:
            std = np.std(pnls)
            if std > 0:
                combined.sharpe_ratio = round(np.mean(pnls) / std * np.sqrt(250), 2)
    return combined


def calc_profit_loss_ratio(trades):
    wins = [t.pnl_pct for t in trades if t.is_win]
    losses = [abs(t.pnl_pct) for t in trades if not t.is_win]
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0.01
    return round(avg_win / max(avg_loss, 0.01), 2)


# ── G12 基线参数 + I5 卖出引擎 + J4 大盘过滤 ──

G12_BASE = {
    "min_resonance": 2,  # 将在K轮中测试2/3/4
    "rsi_max": 68,
    "require_bullish_market": True,
    "max_change_pct": 5.0,
    "max_dist_ma60_pct": 10.0,
    "require_ma20_rising": True,
    "max_atr_pct": 4.0,
    "min_close_strength": None,
    "min_volume_ratio": 1.2,
    "min_turnover_pct": None,
    "max_turnover_pct": None,
    "min_market_cap": None,
    "max_market_cap": None,
    "max_prev_change_pct": 3.0,
    "require_macd_above_zero": False,
    "min_change_pct": None,
    "max_upper_shadow_pct": 1.0,
    "max_consecutive_up": 2,
    "require_close_above_vwap": False,
}

I5_SELL = {"take_profit_pct": 0.05, "stop_loss_pct": -0.03, "open_sell_threshold": 0.02}

J4_MARKET = {"min_score": 40, "threshold": 70}


# ── K 轮共振数优化方案 ──

RESONANCE_CONFIGS = [
    {"label": "K0: 基线(2/4共振)", "min_resonance": 2, "extra_filters": {}},
    {"label": "K1: 3/4共振", "min_resonance": 3, "extra_filters": {}},
    {"label": "K2: 4/4共振", "min_resonance": 4, "extra_filters": {}},
    {"label": "K3: 3/4 + RSI<65", "min_resonance": 3, "extra_filters": {"rsi_max": 65}},
    {
        "label": "K4: 3/4 + 量比>1.5",
        "min_resonance": 3,
        "extra_filters": {"min_volume_ratio": 1.5},
    },
    {
        "label": "K5: 3/4 + 前日涨幅<2%",
        "min_resonance": 3,
        "extra_filters": {"max_prev_change_pct": 2.0},
    },
    {
        "label": "K6: 3/4 + 连涨<=1天",
        "min_resonance": 3,
        "extra_filters": {"max_consecutive_up": 1},
    },
    {
        "label": "K7: 3/4 + 上影线<0.5%",
        "min_resonance": 3,
        "extra_filters": {"max_upper_shadow_pct": 0.5},
    },
    {
        "label": "K8: 3/4 + RSI<65 + 量比>1.5",
        "min_resonance": 3,
        "extra_filters": {"rsi_max": 65, "min_volume_ratio": 1.5},
    },
    {
        "label": "K9: 3/4 + 前日涨幅<2% + 连涨<=1",
        "min_resonance": 3,
        "extra_filters": {"max_prev_change_pct": 2.0, "max_consecutive_up": 1},
    },
    {
        "label": "K10: 4/4 + RSI<65",
        "min_resonance": 4,
        "extra_filters": {"rsi_max": 65},
    },
    {
        "label": "K11: 4/4 + 量比>1.5",
        "min_resonance": 4,
        "extra_filters": {"min_volume_ratio": 1.5},
    },
]


def main():
    flush_print("=" * 70)
    flush_print("  T1 v3 K 轮优化：买入门槛提升（共振数优化）")
    flush_print(f"  区间: {START_DATE} ~ {END_DATE}")
    flush_print(f"  样本: {MAX_STOCKS} 只股票")
    flush_print(f"  大盘过滤: J4 (评分>={J4_MARKET['threshold']})")
    flush_print("=" * 70)

    # 1. 加载数据
    flush_print("\n[1/4] 加载本地数据 ...")
    all_df, stock_info = load_local_data()

    # 2. 筛选 + 采样
    flush_print("\n[2/4] 筛选可交易股票 & 预缓存 ...")
    eligible = filter_mainboard_stocks(stock_info, all_df)
    flush_print(f"  主板股票: {len(eligible)} 只")

    num_cols = ["open", "high", "low", "close", "volume"]
    for col in num_cols:
        if col in all_df.columns:
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")
    grouped = all_df.groupby("ts_code")
    stock_cache = {}
    for code in eligible:
        if code not in grouped.groups:
            continue
        sub = grouped.get_group(code).sort_values("date").reset_index(drop=True)
        if len(sub) >= 80:
            stock_cache[code] = sub
    eligible = list(stock_cache.keys())
    flush_print(f"  有效股票（>=80天数据）: {len(eligible)} 只")

    if MAX_STOCKS > 0 and len(eligible) > MAX_STOCKS:
        random.seed(42)
        eligible = random.sample(eligible, MAX_STOCKS)
        stock_cache = {k: v for k, v in stock_cache.items() if k in set(eligible)}
        flush_print(f"  采样后: {len(eligible)} 只")
    del all_df

    # 3. 指数数据
    flush_print("\n[3/4] 拉取指数数据 ...")
    idx_start = (
        datetime.strptime(START_DATE, "%Y%m%d") - timedelta(days=150)
    ).strftime("%Y%m%d")
    index_df = fetch_index_daily(INDEX_CODE, idx_start, END_DATE)
    if index_df.empty:
        index_df = fetch_index_daily("000001.SH", idx_start, END_DATE)
    flush_print(f"  指数数据: {len(index_df)} 天")

    market_cache = build_market_env_cache(index_df, J4_MARKET["min_score"])
    tradable_days = sum(
        1
        for env in market_cache.values()
        if env.is_tradable and env.score >= J4_MARKET["threshold"]
    )
    flush_print(f"  可交易天数: {tradable_days}/307")

    # 4. 运行方案
    flush_print(f"\n[4/4] 运行 {len(RESONANCE_CONFIGS)} 个共振数优化方案 ...")
    flush_print(f"  共 {len(eligible)} 只股票\n")

    header = f"  {'方案':<32} {'交易':>5} {'胜率':>6} {'总收益':>8} {'均收益':>7} {'夏普':>6} {'回撤':>8} {'盈亏比':>6}"
    flush_print(header)
    flush_print(f"  {'-'*92}")

    results = []
    for cfg in RESONANCE_CONFIGS:
        t0 = time.time()

        params = G12_BASE.copy()
        params["min_resonance"] = cfg["min_resonance"]
        params.update(cfg["extra_filters"])

        r = run_backtest(
            stocks=eligible,
            stock_info=stock_info,
            stock_cache=stock_cache,
            market_cache=market_cache,
            params=params,
            sell_params=I5_SELL,
            market_threshold=J4_MARKET["threshold"],
            label=cfg["label"][:10],
        )
        elapsed = time.time() - t0
        plr = calc_profit_loss_ratio(r.trades) if r.total_trades > 0 else 0
        results.append((cfg["label"], r, plr, cfg))

        if r.total_trades == 0:
            flush_print(f"  {cfg['label']:<32} 无交易")
        else:
            flush_print(
                f"  {cfg['label']:<32} "
                f"{r.total_trades:>4}笔 "
                f"{r.win_rate*100:>5.1f}% "
                f"{r.total_return_pct:>+7.2f}% "
                f"均{r.avg_return_pct:>+5.2f}% "
                f"夏普{r.sharpe_ratio:>5.2f} "
                f"回撤{r.max_drawdown_pct:>6.2f}% "
                f"盈亏比{plr:>4.2f} "
                f"({elapsed:.0f}s)"
            )

    # 5. 综合评分
    flush_print(f"\n\n{'='*70}")
    flush_print("  综合评分排名")
    flush_print(f"  评分 = 胜率×0.35 + 夏普归一×0.30 + 盈亏比归一×0.20 + 交易频率×0.15")
    flush_print(f"{'='*70}")

    scored = []
    for label, r, plr, cfg in results:
        if r.total_trades < 10:
            continue
        trade_freq = r.total_trades / tradable_days
        freq_score = min(trade_freq / 0.3, 1.0)  # 期望每3天1笔

        score = (
            r.win_rate * 0.35
            + min(r.sharpe_ratio / 5.0, 1.0) * 0.30
            + min(plr / 3.0, 1.0) * 0.20
            + freq_score * 0.15
        )
        scored.append((label, r, score, plr, cfg))

    scored.sort(key=lambda x: x[2], reverse=True)
    flush_print(
        f"\n  {'排名':>4} {'方案':<32} {'综合分':>6} {'交易':>5} {'胜率':>6} {'夏普':>6} {'盈亏比':>6}"
    )
    flush_print(f"  {'-'*92}")
    for i, (label, r, score, plr, _) in enumerate(scored):
        marker = " ★" if i == 0 else ""
        flush_print(
            f"  {i+1:>4} {label:<32} {score:>5.3f} "
            f"{r.total_trades:>4}笔 "
            f"{r.win_rate*100:>5.1f}% {r.sharpe_ratio:>5.2f} "
            f"{plr:>5.2f}{marker}"
        )

    # 6. 冠军方案详情
    if scored:
        best_label, best_r, best_score, best_plr, best_cfg = scored[0]
        flush_print(f"\n{'='*70}")
        flush_print(f"  冠军方案: {best_label}")
        flush_print(
            f"  参数: min_resonance={best_cfg['min_resonance']}, 额外过滤={best_cfg['extra_filters']}"
        )
        flush_print(f"{'='*70}")
        flush_print(
            f"  交易: {best_r.total_trades}笔 | 胜率: {best_r.win_rate*100:.1f}% | 盈亏比: {best_plr:.2f}"
        )
        flush_print(
            f"  总收益: {best_r.total_return_pct:+.2f}% | 夏普: {best_r.sharpe_ratio:.2f} | 回撤: {best_r.max_drawdown_pct:.2f}%"
        )

    flush_print("\nK 轮共振数优化完成!")


if __name__ == "__main__":
    main()
