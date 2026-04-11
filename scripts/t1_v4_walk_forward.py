#!/usr/bin/env python3
"""
T1 v4 Walk-Forward 验证

滚动窗口回测，检测策略在样本外的稳定性。
每个窗口独立运行回测，汇总所有窗口的结果。

训练窗口用于"观察"策略在该时段的表现（不做参数优化，因为 v4 没有可调参数）。
测试窗口用于评估样本外表现。
核心目标：测试窗口之间的胜率标准差 < 10pp。
"""

import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.t1_v4_new_backtest import V4Backtester, load_local_data, flush_print


# ---------------------------------------------------------------------------
# 月份偏移工具函数
# ---------------------------------------------------------------------------

def _add_months(yyyymm: str, months: int) -> str:
    """
    对 'YYYYMM' 格式字符串加减月份，返回 'YYYYMM'。
    例：_add_months('202502', 6) -> '202508'
    """
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])
    total = year * 12 + (month - 1) + months
    new_year = total // 12
    new_month = total % 12 + 1
    return f"{new_year:04d}{new_month:02d}"


def _month_end(yyyymm: str) -> str:
    """
    返回指定月份最后一天，格式 'YYYYMMDD'。
    例：_month_end('202502') -> '20250228'
    """
    import calendar
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}{month:02d}{last_day:02d}"


def _month_start(yyyymm: str) -> str:
    """
    返回指定月份第一天，格式 'YYYYMMDD'。
    例：_month_start('202502') -> '20250201'
    """
    return f"{yyyymm}01"


def _yyyymmdd_to_yyyymm(yyyymmdd: str) -> str:
    """'20250201' -> '202502'"""
    s = yyyymmdd.replace("-", "")
    return s[:6]


def _fmt_month_range(start_yyyymmdd: str, end_yyyymmdd: str) -> str:
    """格式化为 'YYYY.MM-YYYY.MM' 显示"""
    s = start_yyyymmdd.replace("-", "")
    e = end_yyyymmdd.replace("-", "")
    return f"{s[:4]}.{s[4:6]}-{e[:4]}.{e[4:6]}"


def _fmt_month(yyyymmdd: str) -> str:
    """格式化为 'YYYY.MM' 显示"""
    s = yyyymmdd.replace("-", "")
    return f"{s[:4]}.{s[4:6]}"


# ---------------------------------------------------------------------------
# Walk-Forward 验证器
# ---------------------------------------------------------------------------

class WalkForwardValidator:
    """Walk-forward 验证器"""

    def __init__(self, config: dict = None):
        self.config = {
            "train_months": 6,       # 训练窗口长度
            "test_months": 1,        # 测试窗口长度
            "step_months": 1,        # 滚动步长
            "start_date": "20250201",
            "end_date": "20260401",
            "max_stocks": 500,       # 每个窗口的最大股票数
            "top_n": 5,
            "min_score": 50,
            **(config or {}),
        }

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self, all_daily: pd.DataFrame, stock_list: pd.DataFrame) -> dict:
        """
        运行 walk-forward 验证。

        Args:
            all_daily:   全市场日线数据，含 ts_code/date/open/high/low/close/volume
            stock_list:  股票列表，含 ts_code/name/list_date

        Returns:
            {
                "windows": list[dict],   # 每个窗口的结果
                "summary": dict,         # 跨窗口汇总统计
            }
        """
        # 1. 生成窗口列表
        windows = self._generate_windows()
        if not windows:
            flush_print("  [警告] 未能生成任何有效窗口，请检查 start_date/end_date 设置")
            return {"windows": [], "summary": {}}

        flush_print(f"  共生成 {len(windows)} 个滚动窗口")

        # 2. 对每个窗口运行回测
        results = []
        for i, window in enumerate(windows):
            flush_print(f"\n  ── 窗口 #{i+1}/{len(windows)} ──")
            flush_print(f"     训练: {window['train_start']} ~ {window['train_end']}")
            flush_print(f"     测试: {window['test_start']} ~ {window['test_end']}")

            # 过滤该窗口所需的数据：train_start 到 test_end
            # 训练区间数据作为历史上下文（技术指标计算依赖历史数据）
            # 回测器的 start_date/end_date 设置为测试区间，让其只在测试区间产生交易
            window_df = _filter_date_range(all_daily,
                                           window["train_start"],
                                           window["test_end"])

            backtester = V4Backtester(config={
                "start_date": window["test_start"],
                "end_date": window["test_end"],
                "max_stocks": self.config["max_stocks"],
                "top_n": self.config["top_n"],
                "min_score": self.config["min_score"],
                # lookback 默认 60，训练期 6 个月数据足够预热
            })

            t0 = time.time()
            try:
                bt_result = backtester.run(window_df, stock_list)
            except Exception as e:
                flush_print(f"  [错误] 窗口 #{i+1} 回测失败: {e}")
                results.append({
                    "window_idx": i + 1,
                    "train_start": window["train_start"],
                    "train_end": window["train_end"],
                    "test_start": window["test_start"],
                    "test_end": window["test_end"],
                    "trades": 0,
                    "win_rate": 0.0,
                    "avg_pnl": 0.0,
                    "sharpe": 0.0,
                    "total_pnl": 0.0,
                    "error": str(e),
                })
                continue

            elapsed = time.time() - t0
            summary = bt_result["summary"]

            result_row = {
                "window_idx": i + 1,
                "train_start": window["train_start"],
                "train_end": window["train_end"],
                "test_start": window["test_start"],
                "test_end": window["test_end"],
                "trades": summary["total_trades"],
                "win_rate": summary["win_rate"],
                "avg_pnl": summary["avg_pnl"],
                "sharpe": summary["sharpe_ratio"],
                "total_pnl": summary["total_pnl"],
                "elapsed_s": round(elapsed, 1),
            }
            results.append(result_row)
            flush_print(
                f"     完成: {summary['total_trades']} 笔, "
                f"胜率 {summary['win_rate']*100:.1f}%, "
                f"均收益 {summary['avg_pnl']*100:+.2f}%, "
                f"夏普 {summary['sharpe_ratio']:.2f}, "
                f"耗时 {elapsed:.0f}s"
            )

        # 3. 跨窗口汇总
        summary = self._compute_cross_window_summary(results)
        return {"windows": results, "summary": summary}

    # ------------------------------------------------------------------
    # 窗口生成
    # ------------------------------------------------------------------

    def _generate_windows(self) -> list:
        """
        生成滚动窗口列表。

        从 start_date 月份开始，每次步进 step_months，
        直到 test_end 超过 end_date 为止。

        返回列表，每项：
          {
            "train_start": "YYYYMMDD",
            "train_end":   "YYYYMMDD",
            "test_start":  "YYYYMMDD",
            "test_end":    "YYYYMMDD",
          }
        """
        train_months = self.config["train_months"]
        test_months = self.config["test_months"]
        step_months = self.config["step_months"]

        # 以月份为单位操作，取起始月
        current_train_start_ym = _yyyymmdd_to_yyyymm(self.config["start_date"])
        end_ym = _yyyymmdd_to_yyyymm(self.config["end_date"])

        windows = []
        while True:
            # 训练窗口结束月
            train_end_ym = _add_months(current_train_start_ym, train_months - 1)
            # 测试窗口：紧接训练窗口之后
            test_start_ym = _add_months(train_end_ym, 1)
            test_end_ym = _add_months(test_start_ym, test_months - 1)

            # 测试窗口结束若超过 end_date 则停止
            if test_end_ym > end_ym:
                break

            windows.append({
                "train_start": _month_start(current_train_start_ym),
                "train_end":   _month_end(train_end_ym),
                "test_start":  _month_start(test_start_ym),
                "test_end":    _month_end(test_end_ym),
            })

            current_train_start_ym = _add_months(current_train_start_ym, step_months)

        return windows

    # ------------------------------------------------------------------
    # 跨窗口汇总
    # ------------------------------------------------------------------

    def _compute_cross_window_summary(self, results: list) -> dict:
        """
        跨窗口汇总统计。

        Returns:
            {
                "window_count": int,
                "mean_win_rate": float,
                "std_win_rate": float,
                "min_win_rate": float,
                "max_win_rate": float,
                "stable": bool,          # std < 0.10（10pp）
                "avg_trades_per_window": float,
                "overall_pnl": float,
                "best_window": int,      # window_idx
                "worst_window": int,     # window_idx
            }
        """
        if not results:
            return {}

        # 过滤掉出错的窗口（无 trades）
        valid = [r for r in results if "error" not in r]
        if not valid:
            return {"window_count": len(results), "error": "所有窗口均回测失败"}

        win_rates = [r["win_rate"] for r in valid]
        trades_list = [r["trades"] for r in valid]
        pnl_list = [r["total_pnl"] for r in valid]

        mean_wr = float(np.mean(win_rates))
        std_wr = float(np.std(win_rates, ddof=0)) if len(win_rates) > 1 else 0.0
        min_wr = float(np.min(win_rates))
        max_wr = float(np.max(win_rates))

        best = valid[int(np.argmax(win_rates))]
        worst = valid[int(np.argmin(win_rates))]

        overall_pnl = float(np.sum(pnl_list))
        avg_trades = float(np.mean(trades_list))

        return {
            "window_count": len(results),
            "valid_window_count": len(valid),
            "mean_win_rate": round(mean_wr, 4),
            "std_win_rate": round(std_wr, 4),
            "min_win_rate": round(min_wr, 4),
            "max_win_rate": round(max_wr, 4),
            "stable": std_wr < 0.10,   # 核心目标：标准差 < 10pp
            "avg_trades_per_window": round(avg_trades, 1),
            "overall_pnl": round(overall_pnl, 4),
            "best_window_idx": best["window_idx"],
            "best_win_rate": round(max_wr, 4),
            "worst_window_idx": worst["window_idx"],
            "worst_win_rate": round(min_wr, 4),
        }


# ---------------------------------------------------------------------------
# 数据过滤工具
# ---------------------------------------------------------------------------

def _filter_date_range(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """
    过滤日线数据，保留 [start, end] 日期区间（含两端）。
    start/end 格式均为 'YYYYMMDD'，df 中 date 列已为 'YYYY-MM-DD'。
    """
    # 统一转成 YYYY-MM-DD 进行比较
    def to_dash(d: str) -> str:
        d = d.replace("-", "")
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    s = to_dash(start)
    e = to_dash(end)
    return df[(df["date"] >= s) & (df["date"] <= e)].copy()


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------

def print_walk_forward_results(windows: list, summary: dict) -> None:
    """打印 walk-forward 验证结果表格及跨窗口汇总"""

    flush_print("\n" + "=" * 80)
    flush_print("  Walk-Forward 验证结果")
    flush_print("=" * 80)

    if not windows:
        flush_print("  （无窗口数据）")
        return

    # 表头
    header = (
        f"  {'窗口':>4}  "
        f"{'训练区间':^17}  "
        f"{'测试区间':^9}  "
        f"{'交易数':>6}  "
        f"{'胜率':>6}  "
        f"{'平均收益':>8}  "
        f"{'夏普':>5}"
    )
    flush_print(header)
    flush_print("  " + "-" * 70)

    for r in windows:
        train_range = _fmt_month_range(r["train_start"], r["train_end"])
        test_month = _fmt_month(r["test_start"])
        if "error" in r:
            flush_print(
                f"  #{r['window_idx']:<3}  "
                f"{train_range:^17}  "
                f"{test_month:^9}  "
                f"  ERROR: {r['error']}"
            )
        else:
            flush_print(
                f"  #{r['window_idx']:<3}  "
                f"{train_range:^17}  "
                f"{test_month:^9}  "
                f"{r['trades']:>6}  "
                f"{r['win_rate']*100:>5.1f}%  "
                f"{r['avg_pnl']*100:>+7.2f}%  "
                f"{r['sharpe']:>5.2f}"
            )

    # 跨窗口汇总
    flush_print("\n" + "=" * 80)
    flush_print("  跨窗口汇总")
    flush_print("=" * 80)

    if not summary:
        flush_print("  （无汇总数据）")
        return

    if "error" in summary:
        flush_print(f"  {summary['error']}")
        return

    wc = summary.get("window_count", 0)
    vwc = summary.get("valid_window_count", wc)
    flush_print(f"  窗口数: {wc}（有效: {vwc}）")

    mean_wr = summary["mean_win_rate"] * 100
    std_wr = summary["std_win_rate"] * 100
    stable_flag = "✓ < 10pp" if summary["stable"] else "✗ >= 10pp"
    flush_print(f"  平均胜率: {mean_wr:.1f}% (标准差: {std_wr:.1f}pp) {stable_flag}")

    flush_print(f"  胜率区间: {summary['min_win_rate']*100:.1f}% ~ {summary['max_win_rate']*100:.1f}%")
    flush_print(f"  平均每窗口交易数: {summary['avg_trades_per_window']:.1f}")
    flush_print(f"  整体累计收益: {summary['overall_pnl']*100:+.2f}%")
    flush_print(f"  最佳窗口: #{summary['best_window_idx']} (胜率 {summary['best_win_rate']*100:.1f}%)")
    flush_print(f"  最差窗口: #{summary['worst_window_idx']} (胜率 {summary['worst_win_rate']*100:.1f}%)")
    flush_print("=" * 80)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    flush_print("=" * 80)
    flush_print("  T1 v4 Walk-Forward 验证")
    flush_print("  训练窗口: 6 个月  |  测试窗口: 1 个月  |  滚动步长: 1 个月")
    flush_print("=" * 80)

    # 1. 加载数据
    flush_print("\n[1/3] 加载本地数据 ...")
    all_df, stock_list_df = load_local_data()

    # 2. 创建验证器
    flush_print("\n[2/3] 初始化 Walk-Forward 验证器 ...")
    validator = WalkForwardValidator(config={
        "train_months": 6,
        "test_months": 1,
        "step_months": 1,
        "start_date": "20250201",
        "end_date": "20260401",
        "max_stocks": 500,
        "top_n": 5,
        "min_score": 50,
    })

    # 3. 运行验证
    flush_print("\n[3/3] 运行 Walk-Forward 验证 ...")
    result = validator.run(all_df, stock_list_df)

    # 4. 打印结果
    print_walk_forward_results(result["windows"], result["summary"])

    flush_print("\nWalk-Forward 验证完成!")
