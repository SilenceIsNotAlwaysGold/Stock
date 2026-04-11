#!/usr/bin/env python3
"""
T1 v4 多维度评分策略 - 完整回测

端到端流程：
1. 数据加载（本地 CSV 或 Tushare）
2. 每个交易日：
   a. VetoFilter 过滤
   b. 5 维评分（仅用技术面，资金面/基本面/板块面/市场面标记为 TODO 待数据支撑）
   c. 排序选 Top-N
   d. SellEngineV2 模拟次日卖出
3. 统计输出：胜率/收益率/夏普/最大回撤/月度分布/卖出原因分布
"""

import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.t1_v4.scorer import T1V4Scorer
from engine.t1_v4.sell_engine_v2 import SellEngineV2

# ── 数据文件路径 ──
ALL_DAILY_FILE = PROJECT_ROOT / "data" / "yearly" / "all_stocks_daily.csv"
STOCK_LIST_FILE = PROJECT_ROOT / "data" / "stock_list.csv"


def flush_print(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_local_data() -> tuple:
    """
    从本地 CSV 加载日线数据和股票列表。

    Returns:
        (all_df, stock_list_df)
        all_df: 含 ts_code/date/open/high/low/close/volume 列
        stock_list_df: 含 ts_code/name/list_date 列
    """
    flush_print(f"  读取 {ALL_DAILY_FILE} ...")
    all_df = pd.read_csv(ALL_DAILY_FILE, dtype={"ts_code": str})

    # 统一列名
    rename_map = {}
    if "trade_date" in all_df.columns:
        rename_map["trade_date"] = "date"
    if "vol" in all_df.columns:
        rename_map["vol"] = "volume"
    if rename_map:
        all_df = all_df.rename(columns=rename_map)

    # 统一日期格式为 YYYY-MM-DD
    all_df["date"] = all_df["date"].astype(str).str.replace("-", "")
    all_df["date"] = pd.to_datetime(all_df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

    # 数值列强制转换
    for col in ["open", "high", "low", "close", "volume"]:
        if col in all_df.columns:
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")

    flush_print(f"  总行数: {len(all_df):,}, 股票数: {all_df['ts_code'].nunique()}")

    # 股票列表
    if STOCK_LIST_FILE.exists():
        flush_print(f"  读取 {STOCK_LIST_FILE} ...")
        stock_list_df = pd.read_csv(STOCK_LIST_FILE, dtype={"ts_code": str})
        # 确保必要列存在
        for col in ["ts_code", "name", "list_date"]:
            if col not in stock_list_df.columns:
                stock_list_df[col] = ""
    else:
        flush_print("  stock_list.csv 不存在，尝试从 Tushare 获取 ...")
        stock_list_df = _fetch_stock_list_from_tushare()

    return all_df, stock_list_df


def _fetch_stock_list_from_tushare() -> pd.DataFrame:
    """从 Tushare 获取股票列表（fallback）"""
    try:
        import tushare as ts
        from app.config import Settings
        settings = Settings()
        ts.set_token(settings.TUSHARE_TOKEN)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange="", list_status="L",
                             fields="ts_code,name,list_date")
        if df is not None and not df.empty:
            flush_print(f"  Tushare 股票列表: {len(df)} 只")
            return df
    except Exception as e:
        flush_print(f"  Tushare 获取失败: {e}")
    # 返回空 DataFrame，后续会用 ts_code 填充
    return pd.DataFrame(columns=["ts_code", "name", "list_date"])


# ---------------------------------------------------------------------------
# 核心回测器
# ---------------------------------------------------------------------------

class V4Backtester:
    """v4 回测器：技术面评分 + SellEngineV2"""

    def __init__(self, config: dict = None):
        # market_safe_threshold=0：回测中没有市场统计数据，放宽市场面门槛
        self.scorer = T1V4Scorer(market_safe_threshold=0)
        self.sell_engine = SellEngineV2()
        self.config = {
            "start_date": "20250301",
            "end_date": "20260301",
            "max_stocks": 1000,   # 最多回测几只（0 = 全部）
            "top_n": 5,           # 每天选几只
            "min_score": 50,      # 最低总分
            "lookback": 60,       # 技术面计算所需的最少历史天数
            **(config or {}),
        }

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self, all_daily: pd.DataFrame, stock_list: pd.DataFrame) -> dict:
        """
        运行回测。

        Args:
            all_daily: 全市场日线数据，含 ts_code/date/open/high/low/close/volume
            stock_list: 股票列表，含 ts_code/name/list_date

        Returns:
            {
                "trades": list[dict],
                "summary": dict,
                "monthly": pd.DataFrame,
                "sell_reasons": dict,
            }
        """
        start_date = self.config["start_date"]
        end_date = self.config["end_date"]
        top_n = self.config["top_n"]
        min_score = self.config["min_score"]
        lookback = self.config["lookback"]

        # 1. 按 ts_code 分组，预先建 dict — 避免每次循环 filter
        flush_print("  建立股票缓存 ...")
        stock_groups: Dict[str, pd.DataFrame] = {}
        for code, grp in all_daily.groupby("ts_code"):
            grp_sorted = grp.sort_values("date").reset_index(drop=True)
            stock_groups[str(code)] = grp_sorted

        # 2. 股票信息 dict
        stock_info_map: Dict[str, dict] = {}
        for _, row in stock_list.iterrows():
            code = str(row["ts_code"])
            stock_info_map[code] = {
                "name": str(row.get("name", "")),
                "list_date": str(row.get("list_date", "")),
            }
        # 补充 stock_groups 中没有信息的股票（最少给个空 info）
        for code in stock_groups:
            if code not in stock_info_map:
                stock_info_map[code] = {"name": code, "list_date": ""}

        # 3. 获取全部交易日列表（在回测区间内）
        all_dates = sorted(all_daily["date"].unique())
        trade_dates = [d for d in all_dates if start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:] <= d <= end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:]]
        flush_print(f"  回测区间: {trade_dates[0] if trade_dates else 'N/A'} ~ {trade_dates[-1] if trade_dates else 'N/A'}, 共 {len(trade_dates)} 个交易日")

        # 4. 确定回测股票池
        eligible_codes = list(stock_groups.keys())
        max_stocks = self.config["max_stocks"]
        if max_stocks > 0 and len(eligible_codes) > max_stocks:
            import random
            random.seed(42)
            eligible_codes = random.sample(eligible_codes, max_stocks)
        flush_print(f"  回测股票数: {len(eligible_codes)}")

        # 5. 主回测循环
        trades: List[dict] = []
        total_days = len(trade_dates)
        last_pct = -1

        flush_print(f"\n  开始逐日回测 ...")
        t_start = time.time()

        for day_idx, trade_date in enumerate(trade_dates):
            # 进度提示（每 10%）
            pct = int(day_idx / total_days * 10) * 10
            if pct != last_pct:
                elapsed = time.time() - t_start
                flush_print(f"    {pct:3d}%  ({day_idx}/{total_days}) 已用 {elapsed:.0f}s, 累计 {len(trades)} 笔交易")
                last_pct = pct

            # 5a. 收集当天各股票的数据切片
            stock_pool: List[dict] = []
            daily_data: Dict[str, pd.DataFrame] = {}

            for code in eligible_codes:
                df = stock_groups.get(code)
                if df is None:
                    continue

                # 找到当天在 df 中的位置
                idx_arr = df.index[df["date"] == trade_date].tolist()
                if not idx_arr:
                    continue
                idx = idx_arr[0]

                # 需要至少 lookback 天历史数据
                if idx < lookback:
                    continue

                # 取到当天为止的历史切片（用于技术面计算）
                slice_df = df.iloc[: idx + 1].copy()
                daily_data[code] = slice_df

                info = stock_info_map[code]
                stock_pool.append({
                    "ts_code": code,
                    "name": info["name"],
                    "list_date": info["list_date"],
                })

            if not stock_pool:
                continue

            # 5b. 简化版 context（目前只有技术面是真实的）
            global_context = {
                "money_flow_df": None,         # TODO: 接入真实资金流数据
                "north_flow_df": None,          # TODO: 接入北向资金
                "index_df": None,               # TODO: 接入指数日线
                "market_stats": None,           # TODO: 接入市场统计
            }

            # 5c. 为每只股票构建个股 context
            stock_contexts: Dict[str, dict] = {}
            for sp in stock_pool:
                code = sp["ts_code"]
                stock_contexts[code] = {
                    "turnover_rate": None,             # TODO: 接入 daily_basic
                    "fina_df": None,                   # TODO: 接入财务数据
                    "pe": None,                        # TODO: 接入 PE
                    "industry_pe_median": None,        # TODO: 接入行业 PE
                    "sector_rank": None,               # TODO: 接入板块排名
                    "total_sectors": None,             # TODO: 接入板块总数
                    "sector_limit_up_count": 0,
                    "sector_consecutive_strong_days": 0,
                    "list_date": sp["list_date"],
                    "is_suspended": False,
                }

            # 5d. 调用 scorer.rank_and_select()
            try:
                top_scores = self.scorer.rank_and_select(
                    stock_pool=stock_pool,
                    daily_data=daily_data,
                    context=global_context,
                    stock_contexts=stock_contexts,
                    top_n=top_n,
                )
            except Exception as e:
                # 单日评分失败不中断整体回测
                continue

            # 按 min_score 再过滤一遍（rank_and_select 里已有 config 控制，但 config 里
            # 的 min_total_score 用的是 scorer 自己的配置，此处用回测器配置）
            top_scores = [s for s in top_scores if s.total_score >= min_score]

            # 5e. 对选出的候选，找次日数据，用 sell_engine.decide()
            for score_obj in top_scores:
                code = score_obj.ts_code
                df = stock_groups.get(code)
                if df is None:
                    continue

                idx_arr = df.index[df["date"] == trade_date].tolist()
                if not idx_arr:
                    continue
                idx = idx_arr[0]

                # 次日必须存在
                if idx + 1 >= len(df):
                    continue

                today_row = df.iloc[idx]
                next_row = df.iloc[idx + 1]

                buy_price = float(today_row["close"])
                if buy_price <= 0:
                    continue

                next_open = float(next_row["open"])
                next_high = float(next_row["high"])
                next_low = float(next_row["low"])
                next_close = float(next_row["close"])

                # 跳过次日数据异常的
                if any(v <= 0 for v in [next_open, next_high, next_low, next_close]):
                    continue
                if next_low > next_high:
                    continue

                try:
                    decision = self.sell_engine.decide(
                        buy_price=buy_price,
                        next_open=next_open,
                        next_high=next_high,
                        next_low=next_low,
                        next_close=next_close,
                    )
                except Exception:
                    continue

                trades.append({
                    "date": trade_date,
                    "next_date": str(next_row["date"]),
                    "ts_code": code,
                    "stock_name": score_obj.stock_name,
                    "buy_price": round(buy_price, 2),
                    "sell_price": decision.sell_price,
                    "sell_reason": decision.sell_reason,
                    "sell_phase": decision.phase,
                    "pnl_pct": decision.pnl_pct,
                    "is_win": decision.pnl_pct > 0,
                    "total_score": round(score_obj.total_score, 2),
                    "tech_score": round(score_obj.tech_score, 2),
                    "capital_score": round(score_obj.capital_score, 2),
                    "fundamental_score": round(score_obj.fundamental_score, 2),
                    "sector_score": round(score_obj.sector_score, 2),
                    "market_score": round(score_obj.market_score, 2),
                })

        elapsed_total = time.time() - t_start
        flush_print(f"  回测完成，耗时 {elapsed_total:.1f}s，共 {len(trades)} 笔交易\n")

        # 6. 汇总统计
        summary = self._compute_summary(trades)
        monthly_df = self._compute_monthly(trades)
        sell_reasons = self._compute_sell_reasons(trades)

        return {
            "trades": trades,
            "summary": summary,
            "monthly": monthly_df,
            "sell_reasons": sell_reasons,
        }

    # ------------------------------------------------------------------
    # 统计计算
    # ------------------------------------------------------------------

    def _compute_summary(self, trades: list) -> dict:
        """计算汇总统计"""
        if not trades:
            return {
                "total_trades": 0,
                "win_count": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "max_pnl": 0.0,
                "min_pnl": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "avg_score": 0.0,
            }

        pnls = [t["pnl_pct"] for t in trades]
        win_count = sum(1 for p in pnls if p > 0)
        total = len(pnls)

        # 夏普比率（年化，250 交易日）
        sharpe = 0.0
        if total > 1:
            std = float(np.std(pnls))
            if std > 0:
                sharpe = round(float(np.mean(pnls)) / std * np.sqrt(250), 2)

        # 最大回撤（按累计 pnl 序列）
        cumulative = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative)
        drawdown = cumulative - peak
        max_drawdown = round(float(np.min(drawdown)), 4) if len(drawdown) > 0 else 0.0

        avg_score = round(float(np.mean([t["total_score"] for t in trades])), 2)

        return {
            "total_trades": total,
            "win_count": win_count,
            "win_rate": round(win_count / total, 4),
            "total_pnl": round(float(np.sum(pnls)), 4),
            "avg_pnl": round(float(np.mean(pnls)), 6),
            "max_pnl": round(float(np.max(pnls)), 4),
            "min_pnl": round(float(np.min(pnls)), 4),
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "avg_score": avg_score,
        }

    def _compute_monthly(self, trades: list) -> pd.DataFrame:
        """月度统计：按 date 的前 7 位（YYYY-MM）分组"""
        if not trades:
            return pd.DataFrame(columns=["month", "trades", "wins", "win_rate", "pnl"])

        monthly: Dict[str, list] = {}
        for t in trades:
            month = str(t["date"])[:7]
            if month not in monthly:
                monthly[month] = []
            monthly[month].append(t)

        rows = []
        for month in sorted(monthly.keys()):
            mt = monthly[month]
            wins = sum(1 for t in mt if t["is_win"])
            total = len(mt)
            pnl = round(sum(t["pnl_pct"] for t in mt), 4)
            rows.append({
                "month": month,
                "trades": total,
                "wins": wins,
                "win_rate": round(wins / total, 4) if total > 0 else 0.0,
                "pnl": pnl,
            })

        return pd.DataFrame(rows)

    def _compute_sell_reasons(self, trades: list) -> dict:
        """卖出原因分布：{reason: {count, avg_pnl, win_rate}}"""
        if not trades:
            return {}

        reasons: Dict[str, dict] = {}
        for t in trades:
            r = t["sell_reason"]
            if r not in reasons:
                reasons[r] = {"count": 0, "pnls": []}
            reasons[r]["count"] += 1
            reasons[r]["pnls"].append(t["pnl_pct"])

        result = {}
        for r, data in reasons.items():
            pnls = data["pnls"]
            wins = sum(1 for p in pnls if p > 0)
            result[r] = {
                "count": data["count"],
                "avg_pnl": round(float(np.mean(pnls)), 6),
                "win_rate": round(wins / len(pnls), 4),
            }
        return result


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------

def print_summary(summary: dict) -> None:
    flush_print("=" * 72)
    flush_print("  汇总统计")
    flush_print("=" * 72)
    flush_print(f"  交易总数:   {summary['total_trades']:>6} 笔")
    flush_print(f"  盈利交易:   {summary['win_count']:>6} 笔  胜率: {summary['win_rate']*100:.1f}%")
    flush_print(f"  总收益:     {summary['total_pnl']*100:>+8.2f}%")
    flush_print(f"  均收益:     {summary['avg_pnl']*100:>+8.3f}%")
    flush_print(f"  最大单笔:   {summary['max_pnl']*100:>+8.2f}%")
    flush_print(f"  最小单笔:   {summary['min_pnl']*100:>+8.2f}%")
    flush_print(f"  夏普比率:   {summary['sharpe_ratio']:>8.2f}")
    flush_print(f"  最大回撤:   {summary['max_drawdown']*100:>+8.2f}%")
    flush_print(f"  平均评分:   {summary['avg_score']:>8.2f}")


def print_monthly(monthly_df: pd.DataFrame) -> None:
    if monthly_df.empty:
        flush_print("  （无月度数据）")
        return
    flush_print("=" * 72)
    flush_print("  月度分布")
    flush_print("=" * 72)
    flush_print(f"  {'月份':>8}  {'交易':>5}  {'胜率':>6}  {'收益':>8}")
    flush_print(f"  {'-'*40}")
    for _, row in monthly_df.iterrows():
        flush_print(
            f"  {row['month']:>8}  {int(row['trades']):>4}笔"
            f"  {row['win_rate']*100:>5.1f}%"
            f"  {row['pnl']*100:>+7.2f}%"
        )


def print_sell_reasons(sell_reasons: dict) -> None:
    flush_print("=" * 72)
    flush_print("  卖出原因分布")
    flush_print("=" * 72)
    flush_print(f"  {'原因':<26}  {'次数':>5}  {'胜率':>6}  {'均收益':>8}")
    flush_print(f"  {'-'*56}")
    for reason, stats in sorted(sell_reasons.items(), key=lambda x: -x[1]["count"]):
        flush_print(
            f"  {reason:<26}  {stats['count']:>4}次"
            f"  {stats['win_rate']*100:>5.1f}%"
            f"  {stats['avg_pnl']*100:>+7.3f}%"
        )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    flush_print("=" * 72)
    flush_print("  T1 v4 多维度评分策略 - 端到端回测（新版）")
    flush_print("  注意：当前仅技术面评分为真实计算，其他维度为 TODO")
    flush_print("=" * 72)

    # 1. 加载数据
    flush_print("\n[1/3] 加载本地数据 ...")
    all_df, stock_list_df = load_local_data()

    # 2. 创建回测器并运行
    flush_print("\n[2/3] 初始化回测器 ...")
    backtester = V4Backtester(config={
        "start_date": "20250301",
        "end_date": "20260301",
        "max_stocks": 1000,
        "top_n": 5,
        "min_score": 50,
    })

    flush_print("\n[3/3] 运行回测 ...")
    result = backtester.run(all_df, stock_list_df)

    trades = result["trades"]
    summary = result["summary"]
    monthly_df = result["monthly"]
    sell_reasons = result["sell_reasons"]

    # 3. 打印结果
    flush_print("")
    print_summary(summary)
    flush_print("")
    print_monthly(monthly_df)
    flush_print("")
    print_sell_reasons(sell_reasons)

    flush_print("\n回测完成!")
