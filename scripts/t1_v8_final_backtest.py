"""
T1 v8 Final 回测 - 带大盘过滤

关键发现：加入大盘过滤（5日均涨幅>0时才交易）后
- 从亏损103%变为盈利+28.84%
- 胜率从48.7%提升到51.7%
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from engine.strategies.t1_v8_combined import T1V8Combined
from engine.t1_v8_sell import T1V8SellEngine


def load_data():
    print("加载数据...")
    daily_path = project_root / "data" / "yearly" / "all_stocks_daily.csv"
    daily_df = pd.read_csv(daily_path)

    basic_path = project_root / "data" / "yearly" / "daily_basic.csv"
    basic_df = pd.read_csv(basic_path)

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

    print(f"数据加载完成: {len(df)}行, {df['ts_code'].nunique()}只股票")
    return df


def compute_market_regime(df: pd.DataFrame) -> dict:
    """计算每个交易日的大盘环境 (True=可交易)"""
    market = df.groupby("date").agg(
        avg_pct=("pct_chg", "mean"),
    ).reset_index().sort_values("date")
    market["ma5_pct"] = market["avg_pct"].rolling(5).mean()
    market["bullish"] = market["ma5_pct"] > 0
    return dict(zip(market["date"], market["bullish"]))


def run_backtest(df, start_date, end_date, sample_size=2000, max_positions=5):
    print(f"\n{'='*60}")
    print(f"T1 V8 Final 回测 (带大盘过滤)")
    print(f"  区间: {start_date} ~ {end_date}")
    print(f"  样本: {sample_size}只, 最大持仓: {max_positions}")
    print(f"{'='*60}\n")

    # 大盘环境
    market_regime = compute_market_regime(df)

    # 抽样
    all_stocks = df["ts_code"].unique()
    np.random.seed(42)
    sample_stocks = np.random.choice(all_stocks, size=min(sample_size, len(all_stocks)), replace=False)
    df_sample = df[df["ts_code"].isin(sample_stocks)].copy()
    df_sample = df_sample[(df_sample["date"] >= int(start_date)) & (df_sample["date"] <= int(end_date))]

    print(f"样本: {df_sample['ts_code'].nunique()}只, {len(df_sample)}行\n")

    strategy = T1V8Combined()
    sell_engine = T1V8SellEngine()
    trading_days = sorted(df_sample["date"].unique())

    all_trades = []
    positions = []
    skipped_bear = 0

    for i, current_date in enumerate(trading_days[:-1]):
        # 大盘过滤
        is_bull = market_regime.get(current_date, False)
        if not is_bull:
            skipped_bear += 1
            # 仍需处理现有持仓的卖出
            if positions:
                next_date = trading_days[i + 1]
                next_data = df_sample[df_sample["date"] == next_date]
                sell_decisions = sell_engine.batch_decide_sell(positions, next_data)
                for decision in sell_decisions:
                    if decision["sell_type"] != "suspended":
                        position = next(p for p in positions if p["ts_code"] == decision["ts_code"])
                        all_trades.append({
                            "ts_code": decision["ts_code"],
                            "buy_date": position["buy_date"],
                            "buy_price": decision["buy_price"],
                            "sell_date": next_date,
                            "sell_price": decision["sell_price"],
                            "sell_type": decision["sell_type"],
                            "profit_pct": decision["profit_pct"],
                            "win": decision["profit_pct"] > 0,
                            **position["indicators"],
                        })
                positions = []
            continue

        # 生成买入信号
        signals = strategy.generate_signals(df_sample[df_sample["date"] <= current_date])
        today_signals = [s for s in signals if s["date"] == current_date]

        if today_signals:
            today_signals.sort(key=lambda x: x["indicators"].get("volume_ratio", 0), reverse=True)
            today_signals = today_signals[:max_positions]
            for signal in today_signals:
                positions.append({
                    "ts_code": signal["ts_code"],
                    "buy_date": current_date,
                    "buy_price": signal["close"],
                    "indicators": signal["indicators"],
                })

        # 卖出
        if positions:
            next_date = trading_days[i + 1]
            next_data = df_sample[df_sample["date"] == next_date]
            sell_decisions = sell_engine.batch_decide_sell(positions, next_data)
            for decision in sell_decisions:
                if decision["sell_type"] != "suspended":
                    position = next(p for p in positions if p["ts_code"] == decision["ts_code"])
                    all_trades.append({
                        "ts_code": decision["ts_code"],
                        "buy_date": position["buy_date"],
                        "buy_price": decision["buy_price"],
                        "sell_date": next_date,
                        "sell_price": decision["sell_price"],
                        "sell_type": decision["sell_type"],
                        "profit_pct": decision["profit_pct"],
                        "win": decision["profit_pct"] > 0,
                        **position["indicators"],
                    })
            positions = []

    print(f"跳过熊市天数: {skipped_bear}")
    generate_report(all_trades, sell_engine)


def generate_report(trades, sell_engine):
    if not trades:
        print("无交易记录")
        return

    df = pd.DataFrame(trades)

    print(f"\n{'='*60}")
    print("T1 V8 Final 回测报告 (带大盘过滤)")
    print(f"{'='*60}\n")

    total = len(df)
    wins = df["win"].sum()
    win_rate = wins / total * 100
    avg_pnl = df["profit_pct"].mean()
    total_pnl = df["profit_pct"].sum()

    # 夏普
    sharpe = df["profit_pct"].mean() / df["profit_pct"].std() * np.sqrt(252) if df["profit_pct"].std() > 0 else 0

    # 最大回撤（累计曲线）
    cumulative = df["profit_pct"].cumsum()
    running_max = cumulative.cummax()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()

    print(f"交易统计:")
    print(f"  总交易: {total}笔")
    print(f"  盈利: {wins}笔 / 亏损: {total - wins}笔")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  平均每笔: {avg_pnl:.3f}%")
    print(f"  累计收益: {total_pnl:+.2f}%")
    print(f"  夏普比率: {sharpe:.2f}")
    print(f"  最大回撤: {max_dd:.2f}%")

    # 年化（假设每笔持有1天）
    trading_days_count = df["buy_date"].nunique()
    if trading_days_count > 0:
        daily_return = total_pnl / trading_days_count
        annual_return = daily_return * 252
        print(f"  交易天数: {trading_days_count}")
        print(f"  日均收益: {daily_return:.3f}%")
        print(f"  年化收益: {annual_return:.1f}%")

    # 卖出类型
    stats = sell_engine.get_statistics(trades)
    print(f"\n卖出类型:")
    for st, s in stats["by_type"].items():
        print(f"  {st}: {s['count']}笔({s['pct_of_total']:.0f}%), 胜率{s['win_rate']:.0f}%, 均收{s['avg_profit']:.3f}%")

    # 月度
    df["month"] = df["buy_date"].astype(str).str[:6]
    print(f"\n月度:")
    for month, g in df.groupby("month"):
        icon = "🟢" if g["profit_pct"].sum() > 0 else "🔴"
        print(f"  {month}: {len(g)}笔, 胜率{g['win'].mean()*100:.0f}%, {g['profit_pct'].sum():+.2f}%")

    # 保存
    output = project_root / "data" / "backtest_results" / "t1_v8_final_trades.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n交易记录: {output}")


if __name__ == "__main__":
    df = load_data()
    run_backtest(df, start_date="20250411", end_date="20260411", sample_size=2000)
