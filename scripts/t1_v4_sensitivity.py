#!/usr/bin/env python3
"""
T1 v4 参数敏感性分析

对每个评分维度的权重做 +/-20% 扰动，观察胜率变化。
核心目标：任意单维度扰动 20%，胜率变化 < 3pp。

扰动方式：
    不修改 engine/t1_v4/ 任何文件。
    用 PerturbedScorer 包装 T1V4Scorer，在 score_stock() 输出上对
    指定维度的分数做乘法缩放，然后重算 total_score。
    再将 V4Backtester.scorer 替换为 PerturbedScorer 实例。
"""

import sys
from pathlib import Path
from copy import deepcopy
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.t1_v4_new_backtest import V4Backtester, load_local_data
from engine.t1_v4.scorer import T1V4Scorer, StockScore


# ---------------------------------------------------------------------------
# 扰动评分包装器
# ---------------------------------------------------------------------------

class PerturbedScorer:
    """
    对 T1V4Scorer 的输出做维度缩放。

    在 score_stock() 返回的 StockScore 上，将指定维度乘以 factor，
    然后重算 total_score = sum(5 个维度)。

    rank_and_select() 直接委托给 base，但先 monkey-patch base.score_stock
    指向本类的 score_stock，使其在排序时也使用扰动分。
    """

    # 5 个维度名称到 StockScore 字段的映射
    DIM_FIELD_MAP = {
        "tech":        "tech_score",
        "capital":     "capital_score",
        "fundamental": "fundamental_score",
        "sector":      "sector_score",
        "market":      "market_score",
    }

    def __init__(self, base_scorer: T1V4Scorer, dim: str, factor: float):
        if dim not in self.DIM_FIELD_MAP:
            raise ValueError(f"未知维度: {dim}，可选: {list(self.DIM_FIELD_MAP)}")
        self.base = base_scorer
        self.dim = dim
        self.factor = factor
        self._field = self.DIM_FIELD_MAP[dim]

    def _perturb(self, score: StockScore) -> StockScore:
        """对 StockScore 的指定维度做缩放，重算 total。"""
        if score.vetoed:
            return score
        setattr(score, self._field, getattr(score, self._field) * self.factor)
        score.total_score = (
            score.tech_score
            + score.capital_score
            + score.fundamental_score
            + score.sector_score
            + score.market_score
        )
        return score

    def score_stock(self, *args, **kwargs) -> StockScore:
        score = self.base.score_stock(*args, **kwargs)
        return self._perturb(score)

    def rank_and_select(
        self,
        stock_pool: List[dict],
        daily_data: Dict[str, pd.DataFrame],
        context: dict,
        stock_contexts: Optional[Dict[str, dict]] = None,
        top_n: Optional[int] = None,
    ) -> List[StockScore]:
        """
        复用 base.rank_and_select 的市场面预过滤逻辑，
        但对每只股票的最终评分使用 self.score_stock（已含扰动）。
        """
        if top_n is None:
            top_n = self.base.config["top_n"]

        market_safe_threshold = self.base.config["market_safe_threshold"]
        min_total_score = self.base.config["min_total_score"]

        # 市场面单独计算一次（所有股票共享）
        market_result = self.base.market_scorer.score(
            index_df=context.get("index_df"),
            market_stats=context.get("market_stats"),
        )
        market_score_val = float(market_result.get("market_total", 0.0))

        if market_score_val < market_safe_threshold:
            return []

        # 对每只股票调用含扰动的 score_stock
        all_scores: List[StockScore] = []
        for stock_info in stock_pool:
            ts_code = str(stock_info.get("ts_code", ""))
            stock_name = str(stock_info.get("name", ""))

            daily_df = daily_data.get(ts_code)
            if daily_df is None:
                daily_df = pd.DataFrame()

            stock_ctx = dict(context)
            if stock_contexts and ts_code in stock_contexts:
                stock_ctx.update(stock_contexts[ts_code])
            if "list_date" in stock_info and "list_date" not in stock_ctx:
                stock_ctx["list_date"] = stock_info["list_date"]

            stock_score = self.score_stock(
                ts_code=ts_code,
                stock_name=stock_name,
                daily_df=daily_df,
                context=stock_ctx,
            )
            all_scores.append(stock_score)

        valid_scores = [s for s in all_scores if not s.vetoed]
        valid_scores = [s for s in valid_scores if s.total_score >= min_total_score]
        valid_scores.sort(key=lambda s: s.total_score, reverse=True)
        return valid_scores[:top_n]

    # 代理其他可能被访问的属性/方法给 base
    def __getattr__(self, name):
        return getattr(self.base, name)


# ---------------------------------------------------------------------------
# 敏感性分析器
# ---------------------------------------------------------------------------

class SensitivityAnalyzer:
    """
    参数敏感性分析器

    流程：
    1. 跑一次基准回测（原始权重）
    2. 对每个维度，分别做 +20% 和 -20% 的扰动回测
    3. 比较扰动后胜率与基准胜率的差异，判断是否 < max_delta_pp
    """

    # 5 个维度及其默认满分（仅用于文档说明，不影响实际计算）
    DIMENSIONS = {
        "tech":        30,
        "capital":     25,
        "fundamental": 15,
        "sector":      15,
        "market":      15,
    }

    def __init__(self, config: dict = None):
        self.config = {
            "perturbation": 0.20,     # 扰动幅度 20%
            "max_stocks": 500,
            "start_date": "20250301",
            "end_date": "20260301",
            "top_n": 5,
            "min_score": 50,
            "max_delta_pp": 3.0,      # 最大允许胜率变化（百分点）
            **(config or {}),
        }

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def run(self, all_daily: pd.DataFrame, stock_list: pd.DataFrame) -> dict:
        """
        运行敏感性分析。

        Returns:
            {
                "baseline": dict,        # 基准结果 summary
                "perturbations": list,   # 每次扰动的结果
                "summary": dict,         # 汇总（最大偏移、通过数等）
            }
        """
        perturbation = self.config["perturbation"]
        max_delta_pp = self.config["max_delta_pp"]

        backtester_cfg = {
            "start_date": self.config["start_date"],
            "end_date":   self.config["end_date"],
            "max_stocks": self.config["max_stocks"],
            "top_n":      self.config["top_n"],
            "min_score":  self.config["min_score"],
        }

        # ---- 基准回测 ----
        _print("  运行基准回测 ...")
        baseline_result = self._run_one(backtester_cfg, all_daily, stock_list, dim=None, factor=1.0)
        baseline_win_rate = baseline_result["win_rate"]
        baseline_trades   = baseline_result["total_trades"]
        baseline_avg_pnl  = baseline_result["avg_pnl"]

        _print(f"  基准胜率: {baseline_win_rate*100:.1f}%, 交易 {baseline_trades} 笔, 均收益 {baseline_avg_pnl*100:+.2f}%")

        # ---- 逐维度扰动 ----
        perturbations = []
        dims = list(self.DIMENSIONS.keys())
        total_cases = len(dims) * 2
        case_idx = 0

        for dim in dims:
            for sign, factor in [("+", 1 + perturbation), ("-", 1 - perturbation)]:
                case_idx += 1
                label = f"{sign}{int(perturbation*100)}%"
                _print(f"  [{case_idx}/{total_cases}] {dim} {label} ...")

                result = self._run_one(backtester_cfg, all_daily, stock_list, dim=dim, factor=factor)

                delta_wr   = result["win_rate"] - baseline_win_rate
                delta_pnl  = result["avg_pnl"]  - baseline_avg_pnl
                passed     = abs(delta_wr * 100) < max_delta_pp

                perturbations.append({
                    "dim":       dim,
                    "direction": label,
                    "factor":    round(factor, 4),
                    "win_rate":  result["win_rate"],
                    "delta_wr":  round(delta_wr, 6),     # 小数形式，如 0.009
                    "avg_pnl":   result["avg_pnl"],
                    "delta_pnl": round(delta_pnl, 6),
                    "trades":    result["total_trades"],
                    "passed":    passed,
                })

        # ---- 汇总 ----
        all_passed   = all(p["passed"] for p in perturbations)
        pass_count   = sum(1 for p in perturbations if p["passed"])
        total_count  = len(perturbations)
        max_delta_abs = max(abs(p["delta_wr"] * 100) for p in perturbations) if perturbations else 0.0
        worst         = max(perturbations, key=lambda p: abs(p["delta_wr"]), default=None)

        summary_result = {
            "all_passed":    all_passed,
            "pass_count":    pass_count,
            "total_count":   total_count,
            "max_delta_pp":  round(max_delta_abs, 4),
            "worst_case":    f"{worst['dim']} {worst['direction']}" if worst else "N/A",
            "threshold_pp":  max_delta_pp,
        }

        return {
            "baseline":      {"win_rate": baseline_win_rate,
                              "total_trades": baseline_trades,
                              "avg_pnl": baseline_avg_pnl},
            "perturbations": perturbations,
            "summary":       summary_result,
        }

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _run_one(
        self,
        backtester_cfg: dict,
        all_daily: pd.DataFrame,
        stock_list: pd.DataFrame,
        dim: Optional[str],
        factor: float,
    ) -> dict:
        """创建（扰动）回测器并运行，返回 summary dict。"""
        backtester = V4Backtester(config=backtester_cfg)

        if dim is not None:
            # 替换 scorer 为扰动包装器
            base_scorer = backtester.scorer
            backtester.scorer = PerturbedScorer(base_scorer, dim=dim, factor=factor)

        result = backtester.run(all_daily, stock_list)
        return result["summary"]


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def _print(msg: str) -> None:
    print(msg, flush=True)


def print_results(analysis: dict) -> None:
    baseline     = analysis["baseline"]
    perturbations = analysis["perturbations"]
    summary      = analysis["summary"]

    _print("")
    _print("=" * 72)
    _print("  参数敏感性分析")
    _print("=" * 72)

    wr_pct  = baseline["win_rate"] * 100
    avg_pct = baseline["avg_pnl"]  * 100
    _print(
        f"  基准: 胜率 {wr_pct:.1f}%, "
        f"交易 {baseline['total_trades']} 笔, "
        f"平均收益 {avg_pct:+.2f}%"
    )
    _print("")

    # 表头
    _print(
        f"  {'维度':<14}{'扰动':>5}  {'胜率':>6}  {'变化':>7}  "
        f"{'均收益':>7}  {'变化':>7}  {'通过':>4}"
    )
    _print(f"  {'-'*62}")

    for p in perturbations:
        wr      = p["win_rate"] * 100
        dwr     = p["delta_wr"] * 100
        apnl    = p["avg_pnl"]  * 100
        dpnl    = p["delta_pnl"] * 100
        mark    = "V" if p["passed"] else "X"
        dwr_str = f"{dwr:+.1f}pp"
        _print(
            f"  {p['dim']:<14}{p['direction']:>5}  "
            f"{wr:>5.1f}%  {dwr_str:>7}  "
            f"{apnl:>+6.2f}%  {dpnl:>+6.2f}%  {mark:>4}"
        )

    _print("")
    _print("=" * 72)
    _print("  汇总")
    _print("=" * 72)
    worst_str = summary["worst_case"]
    max_d     = summary["max_delta_pp"]
    threshold = summary["threshold_pp"]
    ok_max    = "< " + str(threshold) + "pp V" if max_d < threshold else ">= " + str(threshold) + "pp X"
    _print(f"  最大胜率偏移: {max_d:.2f}pp ({worst_str}) — {ok_max}")

    pass_cnt  = summary["pass_count"]
    total_cnt = summary["total_count"]
    all_ok    = "V" if summary["all_passed"] else "X"
    _print(f"  所有维度通过: {pass_cnt}/{total_cnt} {all_ok}")
    _print("")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _print("=" * 72)
    _print("  T1 v4 参数敏感性分析")
    _print("  目标：任意单维度 +/-20% 扰动，胜率变化 < 3pp")
    _print("=" * 72)

    # 1. 加载数据
    _print("\n[1/2] 加载本地数据 ...")
    all_df, stock_list_df = load_local_data()

    # 2. 运行分析
    _print("\n[2/2] 运行敏感性分析（共 11 次回测）...")
    analyzer = SensitivityAnalyzer(config={
        "start_date": "20250301",
        "end_date":   "20260301",
        "max_stocks": 500,
        "top_n":      5,
        "min_score":  50,
        "perturbation": 0.20,
        "max_delta_pp": 3.0,
    })

    analysis = analyzer.run(all_df, stock_list_df)
    print_results(analysis)

    # 3. 最终判定
    if analysis["summary"]["all_passed"]:
        _print("  结论: 策略权重鲁棒性通过 — 所有扰动胜率变化均 < 3pp V")
    else:
        failed = [
            f"{p['dim']} {p['direction']} ({p['delta_wr']*100:+.2f}pp)"
            for p in analysis["perturbations"]
            if not p["passed"]
        ]
        _print(f"  结论: 部分扰动超出阈值 X")
        for f in failed:
            _print(f"    - {f}")
