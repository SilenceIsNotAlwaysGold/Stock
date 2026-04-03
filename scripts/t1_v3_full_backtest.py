"""
T1 v3 策略全面回测脚本（本地数据版）

读取 data/yearly/ 下的本地 CSV 数据，仅从 Tushare 拉取指数日线。
集成完整大盘环境过滤，多参数组合测试。

用法: python scripts/t1_v3_full_backtest.py
"""

import sys
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tushare as ts
from app.config import settings
from engine.strategies.t1_v3 import T1V3Resonance
from engine.t1_backtest import T1Backtester, BacktestResult
from engine.t1_sell_engine import SmartSellEngine
from engine.t1_filters import MarketEnvironmentFilter, StockPoolFilter

# ── Tushare 初始化（仅用于拉指数） ──
ts.set_token(settings.TUSHARE_TOKEN)
pro = ts.pro_api()

# ── 路径配置 ──
DATA_DIR = ROOT / "data" / "yearly"
ALL_DAILY_FILE = DATA_DIR / "all_stocks_daily.csv"
STOCK_LIST_FILE = DATA_DIR / "stock_list.csv"

# ── 参数配置 ──
START_DATE = "20250225"
END_DATE = "20260225"
INDEX_CODE = "000300.SH"
MAX_STOCKS = 500  # 采样股票数（0=全量）


# ── 本地数据加载 ──


def load_local_data():
    """加载本地 CSV 数据，返回 (all_daily_df, stock_info_dict)"""
    print("  加载本地日线数据 ...")
    df = pd.read_csv(ALL_DAILY_FILE, encoding="utf-8-sig")
    # 确保列名标准化
    if "trade_date" in df.columns:
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
    # 日期标准化为 YYYY-MM-DD（与 market_cache key 一致）
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
    print(f"  股票列表: {len(stock_info)} 只")
    return df, stock_info


def get_stock_daily(all_df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    """从全量数据中提取单只股票的日线，按日期正序"""
    sub = all_df[all_df["ts_code"] == ts_code].copy()
    if sub.empty:
        return pd.DataFrame()
    sub = sub.sort_values("date").reset_index(drop=True)
    # 确保数值列
    for col in ["open", "high", "low", "close", "volume"]:
        if col in sub.columns:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")
    return sub


def filter_mainboard_stocks(stock_info: dict, all_df: pd.DataFrame) -> list:
    """筛选沪深主板股票（排除科创板/北交所/ST/次新）"""
    codes = all_df["ts_code"].unique().tolist()
    eligible = []
    for code in codes:
        info = stock_info.get(code, {})
        name = info.get("name", "")
        list_date = info.get("list_date", "")
        ok, reason = StockPoolFilter.is_eligible(code, name, list_date)
        if ok:
            eligible.append(code)
    return eligible


def fetch_index_daily(ts_code: str, start: str, end: str) -> pd.DataFrame:
    """从 Tushare 获取指数日线"""
    print(f"  拉取指数 {ts_code} 日线 ...")
    df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.sort_values("date").reset_index(drop=True)
    return df


# ── 大盘环境缓存 ──


def build_market_env_cache(index_df: pd.DataFrame) -> dict:
    """预计算每个交易日的大盘环境评分"""
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


def run_full_backtest(
    stocks: list,
    stock_info: dict,
    stock_cache: dict,
    market_cache: dict,
    params: dict,
    sell_params: dict = None,
) -> BacktestResult:
    """对多只股票运行 v3 策略回测（使用预缓存数据）"""
    strategy = T1V3Resonance(**params)
    sell_engine = SmartSellEngine(**(sell_params or {}))
    backtester = T1Backtester(strategy=strategy, sell_engine=sell_engine)

    all_trades = []
    processed = 0

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
        processed += 1

        if processed % 50 == 0:
            print(
                f"    已处理 {processed}/{len(stocks)} 只，累计 {len(all_trades)} 笔交易"
            )

    # 汇总
    combined = BacktestResult(
        strategy_name=strategy.name,
        period=f"{START_DATE} ~ {END_DATE}",
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

    print(f"  处理完成: {processed} 只股票")
    return combined


# ── 分析工具 ──


def analyze_by_month(trades: list) -> str:
    """按月分析胜率"""
    monthly = defaultdict(lambda: {"win": 0, "loss": 0, "pnl": 0.0})
    for t in trades:
        month = str(t.date)[:7]
        monthly[month]["pnl"] += t.pnl_pct
        if t.is_win:
            monthly[month]["win"] += 1
        else:
            monthly[month]["loss"] += 1

    lines = ["\n  月度分析:"]
    lines.append(f"  {'月份':<10} {'交易数':>6} {'胜率':>8} {'总收益':>8}")
    lines.append(f"  {'-'*36}")
    for month in sorted(monthly.keys()):
        d = monthly[month]
        total = d["win"] + d["loss"]
        wr = d["win"] / total * 100 if total > 0 else 0
        lines.append(f"  {month:<10} {total:>6} {wr:>7.1f}% {d['pnl']:>+7.2f}%")
    return "\n".join(lines)


def analyze_by_sell_reason(trades: list) -> str:
    """按卖出原因分析"""
    reasons = defaultdict(lambda: {"count": 0, "win": 0, "pnl": 0.0})
    for t in trades:
        reasons[t.sell_reason]["count"] += 1
        reasons[t.sell_reason]["pnl"] += t.pnl_pct
        if t.is_win:
            reasons[t.sell_reason]["win"] += 1

    lines = ["\n  卖出原因分析:"]
    lines.append(f"  {'原因':<22} {'次数':>5} {'胜率':>8} {'均收益':>8}")
    lines.append(f"  {'-'*46}")
    for reason, d in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
        wr = d["win"] / d["count"] * 100 if d["count"] > 0 else 0
        avg = d["pnl"] / d["count"] if d["count"] > 0 else 0
        lines.append(f"  {reason:<22} {d['count']:>5} {wr:>7.1f}% {avg:>+7.2f}%")
    return "\n".join(lines)


def print_result(label: str, result: BacktestResult):
    """打印单组回测结果"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  总交易: {result.total_trades}")
    if result.total_trades == 0:
        print("  无交易信号")
        return
    print(
        f"  胜率: {result.win_rate*100:.1f}% ({result.win_count}胜/{result.loss_count}负)"
    )
    print(f"  总收益: {result.total_return_pct:+.2f}%")
    print(f"  均收益: {result.avg_return_pct:+.2f}%")
    print(f"  最大单笔: {result.max_return_pct:+.2f}%")
    print(f"  最大亏损: {result.min_return_pct:+.2f}%")
    print(f"  最大回撤: {result.max_drawdown_pct:.2f}%")
    print(f"  夏普比率: {result.sharpe_ratio:.2f}")
    print(analyze_by_month(result.trades))
    print(analyze_by_sell_reason(result.trades))


# ── 主流程 ──


def main():
    print("=" * 60)
    print("  T1 v3 策略全面回测（本地数据版）")
    print(f"  区间: {START_DATE} ~ {END_DATE}")
    print("=" * 60)

    # 1. 加载本地数据
    print("\n[1/4] 加载本地数据 ...")
    all_df, stock_info = load_local_data()

    # 2. 筛选可交易股票 + 预缓存
    print("\n[2/5] 筛选可交易股票 & 预缓存数据 ...")
    eligible = filter_mainboard_stocks(stock_info, all_df)
    print(f"  可交易股票: {len(eligible)} 只")

    # 预缓存每只股票的 DataFrame（用 groupby 一次性拆分）
    print("  预缓存个股数据 ...")
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
    # 采样
    import random

    if MAX_STOCKS > 0 and len(eligible) > MAX_STOCKS:
        random.seed(42)
        eligible = random.sample(eligible, MAX_STOCKS)
        stock_cache = {k: v for k, v in stock_cache.items() if k in set(eligible)}
        print(f"  采样后: {len(eligible)} 只")
    # 释放大表内存
    del all_df

    # 3. 拉取指数数据 + 构建大盘环境缓存
    print("\n[3/5] 拉取指数数据 & 构建大盘环境缓存 ...")
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

    # 4. 多参数组合回测
    print("\n[4/5] 开始多参数组合回测 ...")

    # 基础参数模板（F1最优基线）
    BASE = {
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
        # 新增过滤器默认关闭
        "max_prev_change_pct": None,
        "require_macd_above_zero": False,
        "min_change_pct": None,
        "max_upper_shadow_pct": None,
        "max_consecutive_up": None,
        "require_close_above_vwap": False,
    }

    def with_base(**overrides):
        return {**BASE, **overrides}

    test_configs = [
        # ── 基线: 当前F1最优 ──
        {
            "label": "基线: F1(MA20+ATR4%+量比1.2)",
            "params": with_base(),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G1: F1 + 前日涨幅<2%（避免追高连板） ──
        {
            "label": "G1: F1+前日涨幅<2%",
            "params": with_base(max_prev_change_pct=2.0),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G2: F1 + 前日涨幅<3%（宽松版） ──
        {
            "label": "G2: F1+前日涨幅<3%",
            "params": with_base(max_prev_change_pct=3.0),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G3: F1 + MACD>0轴（中期趋势确认） ──
        {
            "label": "G3: F1+MACD>0轴",
            "params": with_base(require_macd_above_zero=True),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G4: F1 + 上影线<0.5%（避免抛压） ──
        {
            "label": "G4: F1+上影线<0.5%",
            "params": with_base(max_upper_shadow_pct=0.5),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G5: F1 + 上影线<1.0%（宽松版） ──
        {
            "label": "G5: F1+上影线<1.0%",
            "params": with_base(max_upper_shadow_pct=1.0),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G6: F1 + 连涨<=2天 ──
        {
            "label": "G6: F1+连涨<=2天",
            "params": with_base(max_consecutive_up=2),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G7: F1 + 连涨<=1天（首日启动） ──
        {
            "label": "G7: F1+连涨<=1天",
            "params": with_base(max_consecutive_up=1),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G8: F1 + 收盘>均价线 ──
        {
            "label": "G8: F1+收盘>均价线",
            "params": with_base(require_close_above_vwap=True),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G9: F1 + RSI<65（更严格防超买） ──
        {
            "label": "G9: F1+RSI<65",
            "params": with_base(rsi_max=65),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G10: F1 + 共振3（更严格信号） ──
        {
            "label": "G10: F1+共振3",
            "params": with_base(min_resonance=3),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G11: 综合A（前日<2% + MACD>0 + 上影<1%） ──
        {
            "label": "★ G11: 前日<2%+MACD>0+上影<1%",
            "params": with_base(
                max_prev_change_pct=2.0,
                require_macd_above_zero=True,
                max_upper_shadow_pct=1.0,
            ),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G12: 综合B（前日<3% + 连涨<=2 + 上影<1%） ──
        {
            "label": "★ G12: 前日<3%+连涨<=2+上影<1%",
            "params": with_base(
                max_prev_change_pct=3.0,
                max_consecutive_up=2,
                max_upper_shadow_pct=1.0,
            ),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G13: 综合C（MACD>0 + 连涨<=2 + 收盘>均价） ──
        {
            "label": "★ G13: MACD>0+连涨<=2+收盘>均价",
            "params": with_base(
                require_macd_above_zero=True,
                max_consecutive_up=2,
                require_close_above_vwap=True,
            ),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G14: 全面严选（前日<2% + MACD>0 + 连涨<=2 + 上影<1%） ──
        {
            "label": "★★ G14: 全面严选",
            "params": with_base(
                max_prev_change_pct=2.0,
                require_macd_above_zero=True,
                max_consecutive_up=2,
                max_upper_shadow_pct=1.0,
            ),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
        # ── G15: 极致严选（G14 + 收盘>均价 + RSI<65） ──
        {
            "label": "★★ G15: 极致严选",
            "params": with_base(
                max_prev_change_pct=2.0,
                require_macd_above_zero=True,
                max_consecutive_up=2,
                max_upper_shadow_pct=1.0,
                require_close_above_vwap=True,
                rsi_max=65,
            ),
            "sell_params": {"take_profit_pct": 0.05, "stop_loss_pct": -0.03},
        },
    ]

    results = []
    for i, cfg in enumerate(test_configs):
        print(f"\n  ── 测试 {i+1}/{len(test_configs)}: {cfg['label']} ──")
        r = run_full_backtest(
            stocks=eligible,
            stock_info=stock_info,
            stock_cache=stock_cache,
            market_cache=market_cache,
            params=cfg["params"],
            sell_params=cfg.get("sell_params"),
        )
        results.append((cfg["label"], r))
        print_result(cfg["label"], r)

    # 5. 汇总对比
    print("\n" + "=" * 80)
    print("  参数组合对比汇总")
    print("=" * 80)
    print(
        f"  {'方案':<40} {'交易':>5} {'胜率':>7} {'总收益':>8} {'均收益':>7} {'夏普':>6} {'回撤':>8}"
    )
    print(f"  {'-'*82}")
    for label, r in results:
        short_label = label[:38]
        wr = f"{r.win_rate*100:.1f}%" if r.total_trades > 0 else "N/A"
        avg = f"{r.avg_return_pct:+.2f}%" if r.total_trades > 0 else "N/A"
        print(
            f"  {short_label:<40} {r.total_trades:>5} {wr:>7} "
            f"{r.total_return_pct:>+7.2f}% {avg:>7} {r.sharpe_ratio:>5.2f} {r.max_drawdown_pct:>7.2f}%"
        )

    print("\n回测完成")


if __name__ == "__main__":
    main()
