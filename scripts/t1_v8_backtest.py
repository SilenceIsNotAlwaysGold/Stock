"""
T1 v8 组合策略回测

V8 = G12因子 + 量价确认 + 优化卖出
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
    """加载数据"""
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


def run_backtest(
    df: pd.DataFrame, start_date: str, end_date: str, sample_size: int = 2000
):
    print(f"\n{'='*60}")
    print(f"T1 V8 组合策略回测")
    print(f"  时间区间: {start_date} ~ {end_date}")
    print(f"  样本数量: {sample_size}只股票")
    print(f"{'='*60}\n")

    # 随机抽样
    all_stocks = df["ts_code"].unique()
    np.random.seed(42)
    sample_stocks = np.random.choice(
        all_stocks, size=min(sample_size, len(all_stocks)), replace=False
    )

    df_sample = df[df["ts_code"].isin(sample_stocks)].copy()
    df_sample = df_sample[
        (df_sample["date"] >= int(start_date)) & (df_sample["date"] <= int(end_date))
    ]

    print(f"实际样本: {df_sample['ts_code'].nunique()}只股票, {len(df_sample)}行数据\n")

    strategy = T1V8Combined()
    sell_engine = T1V8SellEngine()

    trading_days = sorted(df_sample["date"].unique())

    all_trades = []
    positions = []

    for i, current_date in enumerate(trading_days[:-1]):
        # 生成买入信号
        signals = strategy.generate_signals(
            df_sample[df_sample["date"] <= current_date]
        )

        today_signals = [s for s in signals if s["date"] == current_date]

        if today_signals:
            # 按量比排序，取前5只（集中火力）
            today_signals.sort(key=lambda x: x["indicators"].get("volume_ratio", 0), reverse=True)
            today_signals = today_signals[:5]

            print(f"{current_date}: 买入 {len(today_signals)}只 (共筛出{len([s for s in signals if s['date'] == current_date])}只)")

            for signal in today_signals:
                positions.append(
                    {
                        "ts_code": signal["ts_code"],
                        "buy_date": current_date,
                        "buy_price": signal["close"],
                        "indicators": signal["indicators"],
                    }
                )

        # 处理卖出
        if positions:
            next_date = trading_days[i + 1]
            next_data = df_sample[df_sample["date"] == next_date]

            sell_decisions = sell_engine.batch_decide_sell(positions, next_data)

            for decision in sell_decisions:
                if decision["sell_type"] != "suspended":
                    position = next(
                        p for p in positions if p["ts_code"] == decision["ts_code"]
                    )
                    all_trades.append(
                        {
                            "ts_code": decision["ts_code"],
                            "buy_date": position["buy_date"],
                            "buy_price": decision["buy_price"],
                            "sell_date": next_date,
                            "sell_price": decision["sell_price"],
                            "sell_type": decision["sell_type"],
                            "profit_pct": decision["profit_pct"],
                            "win": decision["profit_pct"] > 0,
                            **position["indicators"],
                        }
                    )

            positions = []

    generate_report(all_trades, sell_engine)


def generate_report(trades: list, sell_engine: T1V8SellEngine):
    if not trades:
        print("无交易记录")
        return

    df_trades = pd.DataFrame(trades)

    print(f"\n{'='*60}")
    print("T1 V8 组合策略回测报告")
    print(f"{'='*60}\n")

    total_trades = len(df_trades)
    wins = df_trades["win"].sum()
    win_rate = wins / total_trades * 100
    avg_profit = df_trades["profit_pct"].mean()
    total_return = df_trades["profit_pct"].sum()
    max_drawdown = df_trades["profit_pct"].min()

    # 夏普比率（简化）
    if df_trades["profit_pct"].std() > 0:
        sharpe = df_trades["profit_pct"].mean() / df_trades["profit_pct"].std() * np.sqrt(252)
    else:
        sharpe = 0

    print(f"交易统计:")
    print(f"  总交易次数: {total_trades}")
    print(f"  盈利次数: {wins}")
    print(f"  亏损次数: {total_trades - wins}")
    print(f"  胜率: {win_rate:.2f}%")
    print(f"  平均收益: {avg_profit:.3f}%")
    print(f"  累计收益: {total_return:.2f}%")
    print(f"  最大单笔亏损: {max_drawdown:.2f}%")
    print(f"  夏普比率: {sharpe:.2f}")

    # 卖出类型统计
    sell_stats = sell_engine.get_statistics(trades)
    print(f"\n卖出类型分布:")
    for sell_type, stats in sell_stats["by_type"].items():
        print(f"  {sell_type}:")
        print(f"    次数: {stats['count']} ({stats['pct_of_total']:.1f}%)")
        print(f"    胜率: {stats['win_rate']:.2f}%")
        print(f"    平均收益: {stats['avg_profit']:.3f}%")

    # 月度统计
    df_trades["month"] = df_trades["buy_date"].astype(str).str[:6]
    monthly = df_trades.groupby("month").agg(
        trades=("profit_pct", "count"),
        win_rate=("win", "mean"),
        avg_pnl=("profit_pct", "mean"),
        total_pnl=("profit_pct", "sum"),
    ).round(3)
    print(f"\n月度统计:")
    for month, row in monthly.iterrows():
        pnl_icon = "+" if row["total_pnl"] > 0 else ""
        print(f"  {month}: {row['trades']}笔, 胜率{row['win_rate']*100:.0f}%, 累计{pnl_icon}{row['total_pnl']:.2f}%")

    # 保存
    output_path = project_root / "data" / "backtest_results" / "t1_v8_trades.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_trades.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n详细交易记录已保存: {output_path}")


if __name__ == "__main__":
    df = load_data()
    run_backtest(df=df, start_date="20250411", end_date="20260411", sample_size=2000)
