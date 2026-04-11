"""
T1 v9 多因子策略回测 - 带大盘过滤 + 评分排序
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from engine.strategies.t1_v9_multifactor import T1V9MultiFactor
from engine.t1_v8_sell import T1V8SellEngine


def load_data():
    print("加载数据...")
    daily_df = pd.read_csv(project_root / "data" / "yearly" / "all_stocks_daily.csv")
    basic_df = pd.read_csv(project_root / "data" / "yearly" / "daily_basic.csv")

    df = pd.merge(
        daily_df,
        basic_df[["ts_code", "trade_date", "turnover_rate", "volume_ratio", "circ_mv"]],
        left_on=["ts_code", "date"],
        right_on=["ts_code", "trade_date"],
        how="left",
    )
    df = df.drop(columns=["trade_date"])
    df["turnover_rate"] = df["turnover_rate"].fillna(0)
    df["volume_ratio"] = df["volume_ratio"].fillna(1.0)
    df["circ_mv"] = df["circ_mv"].fillna(0)

    print(f"数据: {len(df)}行, {df['ts_code'].nunique()}只股票")
    return df


def compute_market_regime(df):
    market = df.groupby("date").agg(avg_pct=("pct_chg", "mean")).reset_index().sort_values("date")
    market["ma5_pct"] = market["avg_pct"].rolling(5).mean()
    market["bullish"] = market["ma5_pct"] > 0
    return dict(zip(market["date"], market["bullish"]))


def run_backtest(df, start_date, end_date, sample_size=2000, max_positions=5):
    print(f"\n{'='*60}")
    print(f"T1 V9 多因子策略回测")
    print(f"  区间: {start_date} ~ {end_date}, 样本: {sample_size}, 持仓上限: {max_positions}")
    print(f"{'='*60}\n")

    market_regime = compute_market_regime(df)

    all_stocks = df["ts_code"].unique()
    np.random.seed(42)
    sample = np.random.choice(all_stocks, size=min(sample_size, len(all_stocks)), replace=False)
    df_s = df[df["ts_code"].isin(sample)].copy()
    df_s = df_s[(df_s["date"] >= int(start_date)) & (df_s["date"] <= int(end_date))]
    print(f"样本: {df_s['ts_code'].nunique()}只, {len(df_s)}行\n")

    strategy = T1V9MultiFactor()
    sell_engine = T1V8SellEngine()
    trading_days = sorted(df_s["date"].unique())

    all_trades = []
    positions = []
    skipped = 0

    for i, date in enumerate(trading_days[:-1]):
        is_bull = market_regime.get(date, False)

        # 卖出现有持仓（无论牛熊）
        if positions:
            next_date = trading_days[i + 1]
            next_data = df_s[df_s["date"] == next_date]
            for decision in sell_engine.batch_decide_sell(positions, next_data):
                if decision["sell_type"] != "suspended":
                    pos = next(p for p in positions if p["ts_code"] == decision["ts_code"])
                    all_trades.append({
                        "ts_code": decision["ts_code"],
                        "buy_date": pos["buy_date"],
                        "buy_price": decision["buy_price"],
                        "sell_date": next_date,
                        "sell_price": decision["sell_price"],
                        "sell_type": decision["sell_type"],
                        "profit_pct": decision["profit_pct"],
                        "win": decision["profit_pct"] > 0,
                        **pos["indicators"],
                    })
            positions = []

        if not is_bull:
            skipped += 1
            continue

        # 买入
        signals = strategy.generate_signals(df_s[df_s["date"] <= date])
        today_signals = [s for s in signals if s["date"] == date]

        if today_signals:
            # 按评分排序，取前 N 只
            today_signals.sort(key=lambda x: x["indicators"].get("score", 0), reverse=True)
            today_signals = today_signals[:max_positions]

            for sig in today_signals:
                positions.append({
                    "ts_code": sig["ts_code"],
                    "buy_date": date,
                    "buy_price": sig["close"],
                    "indicators": sig["indicators"],
                })

    print(f"跳过熊市: {skipped}天\n")

    # === 报告 ===
    if not all_trades:
        print("无交易记录")
        return

    df_t = pd.DataFrame(all_trades)
    total = len(df_t)
    wins = df_t["win"].sum()

    # 夏普
    sharpe = df_t["profit_pct"].mean() / df_t["profit_pct"].std() * np.sqrt(252) if df_t["profit_pct"].std() > 0 else 0

    # 最大回撤
    cum = df_t["profit_pct"].cumsum()
    max_dd = (cum - cum.cummax()).min()

    # 年化
    trade_days = df_t["buy_date"].nunique()
    daily_ret = df_t["profit_pct"].sum() / trade_days if trade_days > 0 else 0

    print(f"{'='*60}")
    print(f"T1 V9 多因子回测报告")
    print(f"{'='*60}\n")
    print(f"总交易: {total}笔")
    print(f"胜率: {wins/total*100:.1f}%")
    print(f"平均每笔: {df_t['profit_pct'].mean():.3f}%")
    print(f"累计收益: {df_t['profit_pct'].sum():+.2f}%")
    print(f"夏普: {sharpe:.2f}")
    print(f"最大回撤: {max_dd:.2f}%")
    print(f"交易天数: {trade_days}, 日均: {daily_ret:.3f}%, 年化: {daily_ret*252:.1f}%")

    # 评分分布
    print(f"\n评分分布:")
    df_t["score_bin"] = pd.cut(df_t["score"], bins=[55, 65, 75, 85, 100])
    for b, g in df_t.groupby("score_bin", observed=True):
        if len(g) > 0:
            print(f"  {b}: {len(g)}笔, 胜率{g['win'].mean()*100:.0f}%, 均收{g['profit_pct'].mean():.3f}%")

    # 卖出类型
    stats = sell_engine.get_statistics(all_trades)
    print(f"\n卖出类型:")
    for st, s in stats["by_type"].items():
        print(f"  {st}: {s['count']}笔({s['pct_of_total']:.0f}%), 胜率{s['win_rate']:.0f}%, 均收{s['avg_profit']:.3f}%")

    # 月度
    df_t["month"] = df_t["buy_date"].astype(str).str[:6]
    print(f"\n月度:")
    for month, g in df_t.groupby("month"):
        print(f"  {month}: {len(g)}笔, 胜率{g['win'].mean()*100:.0f}%, {g['profit_pct'].sum():+.2f}%")

    # 对比 V8
    print(f"\n{'='*60}")
    print(f"对比 V8 (仅供参考):")
    print(f"  V8: 478笔, 胜率51.7%, 累计+28.84%, 年化+58.6%")
    print(f"  V9: {total}笔, 胜率{wins/total*100:.1f}%, 累计{df_t['profit_pct'].sum():+.2f}%, 年化{daily_ret*252:+.1f}%")

    # 保存
    out = project_root / "data" / "backtest_results" / "t1_v9_trades.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df_t.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n交易记录: {out}")


if __name__ == "__main__":
    df = load_data()
    run_backtest(df, "20250411", "20260411", sample_size=2000)
