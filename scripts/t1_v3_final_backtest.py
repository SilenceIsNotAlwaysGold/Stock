"""
T1 v3 策略最终全量回测

基于 H 轮优化结论，选取 Top 方案在全量股票上验证。
不采样，跑全部可交易主板股。

用法: python scripts/t1_v3_final_backtest.py
"""

import sys
import time
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


# ── 数据加载 ──


def load_local_data():
    """加载本地 CSV 数据"""
    print(f"  读取 {ALL_DAILY_FILE} ...")
    all_df = pd.read_csv(ALL_DAILY_FILE, dtype={"ts_code": str})
    all_df["date"] = pd.to_datetime(all_df["date"])
    all_df.sort_values(["ts_code", "date"], inplace=True)

    stock_info = {}
    if STOCK_LIST_FILE.exists():
        sl = pd.read_csv(STOCK_LIST_FILE, dtype={"ts_code": str})
        for _, row in sl.iterrows():
            stock_info[row["ts_code"]] = {
                "name": row.get("name", ""),
                "market": row.get("market", ""),
                "list_date": row.get("list_date", ""),
            }
    print(f"  总行数: {len(all_df):,}, 股票数: {all_df['ts_code'].nunique()}")
    return all_df, stock_info


def filter_mainboard_stocks(stock_info, all_df):
    """筛选主板股票"""
    codes = all_df["ts_code"].unique()
    eligible = []
    for code in codes:
        if code.startswith("3") or code.startswith("8") or code.startswith("4"):
            continue
        if code.startswith("688"):
            continue
        info = stock_info.get(code, {})
        name = info.get("name", "")
        if "ST" in name or "退" in name:
            continue
        eligible.append(code)
    return eligible


def fetch_index_daily(code, start, end):
    """获取指数日线"""
    try:
        df = pro.index_daily(ts_code=code, start_date=start, end_date=end)
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
    except Exception as e:
        print(f"  指数获取失败: {e}")
    return pd.DataFrame()


def build_market_env_cache(index_df):
    """构建大盘环境缓存"""
    mef = MarketEnvironmentFilter()
    cache = {}
    dates = index_df["date"].tolist()
    for i in range(30, len(index_df)):
        dt = dates[i]
        dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        slice_df = index_df.iloc[: i + 1].copy()
        env = mef.evaluate(slice_df)
        cache[dt_str] = env
    return cache


# ── 回测核心 ──


def run_backtest(
    stocks, stock_info, stock_cache, market_cache, params, sell_params=None
):
    """对多只股票运行 v3 策略回测"""
    strategy = T1V3Resonance(**params)
    sell_engine = SmartSellEngine(**(sell_params or {}))
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


def print_detail(label, r):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    if r.total_trades == 0:
        print("  无交易信号")
        return
    plr = calc_profit_loss_ratio(r.trades)
    print(
        f"  交易: {r.total_trades}笔 | 胜率: {r.win_rate*100:.1f}% ({r.win_count}胜/{r.loss_count}负)"
    )
    print(
        f"  总收益: {r.total_return_pct:+.2f}% | 均收益: {r.avg_return_pct:+.2f}% | 盈亏比: {plr:.2f}"
    )
    print(f"  最大单笔: {r.max_return_pct:+.2f}% | 最大亏损: {r.min_return_pct:+.2f}%")
    print(f"  夏普: {r.sharpe_ratio:.2f} | 回撤: {r.max_drawdown_pct:.2f}%")

    reasons = analyze_by_sell_reason(r.trades)
    print(f"\n  卖出原因:")
    print(f"  {'原因':<22} {'次数':>5} {'胜率':>8} {'均收益':>8}")
    for reason, d in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
        wr = d["win"] / d["count"] * 100 if d["count"] > 0 else 0
        avg = d["pnl"] / d["count"] if d["count"] > 0 else 0
        print(f"  {reason:<22} {d['count']:>5} {wr:>7.1f}% {avg:>+7.2f}%")

    monthly = defaultdict(lambda: {"win": 0, "loss": 0, "pnl": 0.0})
    for t in r.trades:
        month = str(t.date)[:7]
        monthly[month]["pnl"] += t.pnl_pct
        if t.is_win:
            monthly[month]["win"] += 1
        else:
            monthly[month]["loss"] += 1
    print(f"\n  月度分布:")
    print(f"  {'月份':<10} {'交易':>5} {'胜率':>8} {'收益':>8}")
    for month in sorted(monthly.keys()):
        d = monthly[month]
        total = d["win"] + d["loss"]
        wr = d["win"] / total * 100 if total > 0 else 0
        print(f"  {month:<10} {total:>5}笔 {wr:>7.1f}% {d['pnl']:>+7.2f}%")


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

G12_SELL = {"take_profit_pct": 0.05, "stop_loss_pct": -0.03}


def with_g12(**overrides):
    return {**G12_BASE, **overrides}


# ── 最终方案 ──

FINAL_CONFIGS = [
    {
        "label": "A: G12基线",
        "params": with_g12(),
        "sell_params": {**G12_SELL},
    },
    {
        "label": "B: RSI<70 (H10最优收益)",
        "params": with_g12(rsi_max=70),
        "sell_params": {**G12_SELL},
    },
    {
        "label": "C: 量比>1.5 (H11最优胜率)",
        "params": with_g12(min_volume_ratio=1.5),
        "sell_params": {**G12_SELL},
    },
    {
        "label": "D: RSI<65 (H9最优夏普)",
        "params": with_g12(rsi_max=65),
        "sell_params": {**G12_SELL},
    },
    {
        "label": "E: RSI<70+量比>1.5 (组合)",
        "params": with_g12(rsi_max=70, min_volume_ratio=1.5),
        "sell_params": {**G12_SELL},
    },
    {
        "label": "F: RSI<65+量比>1.5 (保守组合)",
        "params": with_g12(rsi_max=65, min_volume_ratio=1.5),
        "sell_params": {**G12_SELL},
    },
    {
        "label": "G: RSI<70+止损-4% (激进)",
        "params": with_g12(rsi_max=70),
        "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.04},
    },
    {
        "label": "H: RSI<65+上影<0.5%+止损-2% (稳健)",
        "params": with_g12(rsi_max=65, max_upper_shadow_pct=0.5),
        "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.02},
    },
]


# ── 主流程 ──


def main():
    print("=" * 70)
    print("  T1 v3 最终全量回测")
    print(f"  区间: {START_DATE} ~ {END_DATE}")
    print(f"  全量主板股票，不采样")
    print("=" * 70)

    # 1. 加载数据
    print("\n[1/4] 加载本地数据 ...")
    all_df, stock_info = load_local_data()

    # 2. 筛选 + 预缓存（全量，不采样）
    print("\n[2/4] 筛选可交易股票 & 预缓存 ...")
    eligible = filter_mainboard_stocks(stock_info, all_df)
    print(f"  主板股票: {len(eligible)} 只")

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
    print(f"  有效股票（>=80天数据）: {len(eligible)} 只")
    del all_df

    # 3. 指数 + 大盘环境
    print("\n[3/4] 拉取指数 & 构建大盘环境缓存 ...")
    idx_start = (
        datetime.strptime(START_DATE, "%Y%m%d") - timedelta(days=150)
    ).strftime("%Y%m%d")
    index_df = fetch_index_daily(INDEX_CODE, idx_start, END_DATE)
    if index_df.empty:
        index_df = fetch_index_daily("000001.SH", idx_start, END_DATE)
    print(f"  指数数据: {len(index_df)} 天")
    market_cache = build_market_env_cache(index_df)
    tradable_days = sum(1 for env in market_cache.values() if env.is_tradable)
    print(f"  大盘可交易天数: {tradable_days}/{len(market_cache)}")

    # 4. 运行最终方案
    print("\n[4/4] 运行最终方案回测 ...")
    print(f"\n  共 {len(FINAL_CONFIGS)} 个方案, {len(eligible)} 只股票\n")

    header = f"  {'方案':<42} {'交易':>5} {'胜率':>6} {'总收益':>8} {'均收益':>7} {'夏普':>6} {'回撤':>8} {'盈亏比':>6}"
    print(header)
    print(f"  {'-'*100}")

    results = []
    for cfg in FINAL_CONFIGS:
        t0 = time.time()
        r = run_backtest(
            stocks=eligible,
            stock_info=stock_info,
            stock_cache=stock_cache,
            market_cache=market_cache,
            params=cfg["params"],
            sell_params=cfg.get("sell_params"),
        )
        elapsed = time.time() - t0
        plr = calc_profit_loss_ratio(r.trades) if r.total_trades > 0 else 0
        results.append((cfg["label"], r, plr))

        if r.total_trades == 0:
            print(f"  {cfg['label']:<42} 无交易")
        else:
            print(
                f"  {cfg['label']:<42} "
                f"{r.total_trades:>4}笔 "
                f"{r.win_rate*100:>5.1f}% "
                f"{r.total_return_pct:>+7.2f}% "
                f"均{r.avg_return_pct:>+5.2f}% "
                f"夏普{r.sharpe_ratio:>5.2f} "
                f"回撤{r.max_drawdown_pct:>6.2f}% "
                f"盈亏比{plr:>4.2f} "
                f"({elapsed:.0f}s)"
            )

    # 5. 综合评分排名
    print(f"\n\n{'='*70}")
    print("  综合评分排名")
    print(f"  评分 = 胜率×0.3 + 夏普归一×0.3 + 总收益归一×0.2 + 盈亏比归一×0.2")
    print(f"{'='*70}")

    scored = []
    for label, r, plr in results:
        if r.total_trades < 10:
            continue
        score = (
            r.win_rate * 0.3
            + min(r.sharpe_ratio / 5.0, 1.0) * 0.3
            + min(r.total_return_pct / 50.0, 1.0) * 0.2
            + min(plr / 3.0, 1.0) * 0.2
        )
        scored.append((label, r, score, plr))

    scored.sort(key=lambda x: x[2], reverse=True)
    print(
        f"\n  {'排名':>4} {'方案':<42} {'综合分':>6} {'交易':>5} {'胜率':>6} {'夏普':>6} {'总收益':>8} {'盈亏比':>6}"
    )
    print(f"  {'-'*90}")
    for i, (label, r, score, plr) in enumerate(scored):
        marker = " ★" if i == 0 else ""
        print(
            f"  {i+1:>4} {label:<42} {score:>5.3f} "
            f"{r.total_trades:>4}笔 "
            f"{r.win_rate*100:>5.1f}% {r.sharpe_ratio:>5.2f} "
            f"{r.total_return_pct:>+7.2f}% {plr:>5.2f}{marker}"
        )

    # 6. 冠军方案详细报告
    if scored:
        best_label, best_r, best_score, _ = scored[0]
        print_detail(f"冠军方案: {best_label}", best_r)

        # 打印 Top 3 交易
        if best_r.trades:
            sorted_trades = sorted(best_r.trades, key=lambda t: t.pnl_pct, reverse=True)
            print(f"\n  Top 5 盈利交易:")
            for t in sorted_trades[:5]:
                print(
                    f"    {str(t.date)[:10]} {t.stock_name:<8} 买{t.buy_price:.2f} 卖{t.sell_price:.2f} {t.pnl_pct:+.2f}% [{t.sell_reason}]"
                )
            print(f"\n  Top 5 亏损交易:")
            for t in sorted_trades[-5:]:
                print(
                    f"    {str(t.date)[:10]} {t.stock_name:<8} 买{t.buy_price:.2f} 卖{t.sell_price:.2f} {t.pnl_pct:+.2f}% [{t.sell_reason}]"
                )

    print("\n全量回测完成!")


if __name__ == "__main__":
    main()
