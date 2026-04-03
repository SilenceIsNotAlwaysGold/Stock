"""
T1 v3 策略 I 轮优化：卖出引擎改进

针对 timeout_30min 退出占89.7%、胜率仅55%的问题，测试多种改进方案。

优化方向：
1. 缩短超时时间（20分钟、15分钟）
2. 收紧止盈止损（3%/2%、4%/-2%）
3. 加入盘中趋势判断（5分钟涨幅、成交量萎缩）
4. 动态止损（跟踪止损）

用法: python -u scripts/t1_v3_i_round_sell_optimize.py
"""

import sys
import time
import random
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tushare as ts
from app.config import settings
from engine.strategies.t1_v3 import T1V3Resonance
from engine.t1_backtest import T1Backtester, BacktestResult
from engine.t1_sell_engine import SmartSellEngine
from engine.t1_filters import MarketEnvironmentFilter, StockPoolFilter

ts.set_token(settings.TUSHARE_TOKEN)
pro = ts.pro_api()

DATA_DIR = ROOT / "data" / "yearly"
ALL_DAILY_FILE = DATA_DIR / "all_stocks_daily.csv"
STOCK_LIST_FILE = DATA_DIR / "stock_list.csv"

START_DATE = "20250225"
END_DATE = "20260225"
INDEX_CODE = "000300.SH"
MAX_STOCKS = 1000  # 1000股采样，速度和代表性平衡


def flush_print(msg):
    print(msg)
    sys.stdout.flush()


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


def build_market_env_cache(index_df):
    mef = MarketEnvironmentFilter(min_score_to_trade=40)
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
    stocks, stock_info, stock_cache, market_cache, params, sell_params, label=""
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
                "market_bullish": env.is_tradable and env.score >= 50,
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


def analyze_by_sell_reason(trades):
    reasons = defaultdict(lambda: {"count": 0, "win": 0, "pnl": 0.0})
    for t in trades:
        reasons[t.sell_reason]["count"] += 1
        reasons[t.sell_reason]["pnl"] += t.pnl_pct
        if t.is_win:
            reasons[t.sell_reason]["win"] += 1
    return dict(reasons)


# ── G12 基线参数 ──

G12_BASE = {
    "min_resonance": 2,
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

G12_SELL = {
    "take_profit_pct": 0.05,
    "stop_loss_pct": -0.03,
    "open_sell_threshold": 0.005,
}


# ── I 轮卖出引擎优化方案 ──

SELL_CONFIGS = [
    {
        "label": "I0: G12基线",
        "sell_params": {**G12_SELL},
    },
    # 1. 收紧止盈止损
    {
        "label": "I1: 止盈3% 止损-2%",
        "sell_params": {
            "take_profit_pct": 0.03,
            "stop_loss_pct": -0.02,
            "open_sell_threshold": 0.005,
        },
    },
    {
        "label": "I2: 止盈4% 止损-2%",
        "sell_params": {
            "take_profit_pct": 0.04,
            "stop_loss_pct": -0.02,
            "open_sell_threshold": 0.005,
        },
    },
    {
        "label": "I3: 止盈3% 止损-2.5%",
        "sell_params": {
            "take_profit_pct": 0.03,
            "stop_loss_pct": -0.025,
            "open_sell_threshold": 0.005,
        },
    },
    # 2. 调整开盘卖出阈值
    {
        "label": "I4: 开盘卖阈值1%",
        "sell_params": {
            "take_profit_pct": 0.05,
            "stop_loss_pct": -0.03,
            "open_sell_threshold": 0.01,
        },
    },
    {
        "label": "I5: 开盘卖阈值2%",
        "sell_params": {
            "take_profit_pct": 0.05,
            "stop_loss_pct": -0.03,
            "open_sell_threshold": 0.02,
        },
    },
    {
        "label": "I6: 开盘卖阈值0%（取消）",
        "sell_params": {
            "take_profit_pct": 0.05,
            "stop_loss_pct": -0.03,
            "open_sell_threshold": 0.0,
        },
    },
    # 3. 组合优化
    {
        "label": "I7: 止盈3% 止损-2% 开盘1%",
        "sell_params": {
            "take_profit_pct": 0.03,
            "stop_loss_pct": -0.02,
            "open_sell_threshold": 0.01,
        },
    },
    {
        "label": "I8: 止盈4% 止损-2% 开盘1%",
        "sell_params": {
            "take_profit_pct": 0.04,
            "stop_loss_pct": -0.02,
            "open_sell_threshold": 0.01,
        },
    },
    {
        "label": "I9: 止盈3% 止损-2.5% 开盘1.5%",
        "sell_params": {
            "take_profit_pct": 0.03,
            "stop_loss_pct": -0.025,
            "open_sell_threshold": 0.015,
        },
    },
    # 4. 激进止盈
    {
        "label": "I10: 止盈2% 止损-2%",
        "sell_params": {
            "take_profit_pct": 0.02,
            "stop_loss_pct": -0.02,
            "open_sell_threshold": 0.005,
        },
    },
    {
        "label": "I11: 止盈2.5% 止损-2%",
        "sell_params": {
            "take_profit_pct": 0.025,
            "stop_loss_pct": -0.02,
            "open_sell_threshold": 0.005,
        },
    },
]


def main():
    flush_print("=" * 70)
    flush_print("  T1 v3 I 轮优化：卖出引擎改进")
    flush_print(f"  区间: {START_DATE} ~ {END_DATE}")
    flush_print(f"  样本: {MAX_STOCKS} 只股票")
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

    # 3. 指数 + 大盘环境
    flush_print("\n[3/4] 拉取指数 & 构建大盘环境缓存 ...")
    idx_start = (
        datetime.strptime(START_DATE, "%Y%m%d") - timedelta(days=150)
    ).strftime("%Y%m%d")
    index_df = fetch_index_daily(INDEX_CODE, idx_start, END_DATE)
    if index_df.empty:
        index_df = fetch_index_daily("000001.SH", idx_start, END_DATE)
    flush_print(f"  指数数据: {len(index_df)} 天")
    market_cache = build_market_env_cache(index_df)
    tradable_days = sum(1 for env in market_cache.values() if env.is_tradable)
    flush_print(f"  大盘可交易天数: {tradable_days}/{len(market_cache)}")

    # 4. 运行方案
    flush_print(f"\n[4/4] 运行 {len(SELL_CONFIGS)} 个卖出引擎方案 ...")
    flush_print(f"  共 {len(eligible)} 只股票\n")

    header = f"  {'方案':<32} {'交易':>5} {'胜率':>6} {'总收益':>8} {'均收益':>7} {'夏普':>6} {'回撤':>8} {'盈亏比':>6}"
    flush_print(header)
    flush_print(f"  {'-'*90}")

    results = []
    for cfg in SELL_CONFIGS:
        t0 = time.time()
        r = run_backtest(
            stocks=eligible,
            stock_info=stock_info,
            stock_cache=stock_cache,
            market_cache=market_cache,
            params=G12_BASE,
            sell_params=cfg["sell_params"],
            label=cfg["label"][:10],
        )
        elapsed = time.time() - t0
        plr = calc_profit_loss_ratio(r.trades) if r.total_trades > 0 else 0
        results.append((cfg["label"], r, plr, cfg["sell_params"]))

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
    flush_print(f"  评分 = 胜率×0.35 + 夏普归一×0.25 + 总收益归一×0.2 + 盈亏比归一×0.2")
    flush_print(f"{'='*70}")

    scored = []
    for label, r, plr, sell_params in results:
        if r.total_trades < 20:
            continue
        score = (
            r.win_rate * 0.35
            + min(r.sharpe_ratio / 5.0, 1.0) * 0.25
            + min(r.total_return_pct / 50.0, 1.0) * 0.2
            + min(plr / 3.0, 1.0) * 0.2
        )
        scored.append((label, r, score, plr, sell_params))

    scored.sort(key=lambda x: x[2], reverse=True)
    flush_print(
        f"\n  {'排名':>4} {'方案':<32} {'综合分':>6} {'交易':>5} {'胜率':>6} {'夏普':>6} {'总收益':>8} {'盈亏比':>6}"
    )
    flush_print(f"  {'-'*90}")
    for i, (label, r, score, plr, _) in enumerate(scored):
        marker = " ★" if i == 0 else ""
        flush_print(
            f"  {i+1:>4} {label:<32} {score:>5.3f} "
            f"{r.total_trades:>4}笔 "
            f"{r.win_rate*100:>5.1f}% {r.sharpe_ratio:>5.2f} "
            f"{r.total_return_pct:>+7.2f}% {plr:>5.2f}{marker}"
        )

    # 6. 冠军方案卖出原因分析
    if scored:
        best_label, best_r, best_score, _, best_sell = scored[0]
        flush_print(f"\n{'='*70}")
        flush_print(f"  冠军方案: {best_label}")
        flush_print(f"  参数: {best_sell}")
        flush_print(f"{'='*70}")
        flush_print(
            f"  交易: {best_r.total_trades}笔 | 胜率: {best_r.win_rate*100:.1f}%"
        )
        flush_print(
            f"  总收益: {best_r.total_return_pct:+.2f}% | 夏普: {best_r.sharpe_ratio:.2f}"
        )

        reasons = analyze_by_sell_reason(best_r.trades)
        flush_print(f"\n  卖出原因分布:")
        flush_print(f"  {'原因':<22} {'次数':>5} {'占比':>6} {'胜率':>8} {'均收益':>8}")
        for reason, d in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
            wr = d["win"] / d["count"] * 100 if d["count"] > 0 else 0
            avg = d["pnl"] / d["count"] if d["count"] > 0 else 0
            pct = d["count"] / best_r.total_trades * 100
            flush_print(
                f"  {reason:<22} {d['count']:>5} {pct:>5.1f}% {wr:>7.1f}% {avg:>+7.2f}%"
            )

    flush_print("\nI 轮卖出引擎优化完成!")


if __name__ == "__main__":
    main()
