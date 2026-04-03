"""
T1 v3 策略 H 轮优化 - 卖出引擎 + 买入过滤器联合优化

三阶段：
1. 小样本快扫（50只）→ 找最优方向
2. 中样本验证（200只）→ 确认稳定性
3. 全样本确认（500只）→ 最终结论

用法: python scripts/t1_v3_h_round_optimize.py [--phase 1|2|3] [--stocks N]
"""

import sys
import os
import time
import argparse
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


# ── 数据加载（复用 full_backtest 逻辑） ──


def load_local_data():
    print("  加载本地日线数据 ...")
    df = pd.read_csv(ALL_DAILY_FILE, encoding="utf-8-sig")
    if "trade_date" in df.columns:
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
    df["date"] = df["date"].astype(str).str.replace("-", "")
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    print(f"  日线数据: {len(df)} 条, {df['ts_code'].nunique()} 只股票")

    print("  加载股票列表 ...")
    sl = pd.read_csv(STOCK_LIST_FILE, encoding="utf-8-sig")
    stock_info = {}
    for _, row in sl.iterrows():
        stock_info[row["ts_code"]] = {
            "name": str(row.get("name", "")),
            "industry": str(row.get("industry", "")),
            "market": str(row.get("market", "")),
            "list_date": str(row.get("list_date", "")),
        }
    return df, stock_info


def filter_mainboard_stocks(stock_info, all_df):
    codes = all_df["ts_code"].unique().tolist()
    eligible = []
    for code in codes:
        info = stock_info.get(code, {})
        name = info.get("name", "")
        list_date = info.get("list_date", "")
        ok, _ = StockPoolFilter.is_eligible(code, name, list_date)
        if ok:
            eligible.append(code)
    return eligible


def fetch_index_daily(ts_code, start, end):
    print(f"  拉取指数 {ts_code} 日线 ...")
    df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.sort_values("date").reset_index(drop=True)
    return df


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

    # 汇总
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
    """计算盈亏比"""
    wins = [t.pnl_pct for t in trades if t.is_win]
    losses = [abs(t.pnl_pct) for t in trades if not t.is_win]
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0.01
    return round(avg_win / max(avg_loss, 0.01), 2)


def analyze_by_sell_reason(trades):
    """按卖出原因分析"""
    reasons = defaultdict(lambda: {"count": 0, "win": 0, "pnl": 0.0})
    for t in trades:
        reasons[t.sell_reason]["count"] += 1
        reasons[t.sell_reason]["pnl"] += t.pnl_pct
        if t.is_win:
            reasons[t.sell_reason]["win"] += 1
    return dict(reasons)


def print_result_compact(label, r):
    """紧凑打印结果"""
    if r.total_trades == 0:
        print(f"  {label:<45} 无交易")
        return
    plr = calc_profit_loss_ratio(r.trades)
    print(
        f"  {label:<45} "
        f"{r.total_trades:>4}笔 "
        f"{r.win_rate*100:>5.1f}% "
        f"{r.total_return_pct:>+7.2f}% "
        f"均{r.avg_return_pct:>+5.2f}% "
        f"夏普{r.sharpe_ratio:>5.2f} "
        f"回撤{r.max_drawdown_pct:>6.2f}% "
        f"盈亏比{plr:>4.2f}"
    )


def print_detail(label, r):
    """详细打印含卖出原因分析"""
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

    # 月度分析
    monthly = defaultdict(lambda: {"win": 0, "loss": 0, "pnl": 0.0})
    for t in r.trades:
        month = str(t.date)[:7]
        monthly[month]["pnl"] += t.pnl_pct
        if t.is_win:
            monthly[month]["win"] += 1
        else:
            monthly[month]["loss"] += 1
    print(f"\n  月度:")
    for month in sorted(monthly.keys()):
        d = monthly[month]
        total = d["win"] + d["loss"]
        wr = d["win"] / total * 100 if total > 0 else 0
        print(f"  {month}  {total:>3}笔  {wr:>5.1f}%  {d['pnl']:>+7.2f}%")


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


def build_test_configs():
    """构建 H 轮测试配置"""

    def with_g12(**overrides):
        return {**G12_BASE, **overrides}

    configs = []

    # ── H0: G12 基线 ──
    configs.append(
        {
            "label": "H0: G12基线",
            "params": with_g12(),
            "sell_params": {**G12_SELL},
        }
    )

    # ══════════════════════════════════════════
    # 维度1: 卖出引擎优化（最大优化空间）
    # ══════════════════════════════════════════

    # H1: 止盈线从5%降到3%（更快锁利）
    configs.append(
        {
            "label": "H1: 止盈3%",
            "params": with_g12(),
            "sell_params": {"take_profit_pct": 0.03, "stop_loss_pct": -0.03},
        }
    )

    # H2: 止盈线4%
    configs.append(
        {
            "label": "H2: 止盈4%",
            "params": with_g12(),
            "sell_params": {"take_profit_pct": 0.04, "stop_loss_pct": -0.03},
        }
    )

    # H3: 止损收紧到-2%
    configs.append(
        {
            "label": "H3: 止损-2%",
            "params": with_g12(),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.02},
        }
    )

    # H4: 止损放宽到-4%
    configs.append(
        {
            "label": "H4: 止损-4%",
            "params": with_g12(),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.04},
        }
    )

    # H5: 开盘卖出阈值从0.5%提高到1%（只有涨1%以上才开盘卖）
    configs.append(
        {
            "label": "H5: 开盘卖阈值1%",
            "params": with_g12(),
            "sell_params": {
                "take_profit_pct": 0.05,
                "stop_loss_pct": -0.03,
                "open_sell_threshold": 0.01,
            },
        }
    )

    # H6: 开盘卖出阈值0%（任何盈利都卖）
    configs.append(
        {
            "label": "H6: 开盘卖阈值0%",
            "params": with_g12(),
            "sell_params": {
                "take_profit_pct": 0.05,
                "stop_loss_pct": -0.03,
                "open_sell_threshold": 0.0,
            },
        }
    )

    # H7: 止盈4% + 止损-2%（紧凑组合）
    configs.append(
        {
            "label": "H7: 止盈4%+止损-2%",
            "params": with_g12(),
            "sell_params": {"take_profit_pct": 0.04, "stop_loss_pct": -0.02},
        }
    )

    # H8: 止盈3% + 止损-2%（极紧凑）
    configs.append(
        {
            "label": "H8: 止盈3%+止损-2%",
            "params": with_g12(),
            "sell_params": {"take_profit_pct": 0.03, "stop_loss_pct": -0.02},
        }
    )

    # ══════════════════════════════════════════
    # 维度2: 买入过滤器微调
    # ══════════════════════════════════════════

    # H9: RSI<65（更严格防超买）
    configs.append(
        {
            "label": "H9: RSI<65",
            "params": with_g12(rsi_max=65),
            "sell_params": {**G12_SELL},
        }
    )

    # H10: RSI<70（放宽）
    configs.append(
        {
            "label": "H10: RSI<70",
            "params": with_g12(rsi_max=70),
            "sell_params": {**G12_SELL},
        }
    )

    # H11: 量比>1.5（更严格量能）
    configs.append(
        {
            "label": "H11: 量比>1.5",
            "params": with_g12(min_volume_ratio=1.5),
            "sell_params": {**G12_SELL},
        }
    )

    # H12: 量比>1.0（放宽量能）
    configs.append(
        {
            "label": "H12: 量比>1.0",
            "params": with_g12(min_volume_ratio=1.0),
            "sell_params": {**G12_SELL},
        }
    )

    # H13: ATR<3%（更严格波动控制）
    configs.append(
        {
            "label": "H13: ATR<3%",
            "params": with_g12(max_atr_pct=3.0),
            "sell_params": {**G12_SELL},
        }
    )

    # H14: 上影线<0.5%（更严格）
    configs.append(
        {
            "label": "H14: 上影线<0.5%",
            "params": with_g12(max_upper_shadow_pct=0.5),
            "sell_params": {**G12_SELL},
        }
    )

    # H15: 前日涨幅<2%（更严格）
    configs.append(
        {
            "label": "H15: 前日涨幅<2%",
            "params": with_g12(max_prev_change_pct=2.0),
            "sell_params": {**G12_SELL},
        }
    )

    # H16: 当日涨幅2%-5%（加最低涨幅门槛）
    configs.append(
        {
            "label": "H16: 最低涨幅2%",
            "params": with_g12(min_change_pct=2.0),
            "sell_params": {**G12_SELL},
        }
    )

    # H17: MA60距离<8%（更严格）
    configs.append(
        {
            "label": "H17: MA60距离<8%",
            "params": with_g12(max_dist_ma60_pct=8.0),
            "sell_params": {**G12_SELL},
        }
    )

    # ══════════════════════════════════════════
    # 维度3: 买入+卖出联合优化（基于前两轮最优方向）
    # ══════════════════════════════════════════

    # H18: 上影线<0.5% + 止盈4%
    configs.append(
        {
            "label": "★ H18: 上影<0.5%+止盈4%",
            "params": with_g12(max_upper_shadow_pct=0.5),
            "sell_params": {"take_profit_pct": 0.04, "stop_loss_pct": -0.03},
        }
    )

    # H19: 前日<2% + 上影<0.5% + 止盈4%
    configs.append(
        {
            "label": "★ H19: 前日<2%+上影<0.5%+止盈4%",
            "params": with_g12(max_prev_change_pct=2.0, max_upper_shadow_pct=0.5),
            "sell_params": {"take_profit_pct": 0.04, "stop_loss_pct": -0.03},
        }
    )

    # H20: RSI<65 + 上影<0.5% + 止盈4% + 止损-2%
    configs.append(
        {
            "label": "★★ H20: RSI65+上影0.5%+止盈4%止损2%",
            "params": with_g12(rsi_max=65, max_upper_shadow_pct=0.5),
            "sell_params": {"take_profit_pct": 0.04, "stop_loss_pct": -0.02},
        }
    )

    # H21: 最低涨幅2% + 上影<0.5% + 止盈4%
    configs.append(
        {
            "label": "★★ H21: 涨幅2%+上影0.5%+止盈4%",
            "params": with_g12(min_change_pct=2.0, max_upper_shadow_pct=0.5),
            "sell_params": {"take_profit_pct": 0.04, "stop_loss_pct": -0.03},
        }
    )

    return configs


# ── 主流程 ──


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        type=int,
        default=1,
        help="阶段: 1=快扫50只, 2=验证200只, 3=全量500只",
    )
    parser.add_argument(
        "--stocks", type=int, default=0, help="自定义股票数（覆盖phase默认值）"
    )
    args = parser.parse_args()

    phase_stocks = {1: 50, 2: 200, 3: 500}
    max_stocks = args.stocks if args.stocks > 0 else phase_stocks.get(args.phase, 50)

    print("=" * 70)
    print(f"  T1 v3 H轮优化 - Phase {args.phase} ({max_stocks}只股票)")
    print(f"  区间: {START_DATE} ~ {END_DATE}")
    print("=" * 70)

    # 1. 加载数据
    print("\n[1/4] 加载本地数据 ...")
    all_df, stock_info = load_local_data()

    # 2. 筛选 + 预缓存
    print("\n[2/4] 筛选可交易股票 & 预缓存 ...")
    eligible = filter_mainboard_stocks(stock_info, all_df)
    print(f"  可交易股票: {len(eligible)} 只")

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

    import random

    random.seed(42)
    if len(eligible) > max_stocks:
        eligible = random.sample(eligible, max_stocks)
        stock_cache = {k: v for k, v in stock_cache.items() if k in set(eligible)}
    print(f"  采样后: {len(eligible)} 只")
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

    # 4. 运行优化
    print("\n[4/4] 开始 H 轮优化 ...")
    configs = build_test_configs()
    results = []

    print(
        f"\n  {'方案':<45} {'交易':>5} {'胜率':>6} {'总收益':>8} {'均收益':>7} {'夏普':>6} {'回撤':>8} {'盈亏比':>6}"
    )
    print(f"  {'-'*100}")

    for i, cfg in enumerate(configs):
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
        results.append((cfg["label"], r, cfg))
        print_result_compact(cfg["label"], r)

    # 5. 排序输出 Top 5
    print(f"\n\n{'='*70}")
    print("  Top 5 方案（按夏普比率排序）")
    print(f"{'='*70}")

    ranked = sorted(results, key=lambda x: x[1].sharpe_ratio, reverse=True)
    for i, (label, r, cfg) in enumerate(ranked[:5]):
        print_detail(f"#{i+1} {label}", r)

    # 6. 综合评分
    print(f"\n\n{'='*70}")
    print("  综合评分（胜率×0.3 + 夏普×0.3 + 总收益×0.2 + 盈亏比×0.2）")
    print(f"{'='*70}")

    scored = []
    for label, r, cfg in results:
        if r.total_trades < 5:
            continue
        plr = calc_profit_loss_ratio(r.trades)
        # 归一化评分
        score = (
            r.win_rate * 0.3
            + min(r.sharpe_ratio / 5.0, 1.0) * 0.3
            + min(r.total_return_pct / 50.0, 1.0) * 0.2
            + min(plr / 3.0, 1.0) * 0.2
        )
        scored.append((label, r, score, plr))

    scored.sort(key=lambda x: x[2], reverse=True)
    print(
        f"\n  {'排名':>4} {'方案':<45} {'综合分':>6} {'胜率':>6} {'夏普':>6} {'总收益':>8} {'盈亏比':>6}"
    )
    print(f"  {'-'*90}")
    for i, (label, r, score, plr) in enumerate(scored[:10]):
        print(
            f"  {i+1:>4} {label:<45} {score:>5.3f} "
            f"{r.win_rate*100:>5.1f}% {r.sharpe_ratio:>5.2f} "
            f"{r.total_return_pct:>+7.2f}% {plr:>5.2f}"
        )

    print("\n优化完成!")


if __name__ == "__main__":
    main()
