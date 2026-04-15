"""
T1 v4 策略历史回测引擎

模拟完整的 T+1 隔夜策略流程：
  每个交易日 → VetoFilter + 5维评分 → 选 Top-N → 当日收盘买入 → 次日 SellEngineV2 卖出

支持：
  - 逐日模拟，生成完整交易记录
  - 胜率、收益率、最大回撤、Sharpe 等指标
  - 仓位管理和共振加分（可选）
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engine.t1_v4.scorer import T1V4Scorer
from engine.t1_v4.sell_engine_v2 import SellEngineV2

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """回测交易记录"""
    buy_date: str
    sell_date: str
    ts_code: str
    stock_name: str
    buy_price: float
    sell_price: float
    pnl_pct: float
    sell_reason: str
    sell_phase: int
    score: float
    is_win: bool


@dataclass
class BacktestResult:
    """回测结果"""
    start_date: str
    end_date: str
    initial_cash: float
    final_cash: float
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    total_trades: int
    win_count: int
    win_rate: float
    avg_pnl_pct: float
    max_win_pct: float
    max_loss_pct: float
    sharpe_ratio: float
    profit_factor: float
    trading_days: int
    no_trade_days: int          # 大盘不安全导致不交易的天数
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)
    monthly_returns: List[dict] = field(default_factory=list)


class T1Backtester:
    """
    T1 v4 策略回测引擎

    用法:
        bt = T1Backtester(initial_cash=100000)
        result = bt.run(all_daily_data, stock_info, start_date, end_date)
    """

    def __init__(
        self,
        initial_cash: float = 100000.0,
        top_n: int = 2,
        market_safe_threshold: float = 8.0,
        min_total_score: float = 55.0,
        commission_rate: float = 0.00025,    # 佣金万2.5
        stamp_tax_rate: float = 0.001,       # 印花税千1（卖出）
        # 卖出引擎参数
        sell_phase1_take_profit: float = 0.05,
        sell_phase1_stop_loss: float = -0.03,
        sell_phase2_take_profit: float = 0.05,
        sell_phase2_stop_loss: float = -0.03,
        sell_phase3_stop_loss: float = -0.025,
    ):
        self.initial_cash = initial_cash
        self.top_n = top_n
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate

        self.scorer = T1V4Scorer(
            top_n=top_n,
            market_safe_threshold=market_safe_threshold,
            min_total_score=min_total_score,
        )
        self.sell_engine = SellEngineV2(
            phase1_take_profit=sell_phase1_take_profit,
            phase1_stop_loss=sell_phase1_stop_loss,
            phase2_take_profit=sell_phase2_take_profit,
            phase2_stop_loss=sell_phase2_stop_loss,
            phase3_stop_loss=sell_phase3_stop_loss,
        )

    def run(
        self,
        all_daily_data: Dict[str, pd.DataFrame],
        stock_info: Dict[str, dict],
        trade_dates: List[str],
        lookback: int = 30,
    ) -> BacktestResult:
        """
        运行回测。

        Args:
            all_daily_data: ts_code → DataFrame(date, open, high, low, close, volume, amount, turnover_rate)
                           按日期升序排列
            stock_info: ts_code → {name, industry, list_date}
            trade_dates: 所有交易日列表 (YYYY-MM-DD 或 YYYYMMDD)，升序
            lookback: 评分需要的历史回看天数

        Returns:
            BacktestResult
        """
        if len(trade_dates) < lookback + 2:
            return self._empty_result(trade_dates)

        cash = self.initial_cash
        trades: List[BacktestTrade] = []
        equity_curve: List[dict] = []
        daily_returns: List[float] = []
        no_trade_days = 0

        # 预处理：按日期建索引
        date_set = set(trade_dates)

        for day_idx in range(lookback, len(trade_dates) - 1):
            today = trade_dates[day_idx]
            tomorrow = trade_dates[day_idx + 1]

            # 构建当日截面数据（每只股票取截止到今天的 lookback 天数据）
            stock_pool = []
            daily_data_slice = {}
            stock_contexts = {}

            # 板块排名计算
            industry_changes = {}
            sector_limit_up_counts = {}

            for ts_code, df in all_daily_data.items():
                if ts_code not in stock_info:
                    continue

                # 找到今天在 df 中的位置
                date_col = df["date"].astype(str).str.replace("-", "")
                today_norm = today.replace("-", "")
                mask = date_col <= today_norm
                df_up_to_today = df[mask]

                if len(df_up_to_today) < 5:
                    continue

                # 取最近 lookback 天
                df_slice = df_up_to_today.tail(lookback).copy().reset_index(drop=True)

                info = stock_info[ts_code]
                industry = info.get("industry", "")

                # 计算当日涨跌幅（用于板块排名）
                if len(df_slice) >= 2:
                    prev_close = float(df_slice.iloc[-2]["close"])
                    today_close = float(df_slice.iloc[-1]["close"])
                    if prev_close > 0:
                        change = (today_close - prev_close) / prev_close
                        if industry:
                            industry_changes.setdefault(industry, []).append((ts_code, change))
                            if change >= 0.098:
                                sector_limit_up_counts[industry] = sector_limit_up_counts.get(industry, 0) + 1

                stock_pool.append({
                    "ts_code": ts_code,
                    "name": info.get("name", ""),
                    "list_date": info.get("list_date"),
                })
                daily_data_slice[ts_code] = df_slice

                last_row = df_slice.iloc[-1]
                stock_contexts[ts_code] = {
                    "turnover_rate": float(last_row.get("turnover_rate", 0)) or None,
                    "is_suspended": False,
                    "money_flow_df": None,
                    "north_flow_df": None,
                    "fina_df": None,
                    "pe": None,
                    "industry_pe_median": None,
                }

            # 计算板块排名
            total_sectors = len(industry_changes)
            industry_avg = {
                ind: sum(c for _, c in items) / len(items)
                for ind, items in industry_changes.items()
            }
            sorted_industries = sorted(industry_avg.items(), key=lambda x: x[1], reverse=True)
            industry_rank_map = {ind: i + 1 for i, (ind, _) in enumerate(sorted_industries)}

            for ts_code in stock_contexts:
                info = stock_info.get(ts_code, {})
                industry = info.get("industry", "")
                stock_contexts[ts_code]["sector_rank"] = industry_rank_map.get(industry)
                stock_contexts[ts_code]["total_sectors"] = total_sectors
                stock_contexts[ts_code]["sector_limit_up_count"] = sector_limit_up_counts.get(industry, 0)

            global_context = {"index_df": None, "market_stats": None}

            # 评分选股
            top_scores = self.scorer.rank_and_select(
                stock_pool=stock_pool,
                daily_data=daily_data_slice,
                context=global_context,
                stock_contexts=stock_contexts,
                top_n=self.top_n,
            )

            if not top_scores:
                no_trade_days += 1
                equity_curve.append({"date": today, "equity": round(cash, 2)})
                continue

            # 模拟买入（当日收盘价）+ 次日卖出
            day_pnl = 0.0
            for s in top_scores:
                df = daily_data_slice.get(s.ts_code)
                if df is None or df.empty:
                    continue

                buy_price = float(df.iloc[-1]["close"])
                if buy_price <= 0:
                    continue

                # 简化仓位：等分
                alloc = cash / len(top_scores) * 0.6  # 60% 总仓位均分
                shares = math.floor(alloc / (buy_price * 100)) * 100
                if shares <= 0:
                    continue

                # 找次日数据
                tomorrow_df = all_daily_data.get(s.ts_code)
                if tomorrow_df is None:
                    continue

                tomorrow_norm = tomorrow.replace("-", "")
                date_col = tomorrow_df["date"].astype(str).str.replace("-", "")
                tm_mask = date_col == tomorrow_norm
                tm_rows = tomorrow_df[tm_mask]

                if tm_rows.empty:
                    continue

                tm_row = tm_rows.iloc[0]
                next_open = float(tm_row["open"])
                next_high = float(tm_row["high"])
                next_low = float(tm_row["low"])
                next_close = float(tm_row["close"])

                if next_open <= 0:
                    continue

                # SellEngineV2 决策
                decision = self.sell_engine.decide(
                    buy_price=buy_price,
                    next_open=next_open,
                    next_high=next_high,
                    next_low=next_low,
                    next_close=next_close,
                )

                # 计算交易成本
                buy_cost = shares * buy_price * (1 + self.commission_rate)
                sell_revenue = shares * decision.sell_price * (1 - self.commission_rate - self.stamp_tax_rate)
                trade_pnl = sell_revenue - buy_cost
                trade_pnl_pct = trade_pnl / buy_cost

                cash += trade_pnl
                day_pnl += trade_pnl

                trades.append(BacktestTrade(
                    buy_date=today,
                    sell_date=tomorrow,
                    ts_code=s.ts_code,
                    stock_name=s.stock_name,
                    buy_price=buy_price,
                    sell_price=decision.sell_price,
                    pnl_pct=round(trade_pnl_pct * 100, 2),
                    sell_reason=decision.sell_reason,
                    sell_phase=decision.phase,
                    score=round(s.total_score, 1),
                    is_win=trade_pnl > 0,
                ))

            equity_curve.append({"date": today, "equity": round(cash, 2)})
            if len(equity_curve) >= 2:
                prev_eq = equity_curve[-2]["equity"]
                if prev_eq > 0:
                    daily_returns.append((cash - prev_eq) / prev_eq)

        # 计算汇总指标
        result = self._calc_metrics(
            trades=trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            final_cash=cash,
            trade_dates=trade_dates,
            no_trade_days=no_trade_days,
        )
        return result

    def _calc_metrics(
        self,
        trades: List[BacktestTrade],
        equity_curve: List[dict],
        daily_returns: List[float],
        final_cash: float,
        trade_dates: List[str],
        no_trade_days: int,
    ) -> BacktestResult:
        """计算回测指标"""
        total_trades = len(trades)
        win_count = sum(1 for t in trades if t.is_win)
        pnl_pcts = [t.pnl_pct for t in trades]

        total_return = (final_cash - self.initial_cash) / self.initial_cash
        trading_days = len(equity_curve)
        annual_return = total_return * (252 / max(trading_days, 1))

        # 最大回撤
        max_dd = 0.0
        peak = self.initial_cash
        for pt in equity_curve:
            if pt["equity"] > peak:
                peak = pt["equity"]
            dd = (peak - pt["equity"]) / peak
            max_dd = max(max_dd, dd)

        # Sharpe ratio（年化）
        if daily_returns and len(daily_returns) > 1:
            avg_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns, ddof=1)
            sharpe = (avg_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        # 盈亏比
        gross_wins = sum(t.pnl_pct for t in trades if t.is_win)
        gross_losses = abs(sum(t.pnl_pct for t in trades if not t.is_win))
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf") if gross_wins > 0 else 0.0

        # 月度收益
        monthly = {}
        for t in trades:
            month = t.sell_date[:7]  # YYYY-MM
            monthly.setdefault(month, []).append(t.pnl_pct)
        monthly_returns = [
            {
                "month": m,
                "trades": len(pnls),
                "avg_pnl_pct": round(np.mean(pnls), 2),
                "total_pnl_pct": round(sum(pnls), 2),
                "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 2),
            }
            for m, pnls in sorted(monthly.items())
        ]

        return BacktestResult(
            start_date=trade_dates[0] if trade_dates else "",
            end_date=trade_dates[-1] if trade_dates else "",
            initial_cash=self.initial_cash,
            final_cash=round(final_cash, 2),
            total_return_pct=round(total_return * 100, 2),
            annual_return_pct=round(annual_return * 100, 2),
            max_drawdown_pct=round(max_dd * 100, 2),
            total_trades=total_trades,
            win_count=win_count,
            win_rate=round(win_count / max(total_trades, 1), 4),
            avg_pnl_pct=round(np.mean(pnl_pcts), 2) if pnl_pcts else 0.0,
            max_win_pct=round(max(pnl_pcts), 2) if pnl_pcts else 0.0,
            max_loss_pct=round(min(pnl_pcts), 2) if pnl_pcts else 0.0,
            sharpe_ratio=round(sharpe, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
            trading_days=len(equity_curve),
            no_trade_days=no_trade_days,
            trades=trades,
            equity_curve=equity_curve,
            monthly_returns=monthly_returns,
        )

    def _empty_result(self, trade_dates) -> BacktestResult:
        return BacktestResult(
            start_date=trade_dates[0] if trade_dates else "",
            end_date=trade_dates[-1] if trade_dates else "",
            initial_cash=self.initial_cash,
            final_cash=self.initial_cash,
            total_return_pct=0.0,
            annual_return_pct=0.0,
            max_drawdown_pct=0.0,
            total_trades=0,
            win_count=0,
            win_rate=0.0,
            avg_pnl_pct=0.0,
            max_win_pct=0.0,
            max_loss_pct=0.0,
            sharpe_ratio=0.0,
            profit_factor=0.0,
            trading_days=0,
            no_trade_days=0,
        )
