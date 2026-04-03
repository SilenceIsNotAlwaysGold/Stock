#!/usr/bin/env python3
"""
T1 v5 隔夜策略 - 回测验证（使用 tushare daily_basic 真实数据）

合并 daily + daily_basic 数据（换手率/量比/流通市值）。
测试子策略A（尾盘动量）、B（RSI反弹）、及组合。
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

from engine.strategies.t1_v5 import T1V5Overnight
from engine.t1_v4_sell import T1V4SellEngine
from engine.t1_filters import StockPoolFilter, MarketEnvironmentFilter
from app.config import Settings

settings = Settings()
START_DATE = "20250225"
END_DATE = "20260225"
MAX_STOCKS = 1000
INDEX_CODE = "399006.SZ"

ALL_DAILY_FILE = PROJECT_ROOT / "data" / "yearly" / "all_stocks_daily.csv"
DAILY_BASIC_FILE = PROJECT_ROOT / "data" / "yearly" / "daily_basic.csv"
STOCK_LIST_FILE = PROJECT_ROOT / "data" / "yearly" / "stock_list.csv"

ts.set_token(settings.TUSHARE_TOKEN)
pro = ts.pro_api()


def fp(msg):
    print(msg, flush=True)


def load_and_merge_data():
    """加载 daily + daily_basic 合并数据"""
    fp(f"  读取日线数据 ...")
    daily = pd.read_csv(ALL_DAILY_FILE, dtype={"ts_code": str})
    if "trade_date" in daily.columns:
        daily = daily.rename(columns={"trade_date": "date", "vol": "volume"})
    daily["date"] = daily["date"].astype(str).str.replace("-", "")
    daily["date"] = pd.to_datetime(daily["date"], format="%Y%m%d").dt.strftime(
        "%Y-%m-%d"
    )
    for col in [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pct_chg",
        "pre_close",
        "change",
    ]:
        if col in daily.columns:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")
    fp(f"  日线: {len(daily):,} 行, {daily['ts_code'].nunique()} 只股票")

    fp(f"  读取 daily_basic 数据 ...")
    basic = pd.read_csv(DAILY_BASIC_FILE, dtype={"ts_code": str})
    basic["trade_date"] = basic["trade_date"].astype(str)
    basic["date"] = pd.to_datetime(basic["trade_date"], format="%Y%m%d").dt.strftime(
        "%Y-%m-%d"
    )
    for col in [
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "circ_mv",
        "total_mv",
    ]:
        if col in basic.columns:
            basic[col] = pd.to_numeric(basic[col], errors="coerce")
    basic_cols = [
        "ts_code",
        "date",
        "turnover_rate",
        "volume_ratio",
        "circ_mv",
        "total_mv",
    ]
    basic = basic[[c for c in basic_cols if c in basic.columns]]
    fp(f"  basic: {len(basic):,} 行")

    # 合并
    merged = daily.merge(basic, on=["ts_code", "date"], how="left")
    fp(f"  合并后: {len(merged):,} 行")
    fp(
        f"  volume_ratio 非空: {merged['volume_ratio'].notna().sum():,} ({merged['volume_ratio'].notna().mean()*100:.1f}%)"
    )
    fp(f"  turnover_rate 非空: {merged['turnover_rate'].notna().sum():,}")
    fp(f"  circ_mv 非空: {merged['circ_mv'].notna().sum():,}")

    stock_info = {}
    if STOCK_LIST_FILE.exists():
        sl = pd.read_csv(STOCK_LIST_FILE, dtype={"ts_code": str})
        for _, row in sl.iterrows():
            stock_info[row["ts_code"]] = {
                "name": str(row.get("name", "")),
                "market": str(row.get("market", "")),
                "list_date": str(row.get("list_date", "")),
            }

    return merged, stock_info


def filter_mainboard(stock_info, all_df):
    codes = all_df["ts_code"].unique()
    eligible = []
    for code in codes:
        info = stock_info.get(code, {})
        ok, _ = StockPoolFilter.is_eligible(
            code, info.get("name", ""), info.get("list_date", "")
        )
        if ok:
            eligible.append(code)
    return eligible


def fetch_index(code, start, end):
    try:
        df = pro.index_daily(ts_code=code, start_date=start, end_date=end)
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
    except Exception as e:
        fp(f"  指数失败: {e}")
    return pd.DataFrame()


def build_market_cache(index_df):
    mef = MarketEnvironmentFilter(min_score_to_trade=40)
    cache = {}
    dates = index_df["date"].tolist()
    for i in range(30, len(index_df)):
        dt = dates[i]
        dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        env = mef.evaluate(index_df.iloc[: i + 1].copy())
        cache[dt_str] = env
    return cache


def run_backtest(stocks, stock_info, stock_cache, market_cache, params, label=""):
    strategy = T1V5Overnight(**params)
    sell_engine = T1V4SellEngine(
        take_profit_pct=0.03, stop_loss_pct=-0.02, limit_up_pct=0.098
    )

    trades = []
    for code in stocks:
        df = stock_cache.get(code)
        if df is None:
            continue
        info = stock_info.get(code, {})
        name = info.get("name", code)

        for i in range(61, len(df) - 1):
            df_slice = df.iloc[: i + 1].copy()
            date_str = str(df.iloc[i]["date"])[:10]

            env = market_cache.get(date_str)
            ctx = (
                {
                    "market_bullish": env.is_tradable and env.score >= 50,
                    "market_score": env.score,
                    "market_mood": env.mood,
                }
                if env
                else {"market_bullish": None}
            )

            sig = strategy.signal(df_slice, context=ctx)
            if sig.action != "BUY" or sig.confidence < 0.5:
                continue

            buy_price = float(df.iloc[i]["close"])
            if buy_price <= 0:
                continue

            nd = df.iloc[i + 1]
            dec = sell_engine.decide(
                buy_price,
                float(nd["open"]),
                float(nd["high"]),
                float(nd["low"]),
                float(nd["close"]),
            )

            trades.append(
                {
                    "date": date_str,
                    "ts_code": code,
                    "name": name,
                    "buy_price": buy_price,
                    "sell_price": dec.sell_price,
                    "sell_reason": dec.sell_reason,
                    "pnl_pct": dec.pnl_pct,
                    "is_win": dec.pnl_pct > 0,
                    "sub": sig.metadata.get("sub_strategy", ""),
                    "pct_chg": sig.metadata.get("pct_chg", 0),
                    "vol_ratio": sig.metadata.get("vol_ratio", 0),
                    "rsi2": sig.metadata.get("rsi2", 0),
                    "turnover": sig.metadata.get("turnover_rate", 0),
                    "circ_mv_w": sig.metadata.get("circ_mv", 0),
                }
            )
    return trades


def stats(trades):
    if not trades:
        return {
            "n": 0,
            "wr": 0,
            "pnl": 0,
            "avg": 0,
            "sh": 0,
            "dd": 0,
            "plr": 0,
            "mx": 0,
            "mn": 0,
        }
    pnls = [t["pnl_pct"] for t in trades]
    w = sum(1 for p in pnls if p > 0)
    wv = [p for p in pnls if p > 0]
    lv = [abs(p) for p in pnls if p <= 0]
    aw = np.mean(wv) if wv else 0
    al = np.mean(lv) if lv else 0.01
    sh = 0
    if len(pnls) > 1:
        s = np.std(pnls)
        if s > 0:
            sh = round(np.mean(pnls) / s * np.sqrt(250), 2)
    cum = np.cumsum(pnls)
    pk = np.maximum.accumulate(cum)
    dd = round(float(np.min(cum - pk)), 2)
    return {
        "n": len(trades),
        "wr": round(w / len(trades) * 100, 1),
        "pnl": round(sum(pnls), 2),
        "avg": round(np.mean(pnls), 3),
        "sh": sh,
        "dd": dd,
        "plr": round(aw / max(al, 0.01), 2),
        "mx": round(max(pnls), 2),
        "mn": round(min(pnls), 2),
    }


def monthly(trades):
    if not trades:
        return []
    m = {}
    for t in trades:
        k = t["date"][:7]
        m.setdefault(k, []).append(t)
    return [
        {
            "m": k,
            "n": len(v),
            "wr": round(sum(1 for t in v if t["is_win"]) / len(v) * 100, 1),
            "pnl": round(sum(t["pnl_pct"] for t in v), 2),
        }
        for k, v in sorted(m.items())
    ]


def sell_dist(trades):
    if not trades:
        return []
    r = {}
    for t in trades:
        r.setdefault(t["sell_reason"], {"c": 0, "p": []})
        r[t["sell_reason"]]["c"] += 1
        r[t["sell_reason"]]["p"].append(t["pnl_pct"])
    return [
        {
            "r": k,
            "c": v["c"],
            "pct": round(v["c"] / len(trades) * 100, 1),
            "wr": round(sum(1 for p in v["p"] if p > 0) / len(v["p"]) * 100, 1),
            "avg": round(np.mean(v["p"]), 3),
        }
        for k, v in sorted(r.items(), key=lambda x: -x[1]["c"])
    ]


# ── 测试配置 ──
CONFIGS = {
    "A: 动量(3-5%)": {
        "enable_momentum": True,
        "enable_rsi_reversion": False,
        "min_pct_chg": 3.0,
        "max_pct_chg": 5.0,
        "min_volume_ratio": 1.5,
    },
    "A2: 动量(2-5%宽)": {
        "enable_momentum": True,
        "enable_rsi_reversion": False,
        "min_pct_chg": 2.0,
        "max_pct_chg": 5.0,
        "min_volume_ratio": 1.2,
        "min_turnover_rate": 3.0,
        "max_turnover_rate": 15.0,
        "min_circ_mv": 300000.0,
        "max_circ_mv": 3000000.0,
    },
    "A3: 动量(VR2严)": {
        "enable_momentum": True,
        "enable_rsi_reversion": False,
        "min_pct_chg": 3.0,
        "max_pct_chg": 5.0,
        "min_volume_ratio": 2.0,
    },
    "A4: 动量(无量递增)": {
        "enable_momentum": True,
        "enable_rsi_reversion": False,
        "min_pct_chg": 3.0,
        "max_pct_chg": 5.0,
        "min_volume_ratio": 1.5,
        "require_volume_increase": False,
    },
    "B: RSI(2)<10": {
        "enable_momentum": False,
        "enable_rsi_reversion": True,
        "rsi2_threshold": 10,
    },
    "B2: RSI(2)<15": {
        "enable_momentum": False,
        "enable_rsi_reversion": True,
        "rsi2_threshold": 15,
    },
    "B3: RSI(2)<5": {
        "enable_momentum": False,
        "enable_rsi_reversion": True,
        "rsi2_threshold": 5,
    },
    "C: A+B组合": {
        "enable_momentum": True,
        "enable_rsi_reversion": True,
        "min_pct_chg": 3.0,
        "max_pct_chg": 5.0,
        "min_volume_ratio": 1.5,
        "rsi2_threshold": 10,
    },
    "C2: A4+B2组合": {
        "enable_momentum": True,
        "enable_rsi_reversion": True,
        "min_pct_chg": 3.0,
        "max_pct_chg": 5.0,
        "min_volume_ratio": 1.5,
        "require_volume_increase": False,
        "rsi2_threshold": 15,
    },
}


def main():
    fp("=" * 80)
    fp("  T1 v5 隔夜策略 - 回测验证（含 daily_basic 真实数据）")
    fp(f"  区间: {START_DATE} ~ {END_DATE} | 样本: {MAX_STOCKS} 股")
    fp(f"  配置: {len(CONFIGS)} 种 | 数据: daily + daily_basic")
    fp("=" * 80)

    # 1. 加载合并数据
    fp("\n[1/4] 加载 & 合并数据 ...")
    all_df, stock_info = load_and_merge_data()

    # 2. 筛选 + 缓存
    fp("\n[2/4] 筛选 & 缓存 ...")
    eligible = filter_mainboard(stock_info, all_df)
    fp(f"  主板: {len(eligible)} 只")

    grouped = all_df.groupby("ts_code")
    stock_cache = {}
    for code in eligible:
        if code not in grouped.groups:
            continue
        sub = grouped.get_group(code).sort_values("date").reset_index(drop=True)
        if len(sub) >= 80:
            stock_cache[code] = sub
    eligible = list(stock_cache.keys())
    fp(f"  有效: {len(eligible)} 只")

    if MAX_STOCKS > 0 and len(eligible) > MAX_STOCKS:
        random.seed(42)
        eligible = random.sample(eligible, MAX_STOCKS)
        stock_cache = {k: v for k, v in stock_cache.items() if k in set(eligible)}
        fp(f"  采样: {len(eligible)} 只")
    del all_df

    # 3. 指数
    fp("\n[3/4] 指数 & 大盘环境 ...")
    idx_start = (
        datetime.strptime(START_DATE, "%Y%m%d") - timedelta(days=150)
    ).strftime("%Y%m%d")
    index_df = fetch_index(INDEX_CODE, idx_start, END_DATE)
    if index_df.empty:
        index_df = fetch_index("000001.SH", idx_start, END_DATE)
    fp(f"  指数: {len(index_df)} 天")
    mcache = build_market_cache(index_df)
    fp(f"  环境: {len(mcache)} 天")

    # 4. 回测
    fp(f"\n[4/4] 运行 {len(CONFIGS)} 个方案 ...\n")
    fp(
        f"  {'方案':<18} {'交易':>5} {'胜率':>6} {'总收益':>9} {'均收益':>8} {'夏普':>6} {'回撤':>8} {'盈亏比':>6}"
    )
    fp(f"  {'-'*82}")

    results = []
    for label, params in CONFIGS.items():
        t0 = time.time()
        trades = run_backtest(eligible, stock_info, stock_cache, mcache, params, label)
        el = time.time() - t0
        s = stats(trades)
        results.append((label, trades, s))
        if s["n"] == 0:
            fp(f"  {label:<18} 无交易 ({el:.0f}s)")
        else:
            fp(
                f"  {label:<18} {s['n']:>4}笔 {s['wr']:>5.1f}% {s['pnl']:>+8.2f}% "
                f"均{s['avg']:>+6.3f}% 夏普{s['sh']:>5.2f} 回撤{s['dd']:>7.2f}% 盈亏比{s['plr']:>4.2f} ({el:.0f}s)"
            )

    # 排名
    fp(f"\n{'='*80}")
    fp("  综合评分排名")
    fp(f"{'='*80}")
    scored = []
    for label, trades, s in results:
        if s["n"] < 5:
            continue
        freq = min(s["n"] / 150, 1.0)
        sc = (
            (s["wr"] / 100) * 0.35
            + min(max(s["sh"], 0) / 5, 1) * 0.30
            + min(s["plr"] / 3, 1) * 0.20
            + freq * 0.15
        )
        scored.append((label, trades, s, sc))
    scored.sort(key=lambda x: x[3], reverse=True)

    fp(
        f"\n  {'#':>2} {'方案':<18} {'分':>5} {'交易':>5} {'胜率':>6} {'夏普':>6} {'盈亏比':>6}"
    )
    fp(f"  {'-'*56}")
    for i, (lb, _, s, sc) in enumerate(scored):
        mk = " ★" if i == 0 else ""
        fp(
            f"  {i+1:>2} {lb:<18} {sc:>4.3f} {s['n']:>4}笔 {s['wr']:>5.1f}% 夏普{s['sh']:>5.2f} 盈亏比{s['plr']:>4.2f}{mk}"
        )

    # 冠军详情
    if scored:
        bl, bt, bs, bsc = scored[0]
        fp(f"\n{'='*80}")
        fp(f"  冠军: {bl}")
        fp(f"{'='*80}")
        fp(
            f"  交易:{bs['n']}笔 胜率:{bs['wr']}% 盈亏比:{bs['plr']} 总收益:{bs['pnl']:+.2f}% 夏普:{bs['sh']} 回撤:{bs['dd']}%"
        )

        # 子策略拆分
        sa = [t for t in bt if t["sub"] == "momentum"]
        sb = [t for t in bt if t["sub"] == "rsi_reversion"]
        if sa or sb:
            fp(f"\n  ── 子策略拆分 ──")
            if sa:
                ss = stats(sa)
                fp(
                    f"  动量A: {ss['n']}笔 胜率{ss['wr']}% 均{ss['avg']:+.3f}% 夏普{ss['sh']} 盈亏比{ss['plr']}"
                )
            if sb:
                ss = stats(sb)
                fp(
                    f"  RSI B: {ss['n']}笔 胜率{ss['wr']}% 均{ss['avg']:+.3f}% 夏普{ss['sh']} 盈亏比{ss['plr']}"
                )

        # 月度
        ms = monthly(bt)
        fp(f"\n  ── 月度 ──")
        fp(f"  {'月份':>8} {'笔':>4} {'胜率':>6} {'收益':>8}")
        fp(f"  {'-'*30}")
        for m in ms:
            fp(f"  {m['m']:>8} {m['n']:>3}笔 {m['wr']:>5.1f}% {m['pnl']:>+7.2f}%")

        # 卖出
        sds = sell_dist(bt)
        fp(f"\n  ── 卖出原因 ──")
        fp(f"  {'原因':<22} {'次':>4} {'占比':>5} {'胜率':>5} {'均收益':>8}")
        fp(f"  {'-'*50}")
        for d in sds:
            fp(
                f"  {d['r']:<22} {d['c']:>3} {d['pct']:>4.1f}% {d['wr']:>4.1f}% {d['avg']:>+7.3f}%"
            )

    # 对比
    fp(f"\n{'='*80}")
    fp("  v5 vs v3 vs v4")
    fp(f"{'='*80}")
    fp(f"  {'指标':<10} {'v3(1000股)':>14} {'v4(1000股)':>14} {'v5(最佳)':>14}")
    fp(f"  {'-'*56}")
    if scored:
        b = scored[0][2]
        fp(f"  {'交易':<10} {'102':>14} {'18878':>14} {b['n']:>14}")
        fp(f"  {'胜率':<10} {'56.9%':>14} {'47.3%':>14} {str(b['wr'])+'%':>14}")
        fp(f"  {'夏普':<10} {'3.06':>14} {'-0.19':>14} {b['sh']:>14}")
        fp(f"  {'总收益':<10} {'+44.03%':>14} {'-421.36%':>14} {str(b['pnl'])+'%':>14}")
        fp(f"  {'回撤':<10} {'-7.73%':>14} {'-603.43%':>14} {str(b['dd'])+'%':>14}")
        fp(f"  {'盈亏比':<10} {'1.58':>14} {'1.07':>14} {b['plr']:>14}")

    fp(f"\nv5 回测完成!")


if __name__ == "__main__":
    main()
