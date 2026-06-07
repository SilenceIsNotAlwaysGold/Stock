"""
T1 v4 策略历史回测引擎（成交现实化版）

模拟完整的 T+1 隔夜策略流程：
  每个交易日 → VetoFilter + 5维评分 → 选 Top-N → 当日收盘买入 → 次日 SellEngineV2 卖出

成交现实化（消除收益虚高）：
  - 选股仅用 ≤T 数据，T 日收盘买入，T+1 卖出（无未来函数）
  - 一字涨停买不进；一字/封死跌停卖不出 → 持仓顺延到次日
  - 滑点（冲击成本）+ 佣金双边（最低 5 元）+ 印花税千 0.5（仅卖出，2023-08 新规）
  - 停牌/退市兜底：超 max_hold_days 强制清算并计惩罚
  - 止盈止损同日双触 → 悲观取止损（杀乐观路径偏差）

指标：除收益/回撤/Sharpe 外，新增盈亏比、期望、持仓周期、年化换手、
      成本拖累、评分 IC/ICIR、事件研究（T+1..T+5 收益分布）、保守实盘预期。
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engine.t1_v4.market_rules import (
    apply_slippage,
    board_limit_pct,
    buy_cost,
    is_one_word_limit_up,
    sell_revenue,
)
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
    pnl_pct: float            # 净盈亏%（已扣成本）
    sell_reason: str
    sell_phase: int
    score: float
    is_win: bool
    hold_days: int = 1        # 实际持仓交易日数（停牌/一字会 >1）
    gross_pnl_pct: float = 0.0  # 毛盈亏%（未扣成本）
    cost_pct: float = 0.0       # 成本拖累%（佣金+印花+滑点）


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
    # ── 新增：更严谨的绩效与诊断指标 ──
    loss_count: int = 0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    payoff_ratio: float = 0.0          # 平均盈利 / 平均亏损
    expectancy_pct: float = 0.0        # 单笔期望收益%
    avg_holding_days: float = 1.0
    annual_turnover: float = 0.0       # 年化换手（买入名义 / 平均权益）
    cost_drag_pct: float = 0.0         # 累计交易成本占初始资金%
    sortino_ratio: float = 0.0
    score_ic: float = 0.0              # 评分 vs 实际收益 日均 Spearman IC
    score_icir: float = 0.0            # IC / IC标准差
    stuck_events: int = 0              # 一字/停牌导致顺延的次数
    live_decay: float = 0.4            # 假定实盘衰减比例
    expected_live_return_pct: float = 0.0  # 保守实盘预期 = 总收益*(1-衰减)
    event_study: List[dict] = field(default_factory=list)  # T+1..T+5 收益分布
    realism_notes: List[str] = field(default_factory=list)
    emotion_series: List[dict] = field(default_factory=list)  # 每日情绪周期


class T1Backtester:
    """
    T1 v4 策略回测引擎（成交现实化）

    用法:
        bt = T1Backtester(initial_cash=100000)
        result = bt.run(all_daily_data, stock_info, trade_dates)
    """

    def __init__(
        self,
        initial_cash: float = 100000.0,
        top_n: int = 2,
        market_safe_threshold: float = 8.0,
        min_total_score: float = 55.0,
        commission_rate: float = 0.00025,    # 佣金万2.5（双边）
        stamp_tax_rate: float = 0.0005,      # 印花税千0.5（2023-08-28 起，仅卖出）
        slippage_bps: float = 8.0,           # 滑点 8bp = 0.08%（买卖各一次）
        total_position_pct: float = 0.6,     # 总仓位上限（其余留现金）
        max_hold_days: int = 8,              # 一字/停牌顺延上限，超则强平
        delist_penalty: float = 0.7,         # 停牌退市兜底清算价系数（-30%）
        live_decay: float = 0.4,             # 回测→实盘保守衰减假设
        min_list_days: int = 60,             # 次新股过滤（与 VetoFilter 一致）
        # 卖出引擎参数
        sell_phase1_take_profit: float = 0.05,
        sell_phase1_stop_loss: float = -0.03,
        sell_phase2_take_profit: float = 0.05,
        sell_phase2_stop_loss: float = -0.03,
        sell_phase3_stop_loss: float = -0.025,
        ambiguous_pessimistic: bool = True,
    ):
        self.initial_cash = initial_cash
        self.top_n = top_n
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage_bps = slippage_bps
        self.total_position_pct = total_position_pct
        self.max_hold_days = max_hold_days
        self.delist_penalty = delist_penalty
        self.live_decay = live_decay
        self.min_list_days = min_list_days

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
            ambiguous_pessimistic=ambiguous_pessimistic,
        )

    # ── 数据预处理：每只股票建 日期→行 索引，O(1) 查询 ──
    @staticmethod
    def _index_data(all_daily_data: Dict[str, pd.DataFrame]):
        indexed = {}
        for ts_code, df in all_daily_data.items():
            if df is None or df.empty:
                continue
            d = df.copy()
            d["dnorm"] = d["date"].astype(str).str.replace("-", "")
            d = d.sort_values("dnorm").reset_index(drop=True)
            pos_by_date = {dn: i for i, dn in enumerate(d["dnorm"].tolist())}
            indexed[ts_code] = {"df": d, "pos": pos_by_date}
        return indexed

    def run(
        self,
        all_daily_data: Dict[str, pd.DataFrame],
        stock_info: Dict[str, dict],
        trade_dates: List[str],
        index_df: Optional[pd.DataFrame] = None,
        lookback: int = 30,
    ) -> BacktestResult:
        """
        运行回测。

        Args:
            all_daily_data: ts_code → DataFrame(date, open, high, low, close, volume, amount, turnover_rate) 升序
            stock_info: ts_code → {name, industry, list_date}
            trade_dates: 所有交易日列表 (YYYY-MM-DD 或 YYYYMMDD)，升序
            index_df: 上证指数日线，可选
            lookback: 评分需要的历史回看天数
        """
        trade_dates = [str(d).replace("-", "") for d in trade_dates]
        trade_dates = sorted(set(trade_dates))
        if len(trade_dates) < lookback + 2:
            return self._empty_result(trade_dates)

        idx = self._index_data(all_daily_data)

        cash = self.initial_cash
        holdings: List[dict] = []
        trades: List[BacktestTrade] = []
        equity_curve: List[dict] = []
        daily_returns: List[float] = []
        no_trade_days = 0
        stuck_events = 0
        total_cost = 0.0
        total_buy_notional = 0.0
        # 评分 IC：每日 (score, 净收益%) 对
        daily_ic: List[float] = []
        # 事件研究：每笔买入的 T+1..T+5 毛收益（仅诊断）
        event_rows: List[list] = []

        def _bar(ts_code: str, dnorm: str):
            e = idx.get(ts_code)
            if not e:
                return None, None
            p = e["pos"].get(dnorm)
            if p is None:
                return None, None
            return e["df"].iloc[p], p

        def _is_st(ts_code: str) -> bool:
            nm = stock_info.get(ts_code, {}).get("name", "") or ""
            return "ST" in nm.upper()

        def _close_trade(h: dict, sell_date: str, sell_px_raw: float,
                         reason: str, phase: int, gross_pct: float = 0.0):
            nonlocal cash, total_cost
            sell_px = apply_slippage(sell_px_raw, "sell", self.slippage_bps)
            revenue = sell_revenue(h["shares"], sell_px, self.commission_rate,
                                   self.stamp_tax_rate)
            pnl = revenue - h["cost"]
            cash += revenue
            # 毛收益 = 纯价格变动（无滑点/佣金/印花），基准用实际收盘
            base = h["buy_close_raw"]
            gross_pct = (sell_px_raw - base) / base if base > 0 else 0.0
            # 累计成本 = 买入侧(佣金+买滑点) + 卖出侧(佣金+印花+卖滑点)
            buy_notional = h["shares"] * base
            sell_notional = h["shares"] * sell_px_raw
            total_cost += (h["cost"] - buy_notional)
            total_cost += (sell_notional - revenue)
            net_pct = pnl / h["cost"] if h["cost"] > 0 else 0.0
            cost_pct = (net_pct - gross_pct)
            trades.append(BacktestTrade(
                buy_date=h["buy_date"],
                sell_date=sell_date,
                ts_code=h["ts_code"],
                stock_name=h["name"],
                buy_price=round(h["buy_px"], 2),
                sell_price=round(sell_px, 2),
                pnl_pct=round(net_pct * 100, 2),
                sell_reason=reason,
                sell_phase=phase,
                score=round(h["score"], 1),
                is_win=pnl > 0,
                hold_days=h["hold_days"],
                gross_pnl_pct=round(gross_pct * 100, 2),
                cost_pct=round(cost_pct * 100, 2),
            ))

        for day_idx in range(lookback, len(trade_dates)):
            today = trade_dates[day_idx]

            # ── 1. 结算到期持仓（正常 T+1；停牌/一字顺延） ──
            still_held: List[dict] = []
            day_ic_pairs: List[tuple] = []
            for h in holdings:
                row, _ = _bar(h["ts_code"], today)
                if row is None:
                    # 停牌：顺延，超上限则按上一交易日收盘 * 惩罚强平
                    h["hold_days"] += 1
                    if h["hold_days"] > self.max_hold_days:
                        gross = (h["ref_close"] * self.delist_penalty - h["buy_px"]) / h["buy_px"]
                        _close_trade(h, today, h["ref_close"] * self.delist_penalty,
                                     "forced_suspend", 9, gross)
                        stuck_events += 1
                    else:
                        still_held.append(h)
                    continue

                o, hi, lo, c = (float(row["open"]), float(row["high"]),
                                float(row["low"]), float(row["close"]))
                decision = self.sell_engine.decide(
                    buy_price=h["buy_px"],
                    next_open=o, next_high=hi, next_low=lo, next_close=c,
                    prev_close=h["ref_close"],
                )
                if decision.stuck:
                    stuck_events += 1
                    h["hold_days"] += 1
                    h["ref_close"] = c  # 更新前收，用于次日涨跌停判定
                    if h["hold_days"] > self.max_hold_days:
                        gross = (c - h["buy_px"]) / h["buy_px"]
                        _close_trade(h, today, c, "forced_timeout", 9, gross)
                    else:
                        still_held.append(h)
                    continue

                gross_pct = (decision.sell_price - h["buy_px"]) / h["buy_px"]
                _close_trade(h, today, decision.sell_price,
                             decision.sell_reason, decision.phase, gross_pct)
                day_ic_pairs.append((h["score"], trades[-1].pnl_pct))

            holdings = still_held

            if len(day_ic_pairs) >= 3:
                # 秩相关 = 排名后皮尔逊（等价 Spearman，且不依赖 scipy）
                s_arr = pd.Series([p[0] for p in day_ic_pairs]).rank()
                r_arr = pd.Series([p[1] for p in day_ic_pairs]).rank()
                ic = s_arr.corr(r_arr)
                if ic == ic:  # 非 NaN
                    daily_ic.append(ic)

            # ── 2. 计算权益（现金 + 持仓市值按今日收盘） ──
            mtm = 0.0
            for h in holdings:
                row, _ = _bar(h["ts_code"], today)
                px = float(row["close"]) if row is not None else h["ref_close"]
                mtm += h["shares"] * px
            equity = cash + mtm
            equity_curve.append({"date": today, "equity": round(equity, 2)})
            if len(equity_curve) >= 2:
                prev_eq = equity_curve[-2]["equity"]
                if prev_eq > 0:
                    daily_returns.append((equity - prev_eq) / prev_eq)

            # 最后一个交易日：无法在 T+1 卖出 → 不再开新仓
            if day_idx >= len(trade_dates) - 1:
                continue

            # ── 3. 选股（仅用 ≤ today 数据） ──
            stock_pool = []
            daily_data_slice = {}
            stock_contexts = {}
            industry_changes = {}
            sector_limit_up_counts = {}

            for ts_code, e in idx.items():
                if ts_code not in stock_info:
                    continue
                df = e["df"]
                p = e["pos"].get(today)
                if p is None or p < 4:        # 今日无数据 或 上市不足
                    continue
                # 未上市防御
                ld = stock_info[ts_code].get("list_date")
                if ld and str(ld).replace("-", "") > today:
                    continue

                df_slice = df.iloc[max(0, p - lookback + 1): p + 1].copy().reset_index(drop=True)
                if len(df_slice) < 5:
                    continue

                info = stock_info[ts_code]
                industry = info.get("industry", "") or ""
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

            total_sectors = len(industry_changes)
            industry_avg = {
                ind: sum(c for _, c in items) / len(items)
                for ind, items in industry_changes.items()
            }
            sorted_industries = sorted(industry_avg.items(), key=lambda x: x[1], reverse=True)
            industry_rank_map = {ind: i + 1 for i, (ind, _) in enumerate(sorted_industries)}
            for ts_code in stock_contexts:
                industry = stock_info.get(ts_code, {}).get("industry", "") or ""
                stock_contexts[ts_code]["sector_rank"] = industry_rank_map.get(industry)
                stock_contexts[ts_code]["total_sectors"] = total_sectors
                stock_contexts[ts_code]["sector_limit_up_count"] = sector_limit_up_counts.get(industry, 0)

            # 当日市场统计
            up_count = down_count = 0
            total_amount = 0.0
            for ts_code, e in idx.items():
                p = e["pos"].get(today)
                if p is None or p == 0:
                    continue
                df = e["df"]
                prev_c = float(df.iloc[p - 1]["close"])
                cur_c = float(df.iloc[p]["close"])
                if prev_c > 0:
                    if cur_c > prev_c:
                        up_count += 1
                    elif cur_c < prev_c:
                        down_count += 1
                total_amount += float(df.iloc[p].get("amount", 0) or 0)
            market_stats = {
                "up_count": up_count,
                "down_count": down_count,
                "total_amount": total_amount / 1e4 if total_amount > 1e6 else total_amount,
            }

            index_slice = None
            if index_df is not None and not index_df.empty:
                idx_dn = index_df["date"].astype(str).str.replace("-", "")
                idx_up = index_df[idx_dn <= today]
                if len(idx_up) >= 5:
                    index_slice = idx_up.tail(lookback).copy().reset_index(drop=True)

            global_context = {"index_df": index_slice, "market_stats": market_stats}

            top_scores = self.scorer.rank_and_select(
                stock_pool=stock_pool,
                daily_data=daily_data_slice,
                context=global_context,
                stock_contexts=stock_contexts,
                top_n=self.top_n,
            )
            if not top_scores:
                no_trade_days += 1
                continue

            # ── 4. 买入（今日收盘 + 滑点；一字涨停买不进） ──
            held_codes = {h["ts_code"] for h in holdings}
            buyable = [s for s in top_scores if s.ts_code not in held_codes]
            if not buyable:
                continue
            alloc_each = cash * self.total_position_pct / len(buyable)

            for s in buyable:
                df = daily_data_slice.get(s.ts_code)
                if df is None or len(df) < 2:
                    continue
                today_close = float(df.iloc[-1]["close"])
                if today_close <= 0:
                    continue
                t_o = float(df.iloc[-1]["open"])
                t_h = float(df.iloc[-1]["high"])
                t_l = float(df.iloc[-1]["low"])
                t_prev = float(df.iloc[-2]["close"])
                lim = board_limit_pct(s.ts_code, _is_st(s.ts_code))
                # 一字涨停：全天封死，买不进
                if is_one_word_limit_up(t_o, t_h, t_l, today_close, t_prev, lim):
                    continue

                buy_px = apply_slippage(today_close, "buy", self.slippage_bps)
                shares = math.floor(alloc_each / (buy_px * 100)) * 100
                if shares <= 0:
                    continue
                cost = buy_cost(shares, buy_px, self.commission_rate)
                if cost > cash:
                    shares = math.floor(cash / (buy_px * 100 * (1 + self.commission_rate))) * 100
                    if shares <= 0:
                        continue
                    cost = buy_cost(shares, buy_px, self.commission_rate)
                    if cost > cash:
                        continue

                cash -= cost
                total_buy_notional += shares * today_close

                # 事件研究：买入后 T+1..T+5 收盘价（仅诊断，不参与决策）
                e = idx[s.ts_code]
                p = e["pos"][today]
                fwd = []
                for k in range(1, 6):
                    if p + k < len(e["df"]):
                        fc = float(e["df"].iloc[p + k]["close"])
                        fwd.append((fc - today_close) / today_close)
                    else:
                        fwd.append(None)
                event_rows.append(fwd)

                holdings.append({
                    "ts_code": s.ts_code,
                    "name": s.stock_name,
                    "buy_date": today,
                    "buy_px": buy_px,            # 含滑点的成本基准
                    "buy_close_raw": today_close,  # 实际收盘（成本/前收基准）
                    "ref_close": today_close,     # 卖出日前收（每顺延一日更新）
                    "shares": shares,
                    "cost": cost,
                    "score": s.total_score,
                    "hold_days": 1,
                    "fwd": fwd,
                })

        # 回测结束：剩余持仓按最后交易日收盘强平
        last_day = trade_dates[-1]
        for h in holdings:
            row, _ = _bar(h["ts_code"], last_day)
            px = float(row["close"]) if row is not None else h["ref_close"]
            gross = (px - h["buy_px"]) / h["buy_px"]
            _close_trade(h, last_day, px, "backtest_end", 9, gross)

        return self._calc_metrics(
            trades=trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            final_cash=cash,
            trade_dates=trade_dates,
            no_trade_days=no_trade_days,
            stuck_events=stuck_events,
            total_cost=total_cost,
            total_buy_notional=total_buy_notional,
            daily_ic=daily_ic,
            event_rows=event_rows,
        )

    def _calc_metrics(
        self,
        trades: List[BacktestTrade],
        equity_curve: List[dict],
        daily_returns: List[float],
        final_cash: float,
        trade_dates: List[str],
        no_trade_days: int,
        stuck_events: int = 0,
        total_cost: float = 0.0,
        total_buy_notional: float = 0.0,
        daily_ic: Optional[List[float]] = None,
        event_rows: Optional[List[list]] = None,
    ) -> BacktestResult:
        """计算回测指标"""
        total_trades = len(trades)
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        win_count = len(wins)
        loss_count = len(losses)
        pnl_pcts = [t.pnl_pct for t in trades]

        final_equity = equity_curve[-1]["equity"] if equity_curve else final_cash
        total_return = (final_equity - self.initial_cash) / self.initial_cash
        trading_days = len(equity_curve)
        annual_return = total_return * (252 / max(trading_days, 1))

        # 最大回撤
        max_dd = 0.0
        peak = self.initial_cash
        for pt in equity_curve:
            if pt["equity"] > peak:
                peak = pt["equity"]
            if peak > 0:
                max_dd = max(max_dd, (peak - pt["equity"]) / peak)

        # Sharpe / Sortino（年化）
        sharpe = sortino = 0.0
        if daily_returns and len(daily_returns) > 1:
            arr = np.array(daily_returns)
            avg_ret = arr.mean()
            std_ret = arr.std(ddof=1)
            if std_ret > 0:
                sharpe = avg_ret / std_ret * np.sqrt(252)
            downside = arr[arr < 0]
            if len(downside) > 0:
                dstd = downside.std(ddof=1) if len(downside) > 1 else abs(downside[0])
                if dstd > 0:
                    sortino = avg_ret / dstd * np.sqrt(252)

        # 盈亏比 / 期望
        gross_wins = sum(t.pnl_pct for t in wins)
        gross_losses = abs(sum(t.pnl_pct for t in losses))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (
            float("inf") if gross_wins > 0 else 0.0)
        avg_win = (gross_wins / win_count) if win_count else 0.0
        avg_loss = (gross_losses / loss_count) if loss_count else 0.0
        payoff = (avg_win / avg_loss) if avg_loss > 0 else (
            float("inf") if avg_win > 0 else 0.0)
        win_rate = win_count / max(total_trades, 1)
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

        avg_hold = float(np.mean([t.hold_days for t in trades])) if trades else 1.0
        cost_drag = total_cost / self.initial_cash * 100 if self.initial_cash else 0.0
        avg_equity = float(np.mean([p["equity"] for p in equity_curve])) if equity_curve else self.initial_cash
        years = max(trading_days, 1) / 252
        annual_turnover = (total_buy_notional / avg_equity / years) if avg_equity > 0 else 0.0

        # 评分 IC / ICIR
        score_ic = score_icir = 0.0
        if daily_ic:
            ic_arr = np.array(daily_ic)
            score_ic = float(ic_arr.mean())
            if len(ic_arr) > 1 and ic_arr.std(ddof=1) > 0:
                score_icir = score_ic / ic_arr.std(ddof=1)

        # 事件研究：T+1..T+5 毛收益分布（买入后持有 N 日，独立于卖出逻辑，暴露真实 edge 与衰减）
        event_study = []
        if event_rows:
            for k in range(5):
                vals = [r[k] for r in event_rows if k < len(r) and r[k] is not None]
                if vals:
                    a = np.array(vals)
                    event_study.append({
                        "horizon": f"T+{k+1}",
                        "n": len(vals),
                        "avg_ret_pct": round(float(a.mean()) * 100, 2),
                        "median_ret_pct": round(float(np.median(a)) * 100, 2),
                        "win_rate": round(float((a > 0).mean()), 4),
                    })

        # 月度收益
        monthly = {}
        for t in trades:
            month = t.sell_date[:6] if len(t.sell_date) >= 6 else t.sell_date
            month = f"{month[:4]}-{month[4:6]}" if len(month) >= 6 else month
            monthly.setdefault(month, []).append(t.pnl_pct)
        monthly_returns = [
            {
                "month": m,
                "trades": len(pnls),
                "avg_pnl_pct": round(float(np.mean(pnls)), 2),
                "total_pnl_pct": round(sum(pnls), 2),
                "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 2),
            }
            for m, pnls in sorted(monthly.items())
        ]

        notes = [
            "选股仅用≤T数据，T日收盘买入(含滑点)，T+1卖出 — 无未来函数",
            "一字涨停买不进；一字/封死跌停卖不出，持仓顺延",
            f"成本：佣金双边{self.commission_rate*1e4:.1f}‱(最低5元) + 印花税{self.stamp_tax_rate*1e4:.1f}‱(卖) + 滑点{self.slippage_bps:.0f}bp双边",
            "止盈止损同日双触取悲观(止损优先)",
            f"停牌/退市超{self.max_hold_days}日强平(系数{self.delist_penalty})",
            f"保守实盘预期 = 回测总收益 ×(1-{self.live_decay:.0%}) [经验衰减,非保证]",
            "幸存者偏差：需调用方提供退市股历史数据才能完全消除",
        ]

        return BacktestResult(
            start_date=trade_dates[0] if trade_dates else "",
            end_date=trade_dates[-1] if trade_dates else "",
            initial_cash=self.initial_cash,
            final_cash=round(final_equity, 2),
            total_return_pct=round(total_return * 100, 2),
            annual_return_pct=round(annual_return * 100, 2),
            max_drawdown_pct=round(max_dd * 100, 2),
            total_trades=total_trades,
            win_count=win_count,
            win_rate=round(win_rate, 4),
            avg_pnl_pct=round(float(np.mean(pnl_pcts)), 2) if pnl_pcts else 0.0,
            max_win_pct=round(max(pnl_pcts), 2) if pnl_pcts else 0.0,
            max_loss_pct=round(min(pnl_pcts), 2) if pnl_pcts else 0.0,
            sharpe_ratio=round(sharpe, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
            trading_days=trading_days,
            no_trade_days=no_trade_days,
            trades=trades,
            equity_curve=equity_curve,
            monthly_returns=monthly_returns,
            loss_count=loss_count,
            avg_win_pct=round(avg_win, 2),
            avg_loss_pct=round(avg_loss, 2),
            payoff_ratio=round(payoff, 2) if payoff != float("inf") else 999.0,
            expectancy_pct=round(expectancy, 2),
            avg_holding_days=round(avg_hold, 2),
            annual_turnover=round(annual_turnover, 2),
            cost_drag_pct=round(cost_drag, 2),
            sortino_ratio=round(sortino, 2),
            score_ic=round(score_ic, 4),
            score_icir=round(score_icir, 2),
            stuck_events=stuck_events,
            live_decay=self.live_decay,
            expected_live_return_pct=round(total_return * 100 * (1 - self.live_decay), 2),
            event_study=event_study,
            realism_notes=notes,
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
