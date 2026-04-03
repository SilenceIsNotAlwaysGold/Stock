#!/usr/bin/env python3
"""
T1 v4 蓄势隔夜策略 - 回测验证

任务T4：1000股快速验证 + 多阈值对比
- 使用 T1V4Accumulation 策略 + T1V4SellEngine 卖出引擎
- 测试评分阈值 55/60/65/70/75
- 含月度分布、卖出原因分析
"""

import sys
import time
import random
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import tushare as ts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.strategies.t1_v4 import T1V4Accumulation
from engine.t1_v4_sell import T1V4SellEngine
from engine.t1_filters import StockPoolFilter, MarketEnvironmentFilter
from app.config import Settings

# ── 配置 ──
settings = Settings()
START_DATE = "20250225"
END_DATE = "20260225"
MAX_STOCKS = 1000
INDEX_CODE = "399006.SZ"

ALL_DAILY_FILE = PROJECT_ROOT / "data" / "yearly" / "all_stocks_daily.csv"
STOCK_LIST_FILE = PROJECT_ROOT / "data" / "stock_list.csv"

ts.set_token(settings.TUSHARE_TOKEN)
pro = ts.pro_api()

# 测试的评分阈值
SCORE_THRESHOLDS = [55, 60, 65, 70, 75]


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
    for col in ["open", "high", "low", "close", "volume"]:
        if col in all_df.columns:
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")

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


def run_v4_backtest(
    stocks, stock_info, stock_cache, market_cache, score_threshold, label=""
):
    """运行 v4 策略回测"""
    strategy = T1V4Accumulation(score_threshold=score_threshold)
    sell_engine = T1V4SellEngine(
        take_profit_pct=0.03,
        stop_loss_pct=-0.02,
        limit_up_pct=0.098,
    )

    trades = []
    stock_count = 0

    for code in stocks:
        df = stock_cache.get(code)
        if df is None:
            continue
        stock_count += 1
        info = stock_info.get(code, {})
        name = info.get("name", code)

        for i in range(60, len(df) - 1):
            df_slice = df.iloc[: i + 1].copy()
            date_str = str(df.iloc[i]["date"])[:10]

            # 构建 market context
            env = market_cache.get(date_str)
            if env is not None:
                ctx = {
                    "market_bullish": env.is_tradable and env.score >= 50,
                    "market_score": env.score,
                    "market_mood": env.mood,
                }
            else:
                ctx = {"market_bullish": None}

            # 策略信号
            sig = strategy.signal(df_slice, context=ctx)
            if sig.action != "BUY" or sig.confidence < 0.5:
                continue

            # 买入价 = 当天收盘价
            buy_price = float(df.iloc[i]["close"])
            if buy_price <= 0:
                continue

            # 次日数据 → 卖出决策
            next_day = df.iloc[i + 1]
            decision = sell_engine.decide(
                buy_price=buy_price,
                next_open=float(next_day["open"]),
                next_high=float(next_day["high"]),
                next_low=float(next_day["low"]),
                next_close=float(next_day["close"]),
            )

            trades.append(
                {
                    "date": date_str,
                    "ts_code": code,
                    "stock_name": name,
                    "buy_price": buy_price,
                    "sell_price": decision.sell_price,
                    "sell_reason": decision.sell_reason,
                    "pnl_pct": decision.pnl_pct,
                    "is_win": decision.pnl_pct > 0,
                    "score": sig.metadata.get("total_score", 0),
                    "trend_score": sig.metadata.get("trend", 0),
                    "volume_score": sig.metadata.get("volume", 0),
                    "position_score": sig.metadata.get("position", 0),
                    "market_score_dim": sig.metadata.get("market", 0),
                }
            )

    return trades


def calc_stats(trades):
    """计算回测统计指标"""
    if not trades:
        return {
            "total": 0,
            "wins": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "sharpe": 0,
            "max_dd": 0,
            "plr": 0,
            "max_pnl": 0,
            "min_pnl": 0,
        }
    pnls = [t["pnl_pct"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses_vals = [abs(p) for p in pnls if p <= 0]
    wins_vals = [p for p in pnls if p > 0]
    avg_win = np.mean(wins_vals) if wins_vals else 0
    avg_loss = np.mean(losses_vals) if losses_vals else 0.01

    # 夏普比率
    sharpe = 0
    if len(pnls) > 1:
        std = np.std(pnls)
        if std > 0:
            sharpe = round(np.mean(pnls) / std * np.sqrt(250), 2)

    # 最大回撤
    cumulative = np.cumsum(pnls)
    peak = np.maximum.accumulate(cumulative)
    drawdown = cumulative - peak
    max_dd = round(float(np.min(drawdown)), 2) if len(drawdown) > 0 else 0

    return {
        "total": len(trades),
        "wins": wins,
        "win_rate": round(wins / len(trades) * 100, 1),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(np.mean(pnls), 3),
        "sharpe": sharpe,
        "max_dd": max_dd,
        "plr": round(avg_win / max(avg_loss, 0.01), 2),
        "max_pnl": round(max(pnls), 2),
        "min_pnl": round(min(pnls), 2),
    }


def analyze_monthly(trades):
    """月度分析"""
    if not trades:
        return []
    monthly = {}
    for t in trades:
        month = t["date"][:7]
        if month not in monthly:
            monthly[month] = []
        monthly[month].append(t)

    results = []
    for month in sorted(monthly.keys()):
        mt = monthly[month]
        wins = sum(1 for t in mt if t["is_win"])
        total = len(mt)
        total_pnl = sum(t["pnl_pct"] for t in mt)
        results.append(
            {
                "month": month,
                "trades": total,
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
                "total_pnl": round(total_pnl, 2),
            }
        )
    return results


def analyze_sell_reasons(trades):
    """卖出原因分析"""
    if not trades:
        return []
    reasons = {}
    for t in trades:
        r = t["sell_reason"]
        if r not in reasons:
            reasons[r] = {"count": 0, "pnls": []}
        reasons[r]["count"] += 1
        reasons[r]["pnls"].append(t["pnl_pct"])

    results = []
    for reason, data in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
        pnls = data["pnls"]
        wins = sum(1 for p in pnls if p > 0)
        results.append(
            {
                "reason": reason,
                "count": data["count"],
                "pct": round(data["count"] / len(trades) * 100, 1),
                "win_rate": round(wins / len(pnls) * 100, 1),
                "avg_pnl": round(np.mean(pnls), 3),
            }
        )
    return results


def analyze_score_distribution(trades):
    """评分分布分析"""
    if not trades:
        return []
    buckets = [(55, 60), (60, 65), (65, 70), (70, 75), (75, 80), (80, 100)]
    results = []
    for lo, hi in buckets:
        bt = [t for t in trades if lo <= t["score"] < hi]
        if not bt:
            continue
        wins = sum(1 for t in bt if t["is_win"])
        total_pnl = sum(t["pnl_pct"] for t in bt)
        results.append(
            {
                "range": f"{lo}-{hi}",
                "count": len(bt),
                "win_rate": round(wins / len(bt) * 100, 1),
                "avg_pnl": round(total_pnl / len(bt), 3),
            }
        )
    return results


def main():
    flush_print("=" * 80)
    flush_print("  T1 v4 蓄势隔夜策略 - 回测验证 (T4)")
    flush_print(f"  区间: {START_DATE} ~ {END_DATE}")
    flush_print(f"  样本: {MAX_STOCKS} 只股票")
    flush_print(f"  测试阈值: {SCORE_THRESHOLDS}")
    flush_print("=" * 80)

    # 1. 加载数据
    flush_print("\n[1/4] 加载本地数据 ...")
    all_df, stock_info = load_local_data()

    # 2. 筛选 + 采样
    flush_print("\n[2/4] 筛选可交易股票 ...")
    eligible = filter_mainboard_stocks(stock_info, all_df)
    flush_print(f"  主板股票: {len(eligible)} 只")

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

    # 3. 指数数据 + 大盘环境
    flush_print("\n[3/4] 拉取指数数据 & 构建大盘环境 ...")
    idx_start = (
        datetime.strptime(START_DATE, "%Y%m%d") - timedelta(days=150)
    ).strftime("%Y%m%d")
    index_df = fetch_index_daily(INDEX_CODE, idx_start, END_DATE)
    if index_df.empty:
        index_df = fetch_index_daily("000001.SH", idx_start, END_DATE)
    flush_print(f"  指数数据: {len(index_df)} 天")

    market_cache = build_market_env_cache(index_df, min_score=40)
    flush_print(f"  大盘环境缓存: {len(market_cache)} 天")

    # 4. 多阈值回测
    flush_print(f"\n[4/4] 运行 {len(SCORE_THRESHOLDS)} 个评分阈值方案 ...")
    flush_print(f"  共 {len(eligible)} 只股票\n")

    header = f"  {'阈值':>4} {'交易':>5} {'胜率':>6} {'总收益':>8} {'均收益':>7} {'夏普':>6} {'回撤':>8} {'盈亏比':>6}"
    flush_print(header)
    flush_print(f"  {'-'*72}")

    all_results = []
    for threshold in SCORE_THRESHOLDS:
        t0 = time.time()
        trades = run_v4_backtest(
            stocks=eligible,
            stock_info=stock_info,
            stock_cache=stock_cache,
            market_cache=market_cache,
            score_threshold=threshold,
            label=f"阈值{threshold}",
        )
        elapsed = time.time() - t0
        stats = calc_stats(trades)
        all_results.append((threshold, trades, stats))

        if stats["total"] == 0:
            flush_print(f"  {threshold:>4} 无交易 ({elapsed:.0f}s)")
        else:
            flush_print(
                f"  {threshold:>4} "
                f"{stats['total']:>4}笔 "
                f"{stats['win_rate']:>5.1f}% "
                f"{stats['total_pnl']:>+7.2f}% "
                f"均{stats['avg_pnl']:>+5.3f}% "
                f"夏普{stats['sharpe']:>5.2f} "
                f"回撤{stats['max_dd']:>6.2f}% "
                f"盈亏比{stats['plr']:>4.2f} "
                f"({elapsed:.0f}s)"
            )

    # === 综合评分排名 ===
    flush_print(f"\n\n{'='*80}")
    flush_print("  综合评分排名")
    flush_print(f"  评分 = 胜率×0.35 + 夏普归一×0.30 + 盈亏比归一×0.20 + 交易频率×0.15")
    flush_print(f"{'='*80}")

    scored = []
    for threshold, trades, stats in all_results:
        if stats["total"] < 20:
            continue
        freq_score = min(stats["total"] / 200, 1.0)
        score = (
            (stats["win_rate"] / 100) * 0.35
            + min(stats["sharpe"] / 5.0, 1.0) * 0.30
            + min(stats["plr"] / 3.0, 1.0) * 0.20
            + freq_score * 0.15
        )
        scored.append((threshold, trades, stats, score))

    scored.sort(key=lambda x: x[3], reverse=True)
    flush_print(
        f"\n  {'排名':>4} {'阈值':>4} {'综合分':>6} {'交易':>5} {'胜率':>6} {'夏普':>6} {'盈亏比':>6}"
    )
    flush_print(f"  {'-'*56}")
    for i, (threshold, _, stats, score) in enumerate(scored):
        marker = " ★" if i == 0 else ""
        flush_print(
            f"  {i+1:>4} {threshold:>4} {score:>5.3f} "
            f"{stats['total']:>4}笔 "
            f"{stats['win_rate']:>5.1f}% "
            f"夏普{stats['sharpe']:>5.2f} "
            f"盈亏比{stats['plr']:>4.2f}{marker}"
        )

    # === 冠军方案详细分析 ===
    if scored:
        best_threshold, best_trades, best_stats, best_score = scored[0]
        flush_print(f"\n{'='*80}")
        flush_print(f"  冠军方案: 评分阈值 >= {best_threshold}")
        flush_print(f"{'='*80}")
        flush_print(
            f"  交易: {best_stats['total']}笔 | 胜率: {best_stats['win_rate']}% | 盈亏比: {best_stats['plr']}"
        )
        flush_print(
            f"  总收益: {best_stats['total_pnl']:+.2f}% | 夏普: {best_stats['sharpe']} | 回撤: {best_stats['max_dd']}%"
        )
        flush_print(
            f"  单笔最大收益: {best_stats['max_pnl']:+.2f}% | 单笔最大亏损: {best_stats['min_pnl']:+.2f}%"
        )

        # 月度分析
        monthly = analyze_monthly(best_trades)
        flush_print(f"\n  ── 月度分布 ──")
        flush_print(f"  {'月份':>8} {'交易':>5} {'胜率':>6} {'收益':>8}")
        flush_print(f"  {'-'*32}")
        for m in monthly:
            flush_print(
                f"  {m['month']:>8} {m['trades']:>4}笔 "
                f"{m['win_rate']:>5.1f}% {m['total_pnl']:>+7.2f}%"
            )

        # 卖出原因分析
        sell_reasons = analyze_sell_reasons(best_trades)
        flush_print(f"\n  ── 卖出原因分布 ──")
        flush_print(f"  {'原因':<22} {'次数':>5} {'占比':>6} {'胜率':>6} {'均收益':>8}")
        flush_print(f"  {'-'*54}")
        for sr in sell_reasons:
            flush_print(
                f"  {sr['reason']:<22} {sr['count']:>4}次 "
                f"{sr['pct']:>5.1f}% {sr['win_rate']:>5.1f}% "
                f"{sr['avg_pnl']:>+7.3f}%"
            )

        # 评分分布分析
        score_dist = analyze_score_distribution(best_trades)
        flush_print(f"\n  ── 评分分布 ──")
        flush_print(f"  {'评分区间':<10} {'交易':>5} {'胜率':>6} {'均收益':>8}")
        flush_print(f"  {'-'*36}")
        for sd in score_dist:
            flush_print(
                f"  {sd['range']:<10} {sd['count']:>4}笔 "
                f"{sd['win_rate']:>5.1f}% {sd['avg_pnl']:>+7.3f}%"
            )

        # 维度得分分析
        flush_print(f"\n  ── 各维度平均得分 ──")
        if best_trades:
            avg_trend = np.mean([t["trend_score"] for t in best_trades])
            avg_volume = np.mean([t["volume_score"] for t in best_trades])
            avg_position = np.mean([t["position_score"] for t in best_trades])
            avg_market = np.mean([t["market_score_dim"] for t in best_trades])
            avg_total = np.mean([t["score"] for t in best_trades])
            flush_print(
                f"  趋势: {avg_trend:.1f}/30 | 量价: {avg_volume:.1f}/25 | "
                f"位置: {avg_position:.1f}/25 | 市场: {avg_market:.1f}/20 | 总分: {avg_total:.1f}/100"
            )

    # === 与 v3 对比 ===
    flush_print(f"\n{'='*80}")
    flush_print("  v4 vs v3 对比（1000股样本）")
    flush_print(f"{'='*80}")
    flush_print(f"  {'指标':<12} {'v3 (G12+I5)':>14} {'v4 (最佳)':>14}")
    flush_print(f"  {'-'*44}")
    if scored:
        b = scored[0][2]
        flush_print(f"  {'交易次数':<12} {'102':>14} {b['total']:>14}")
        flush_print(f"  {'胜率':<12} {'56.9%':>14} {str(b['win_rate'])+'%':>14}")
        flush_print(f"  {'夏普比率':<12} {'3.06':>14} {b['sharpe']:>14}")
        flush_print(
            f"  {'总收益':<12} {'+44.03%':>14} {str(round(b['total_pnl'],2))+'%':>14}"
        )
        flush_print(f"  {'最大回撤':<12} {'-7.73%':>14} {str(b['max_dd'])+'%':>14}")
        flush_print(f"  {'盈亏比':<12} {'1.58':>14} {b['plr']:>14}")

    flush_print(f"\nv4 回测验证完成!")


if __name__ == "__main__":
    main()
