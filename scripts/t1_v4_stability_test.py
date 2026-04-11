#!/usr/bin/env python3
"""
T1 v4 多样本稳定性验证

在不同规模的股票样本集上运行回测，对比胜率和收益的一致性。
核心目标：大样本胜率不应比小样本显著下降（下降 < 5pp）。
"""

import sys
import random
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.t1_v4_new_backtest import V4Backtester, load_local_data


class StabilityTester:
    """多样本稳定性验证器"""

    def __init__(self, config: dict = None):
        self.config = {
            "sample_sizes": [500, 1000, 2000],  # 三级样本量（全市场单独处理）
            "num_trials": 3,                      # 每个样本量随机抽样几次
            "random_seed": 42,
            "start_date": "20250301",
            "end_date": "20260301",
            "top_n": 5,
            "min_score": 50,
            **(config or {}),
        }

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self, all_daily: pd.DataFrame, stock_list: pd.DataFrame) -> dict:
        """
        运行稳定性测试

        流程：
        1. 对每个 sample_size，随机抽样 num_trials 次
        2. 每次抽样运行 V4Backtester
        3. 记录每次的胜率、收益、交易数
        4. 最后跑一次全市场（不抽样）
        5. 对比各级别的结果

        Returns:
            {
                "trials": list[dict],   # 每次试验结果
                "summary": dict,        # 汇总对比
            }
        """
        all_codes = list(all_daily["ts_code"].unique())
        total_codes = len(all_codes)
        print(f"  全市场股票数: {total_codes}")

        trials = []
        sample_sizes = self.config["sample_sizes"]
        num_trials = self.config["num_trials"]
        base_seed = self.config["random_seed"]

        # 对每个 sample_size 运行多次抽样试验
        for size in sample_sizes:
            # 如果样本量超过全市场，跳过
            if size > total_codes:
                print(f"  样本量 {size} 超过全市场股票数 {total_codes}，跳过")
                continue

            for trial_idx in range(num_trials):
                label = f"{size}#{trial_idx + 1}"
                # 用不同种子确保每次抽样不同，但可复现
                seed = base_seed + size + trial_idx
                random.seed(seed)
                sample_codes = random.sample(all_codes, size)

                print(f"\n  [{label}] 抽样 {size} 只股票 (seed={seed}) ...")
                result = self._run_single_trial(
                    all_daily=all_daily,
                    stock_list=stock_list,
                    sample_codes=sample_codes,
                    label=label,
                )
                result["size_group"] = size
                result["trial_num"] = trial_idx + 1
                trials.append(result)

        # 全市场试验（不抽样）
        print(f"\n  [全市场] 使用全部 {total_codes} 只股票 ...")
        full_result = self._run_single_trial(
            all_daily=all_daily,
            stock_list=stock_list,
            sample_codes=all_codes,
            label="全市场",
        )
        full_result["size_group"] = total_codes
        full_result["trial_num"] = 0  # 0 表示全市场
        trials.append(full_result)

        # 汇总对比
        summary = self._compute_summary(trials)

        return {
            "trials": trials,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # 单次试验
    # ------------------------------------------------------------------

    def _run_single_trial(
        self,
        all_daily: pd.DataFrame,
        stock_list: pd.DataFrame,
        sample_codes: list,
        label: str,
    ) -> dict:
        """运行单次试验"""
        sample_set = set(sample_codes)

        # 过滤 stock_list 和 all_daily 到 sample_codes
        filtered_daily = all_daily[all_daily["ts_code"].isin(sample_set)].copy()
        filtered_stock_list = stock_list[stock_list["ts_code"].isin(sample_set)].copy()

        # 补充 filtered_daily 中有但 stock_list 中没有的股票（V4Backtester 内部会自动补充）
        # 这里不需要额外处理

        # 创建 V4Backtester，max_stocks=0 表示不再内部抽样（已在外部过滤）
        backtester = V4Backtester(config={
            "start_date": self.config["start_date"],
            "end_date": self.config["end_date"],
            "max_stocks": 0,  # 不限制，已在外部过滤
            "top_n": self.config["top_n"],
            "min_score": self.config["min_score"],
        })

        result = backtester.run(filtered_daily, filtered_stock_list)
        summary = result["summary"]

        return {
            "label": label,
            "sample_size": len(sample_codes),
            "trades": summary["total_trades"],
            "win_rate": summary["win_rate"],
            "avg_pnl": summary["avg_pnl"],
            "sharpe": summary["sharpe_ratio"],
            "max_drawdown": summary["max_drawdown"],
        }

    # ------------------------------------------------------------------
    # 汇总对比
    # ------------------------------------------------------------------

    def _compute_summary(self, trials: list) -> dict:
        """
        汇总对比

        按 size_group 分组，计算每组的均值/标准差
        对比不同组之间的差异
        """
        # 分离全市场试验和抽样试验
        sample_trials = [t for t in trials if t["trial_num"] != 0]
        full_market = next((t for t in trials if t["trial_num"] == 0), None)

        # 按 size_group 分组
        groups = {}
        for t in sample_trials:
            g = t["size_group"]
            if g not in groups:
                groups[g] = []
            groups[g].append(t)

        group_stats = {}
        for size, group_trials in sorted(groups.items()):
            win_rates = [t["win_rate"] for t in group_trials]
            avg_pnls = [t["avg_pnl"] for t in group_trials]
            sharpes = [t["sharpe"] for t in group_trials]
            trades_list = [t["trades"] for t in group_trials]

            group_stats[size] = {
                "mean_win_rate": float(np.mean(win_rates)),
                "std_win_rate": float(np.std(win_rates)) if len(win_rates) > 1 else 0.0,
                "mean_avg_pnl": float(np.mean(avg_pnls)),
                "mean_sharpe": float(np.mean(sharpes)),
                "mean_trades": float(np.mean(trades_list)),
                "num_trials": len(group_trials),
            }

        # 计算最小样本组的均值胜率（第一个样本量）
        sorted_sizes = sorted(group_stats.keys())
        smallest_win_rate = group_stats[sorted_sizes[0]]["mean_win_rate"] if sorted_sizes else 0.0
        full_market_win_rate = full_market["win_rate"] if full_market else 0.0

        # 胜率下降（小样本 -> 全市场），单位 pp
        win_rate_drop = (smallest_win_rate - full_market_win_rate) * 100

        # 各组间最大标准差（pp）
        all_std = [gs["std_win_rate"] * 100 for gs in group_stats.values()]
        max_std = max(all_std) if all_std else 0.0

        # 稳定性判断
        is_stable_drop = win_rate_drop < 5.0
        is_stable_std = max_std < 3.0

        return {
            "group_stats": group_stats,
            "full_market": full_market,
            "smallest_win_rate_pp": smallest_win_rate * 100,
            "full_market_win_rate_pp": full_market_win_rate * 100,
            "win_rate_drop_pp": win_rate_drop,
            "max_group_std_pp": max_std,
            "is_stable_drop": is_stable_drop,
            "is_stable_std": is_stable_std,
        }


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------

def print_stability_report(result: dict) -> None:
    """打印稳定性验证报告"""
    trials = result["trials"]
    summary = result["summary"]
    group_stats = summary["group_stats"]
    full_market = summary["full_market"]

    print("\n" + "=" * 70)
    print("====== 多样本稳定性验证 ======")
    print("=" * 70)

    # 表头
    print(f"\n{'样本量':<10} {'试验':<8} {'股票数':>7} {'交易数':>7} {'胜率':>8} {'平均收益':>10} {'夏普':>6}")
    print("-" * 70)

    # 按 size_group 排序打印（不含全市场）
    sample_trials = [t for t in trials if t["trial_num"] != 0]
    # 按 size_group, trial_num 排序
    sample_trials.sort(key=lambda x: (x["size_group"], x["trial_num"]))

    current_group = None
    for t in sample_trials:
        size = t["size_group"]

        if current_group is not None and current_group != size:
            # 打印上一组的均值行
            gs = group_stats[current_group]
            std_pp = gs["std_win_rate"] * 100
            print(
                f"{'--- ' + str(current_group) + ' 均值 ---':<18}"
                f"  {int(gs['mean_trades']):>7}"
                f"  {gs['mean_win_rate'] * 100:>7.1f}%"
                f"  {gs['mean_avg_pnl'] * 100:>+9.2f}%"
                f"  {gs['mean_sharpe']:>5.1f}"
                f"  (±{std_pp:.1f}pp)"
            )
            print()

        current_group = size
        print(
            f"{size:<10} {'#' + str(t['trial_num']):<8}"
            f"  {t['sample_size']:>7}"
            f"  {t['trades']:>7}"
            f"  {t['win_rate'] * 100:>7.1f}%"
            f"  {t['avg_pnl'] * 100:>+9.2f}%"
            f"  {t['sharpe']:>5.1f}"
        )

    # 打印最后一组均值
    if current_group is not None and current_group in group_stats:
        gs = group_stats[current_group]
        std_pp = gs["std_win_rate"] * 100
        print(
            f"{'--- ' + str(current_group) + ' 均值 ---':<18}"
            f"  {int(gs['mean_trades']):>7}"
            f"  {gs['mean_win_rate'] * 100:>7.1f}%"
            f"  {gs['mean_avg_pnl'] * 100:>+9.2f}%"
            f"  {gs['mean_sharpe']:>5.1f}"
            f"  (±{std_pp:.1f}pp)"
        )

    # 全市场行
    if full_market:
        print()
        print(
            f"{'全市场':<10} {'--':<8}"
            f"  {full_market['sample_size']:>7}"
            f"  {full_market['trades']:>7}"
            f"  {full_market['win_rate'] * 100:>7.1f}%"
            f"  {full_market['avg_pnl'] * 100:>+9.2f}%"
            f"  {full_market['sharpe']:>5.1f}"
        )

    # 稳定性评估
    print("\n" + "=" * 70)
    print("====== 稳定性评估 ======")
    print("=" * 70)

    drop = summary["win_rate_drop_pp"]
    max_std = summary["max_group_std_pp"]
    is_stable_drop = summary["is_stable_drop"]
    is_stable_std = summary["is_stable_std"]

    smallest_pp = summary["smallest_win_rate_pp"]
    full_pp = summary["full_market_win_rate_pp"]

    drop_mark = "✓" if is_stable_drop else "✗"
    std_mark = "✓" if is_stable_std else "✗"

    print(
        f"最小样本→全市场 胜率: {smallest_pp:.1f}% → {full_pp:.1f}%  "
        f"下降: {drop:.1f}pp (< 5pp {drop_mark})"
    )
    print(
        f"最大组间标准差: {max_std:.1f}pp (< 3pp {std_mark})"
    )

    overall = is_stable_drop and is_stable_std
    if overall:
        print("\n结论: 策略在不同样本规模下表现稳定，未发现显著过拟合迹象。")
    else:
        issues = []
        if not is_stable_drop:
            issues.append(f"胜率下降 {drop:.1f}pp 超过 5pp 阈值")
        if not is_stable_std:
            issues.append(f"组间标准差 {max_std:.1f}pp 超过 3pp 阈值")
        print(f"\n警告: 策略稳定性存在问题 - {'; '.join(issues)}")

    print("=" * 70)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  T1 v4 多样本稳定性验证")
    print("=" * 70)

    # 1. 加载数据
    print("\n[1/3] 加载本地数据 ...")
    all_df, stock_list_df = load_local_data()

    # 2. 创建稳定性测试器
    print("\n[2/3] 初始化稳定性测试器 ...")
    tester = StabilityTester(config={
        "sample_sizes": [500, 1000, 2000],
        "num_trials": 3,
        "random_seed": 42,
        "start_date": "20250301",
        "end_date": "20260301",
        "top_n": 5,
        "min_score": 50,
    })

    # 3. 运行稳定性测试
    print("\n[3/3] 运行稳定性测试 ...")
    result = tester.run(all_df, stock_list_df)

    # 4. 打印报告
    print_stability_report(result)

    print("\n稳定性验证完成!")
