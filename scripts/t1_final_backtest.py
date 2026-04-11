"""
T1 v6 策略回测脚本

测试：低位反弹 + 优化止损
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from engine.strategies.t1_final import T1FinalSimple
from engine.t1_final_sell import T1FinalSellEngine


def load_data():
    """加载数据"""
    print("加载数据...")

    # 日线数据
    daily_path = project_root / "data" / "yearly" / "all_stocks_daily.csv"
    daily_df = pd.read_csv(daily_path)

    # daily_basic数据
    basic_path = project_root / "data" / "yearly" / "daily_basic.csv"
    basic_df = pd.read_csv(basic_path)

    # 合并数据
    df = pd.merge(
        daily_df,
        basic_df[["ts_code", "trade_date", "turnover_rate", "volume_ratio", "circ_mv"]],
        left_on=["ts_code", "date"],
        right_on=["ts_code", "trade_date"],
        how="left",
    )

    # 删除重复列
    df = df.drop(columns=["trade_date"])

    # 填充缺失值
    df["turnover_rate"] = df["turnover_rate"].fillna(0)
    df["volume_ratio"] = df["volume_ratio"].fillna(1.0)
    df["circ_mv"] = df["circ_mv"].fillna(0)

    print(f"数据加载完成: {len(df)}行, {df['ts_code'].nunique()}只股票")

    return df


def run_backtest(
    df: pd.DataFrame, start_date: str, end_date: str, sample_size: int = 1000
):
    """
    运行回测

    Args:
        df: 完整数据
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        sample_size: 样本股票数量
    """
    print(f"\n{'='*60}")
    print(f"回测配置:")
    print(f"  时间区间: {start_date} ~ {end_date}")
    print(f"  样本数量: {sample_size}只股票")
    print(f"{'='*60}\n")

    # 随机抽样股票
    all_stocks = df["ts_code"].unique()
    np.random.seed(42)
    sample_stocks = np.random.choice(
        all_stocks, size=min(sample_size, len(all_stocks)), replace=False
    )

    # 过滤数据
    df_sample = df[df["ts_code"].isin(sample_stocks)].copy()
    df_sample = df_sample[
        (df_sample["date"] >= int(start_date)) & (df_sample["date"] <= int(end_date))
    ]

    print(f"实际样本: {df_sample['ts_code'].nunique()}只股票, {len(df_sample)}行数据\n")

    # 初始化策略和卖出引擎
    strategy = T1FinalSimple()
    sell_engine = T1FinalSellEngine()

    # 获取所有交易日
    trading_days = sorted(df_sample["date"].unique())

    # 回测循环
    all_trades = []
    positions = []  # 当前持仓

    for i, current_date in enumerate(trading_days[:-1]):  # 最后一天不买入
        # 获取当日数据
        today_data = df_sample[df_sample["date"] == current_date]

        # 生成买入信号
        signals = strategy.generate_signals(
            df_sample[df_sample["date"] <= current_date]
        )

        # 过滤当日信号
        today_signals = [s for s in signals if s["date"] == current_date]

        if today_signals:
            print(f"{current_date}: 买入信号 {len(today_signals)}只")

            # 记录买入
            for signal in today_signals:
                positions.append(
                    {
                        "ts_code": signal["ts_code"],
                        "buy_date": current_date,
                        "buy_price": signal["close"],
                        "indicators": signal["indicators"],
                    }
                )

        # 处理卖出（次日）
        if positions:
            next_date = trading_days[i + 1]
            next_data = df_sample[df_sample["date"] == next_date]

            # 决定卖出
            sell_decisions = sell_engine.batch_decide_sell(positions, next_data)

            # 记录交易
            for decision in sell_decisions:
                if decision["sell_type"] != "suspended":
                    # 找到对应的买入记录
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

            # 清空持仓
            positions = []

    # 生成回测报告
    generate_report(all_trades, sell_engine)


def generate_report(trades: list, sell_engine: T1FinalSellEngine):
    """生成回测报告"""
    if not trades:
        print("无交易记录")
        return

    df_trades = pd.DataFrame(trades)

    print(f"\n{'='*60}")
    print("T1 v6 策略回测报告")
    print(f"{'='*60}\n")

    # 基础统计
    total_trades = len(df_trades)
    wins = df_trades["win"].sum()
    win_rate = wins / total_trades * 100
    avg_profit = df_trades["profit_pct"].mean()
    total_return = df_trades["profit_pct"].sum()

    print(f"交易统计:")
    print(f"  总交易次数: {total_trades}")
    print(f"  盈利次数: {wins}")
    print(f"  亏损次数: {total_trades - wins}")
    print(f"  胜率: {win_rate:.2f}%")
    print(f"  平均收益: {avg_profit:.3f}%")
    print(f"  累计收益: {total_return:.2f}%")

    # 卖出类型统计
    sell_stats = sell_engine.get_statistics(trades)

    print(f"\n卖出类型分布:")
    for sell_type, stats in sell_stats["by_type"].items():
        print(f"  {sell_type}:")
        print(f"    次数: {stats['count']} ({stats['pct_of_total']:.1f}%)")
        print(f"    胜率: {stats['win_rate']:.2f}%")
        print(f"    平均收益: {stats['avg_profit']:.3f}%")

    # 指标分析
    print(f"\n选股指标统计:")
    if "upper_shadow" in df_trades.columns:
        print(f"  平均上影线: {df_trades['upper_shadow'].mean():.2f}%")
    if "prev_day_change" in df_trades.columns:
        print(f"  平均前日涨幅: {df_trades['prev_day_change'].mean():.2f}%")
    if "consecutive_up" in df_trades.columns:
        print(f"  平均连涨天数: {df_trades['consecutive_up'].mean():.2f}")

    # 保存详细交易记录
    output_path = project_root / "data" / "backtest_results" / "t1_final_trades.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_trades.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n详细交易记录已保存: {output_path}")


if __name__ == "__main__":
    # 加载数据
    df = load_data()

    # 运行回测
    run_backtest(df=df, start_date="20250225", end_date="20260225", sample_size=1000)
