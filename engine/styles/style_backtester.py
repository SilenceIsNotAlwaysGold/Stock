"""
风格通用回测器

任意 TradingStyle 走同一套成交现实化（与阶段1 一致）：
  - 选股仅用 ≤T 数据，T 收盘买入(+滑点，跳过一字涨停)
  - 一字涨/跌停封死 → 无法成交，持仓顺延，超 max_hold_days 强平
  - 佣金双边(最低5元) + 印花税千0.5(卖) + 滑点
  - 复用 T1Backtester._calc_metrics 输出完整指标 + 事件研究

支持任意持仓周期（短线1日 / 打板1日 / 波段~10日 / 长线~40日）。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import pandas as pd

from engine.emotion_cycle import compute_emotion
from engine.styles.base import DayContext, TradingStyle
from engine.t1_v4.backtester import BacktestResult, BacktestTrade, T1Backtester
from engine.t1_v4.market_rules import (
    apply_slippage,
    board_limit_pct,
    buy_cost,
    is_one_word_limit_down,
    is_one_word_limit_up,
    sell_revenue,
)


class StyleBacktester:
    def __init__(
        self,
        style: TradingStyle,
        initial_cash: float = 100000.0,
        commission_rate: float = 0.00025,
        stamp_tax_rate: float = 0.0005,
        slippage_bps: float = 8.0,
        delist_penalty: float = 0.7,
        live_decay: float = 0.4,
    ):
        self.style = style
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage_bps = slippage_bps
        self.delist_penalty = delist_penalty
        self.live_decay = live_decay
        # 复用阶段1 的指标计算
        self._M = T1Backtester(
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            stamp_tax_rate=stamp_tax_rate,
            slippage_bps=slippage_bps,
            max_hold_days=style.max_hold_days,
            delist_penalty=delist_penalty,
            live_decay=live_decay,
        )

    @staticmethod
    def _index(all_daily_data: Dict[str, pd.DataFrame]):
        # 共享高速索引：numpy 列数组 + 向量化涨跌停/连板预计算
        from engine.fast_index import build_fast_index
        return build_fast_index(all_daily_data)

    def run(
        self,
        all_daily_data: Dict[str, pd.DataFrame],
        stock_info: Dict[str, dict],
        trade_dates: List[str],
        index_df: Optional[pd.DataFrame] = None,
        lookback: int = 60,
    ) -> BacktestResult:
        st = self.style
        lookback = max(lookback, st.min_lookback)
        trade_dates = sorted(set(str(d).replace("-", "") for d in trade_dates))
        if len(trade_dates) < lookback + 2:
            return self._M._empty_result(trade_dates)

        idx = self._index(all_daily_data)
        cash = self.initial_cash
        holdings: List[dict] = []
        trades: List[BacktestTrade] = []
        equity_curve: List[dict] = []
        daily_returns: List[float] = []
        no_trade_days = 0
        stuck_events = 0
        total_cost = 0.0
        total_buy_notional = 0.0
        daily_ic: List[float] = []
        event_rows: List[list] = []
        emotion_series: List[dict] = []

        def _at(ts_code, dn):
            """返回 (entry, pos) 或 (None, None)；热循环用 numpy 数组下标，零 pandas。"""
            e = idx.get(ts_code)
            if not e:
                return None, None
            p = e["pos"].get(dn)
            return (e, p) if p is not None else (None, None)

        def _close(h, sell_date, sell_px_raw, reason):
            nonlocal cash, total_cost
            sell_px = apply_slippage(sell_px_raw, "sell", self.slippage_bps)
            rev = sell_revenue(h["shares"], sell_px, self.commission_rate,
                               self.stamp_tax_rate)
            pnl = rev - h["cost"]
            cash += rev
            base = h["buy_close_raw"]
            gross = (sell_px_raw - base) / base if base > 0 else 0.0
            total_cost += (h["cost"] - h["shares"] * base)
            total_cost += (h["shares"] * sell_px_raw - rev)
            net = pnl / h["cost"] if h["cost"] > 0 else 0.0
            trades.append(BacktestTrade(
                buy_date=h["buy_date"], sell_date=sell_date,
                ts_code=h["ts_code"], stock_name=h["name"],
                buy_price=round(h["buy_px"], 2), sell_price=round(sell_px, 2),
                pnl_pct=round(net * 100, 2), sell_reason=reason,
                sell_phase=0, score=round(h["score"], 1), is_win=pnl > 0,
                hold_days=h["hold_days"], gross_pnl_pct=round(gross * 100, 2),
                cost_pct=round((net - gross) * 100, 2),
            ))
            return net * 100

        for di in range(lookback, len(trade_dates)):
            today = trade_dates[di]
            still: List[dict] = []
            ic_pairs = []
            for h in holdings:
                e, p = _at(h["ts_code"], today)
                h["hold_days"] = di - h["buy_idx"]
                if h["hold_days"] <= 0:                 # 进场当日不结算
                    still.append(h)
                    continue
                if p is None:                          # 停牌
                    if h["hold_days"] > st.max_hold_days:
                        _close(h, today, h["ref_close"] * self.delist_penalty,
                               "forced_suspend")
                        stuck_events += 1
                    else:
                        still.append(h)
                    continue
                o, hi, lo, c = (float(e["o"][p]), float(e["h"][p]),
                                float(e["l"][p]), float(e["c"][p]))
                h.setdefault("recent_closes", []).append(c)
                pct = e["pct"]
                bar = {"open": o, "high": hi, "low": lo, "close": c}
                ex = st.should_exit(h, bar, h["hold_days"], h["ref_close"])

                blocked = (
                    is_one_word_limit_down(o, hi, lo, c, h["ref_close"], pct)
                    or is_one_word_limit_up(o, hi, lo, c, h["ref_close"], pct)
                )
                if ex.stuck or (ex.sell and blocked):
                    stuck_events += 1
                    h["ref_close"] = c
                    if h["hold_days"] > st.max_hold_days:
                        _close(h, today, c, "forced_timeout")
                    else:
                        still.append(h)
                    continue
                if ex.sell:
                    r = _close(h, today, ex.price, ex.reason)
                    ic_pairs.append((h["score"], r))
                else:
                    h["ref_close"] = c
                    if h["hold_days"] > st.max_hold_days:
                        _close(h, today, c, "forced_timeout")
                    else:
                        still.append(h)
            holdings = still

            if len(ic_pairs) >= 3:
                # 秩相关 = 排名后皮尔逊（等价 Spearman，不依赖 scipy）
                ic = pd.Series([p[0] for p in ic_pairs]).rank().corr(
                    pd.Series([p[1] for p in ic_pairs]).rank())
                if ic == ic:
                    daily_ic.append(ic)

            mtm = 0.0
            for h in holdings:
                e, p = _at(h["ts_code"], today)
                mtm += h["shares"] * (float(e["c"][p]) if p is not None
                                      else h["ref_close"])
            equity = cash + mtm
            equity_curve.append({"date": today, "equity": round(equity, 2)})
            if len(equity_curve) >= 2 and equity_curve[-2]["equity"] > 0:
                daily_returns.append(
                    (equity - equity_curve[-2]["equity"]) / equity_curve[-2]["equity"])

            if di >= len(trade_dates) - 1:
                continue

            # 选股（仅 ≤ today 数据）；needs_slices=False 的风格跳过昂贵切片构建
            slices = {}
            if st.needs_slices:
                for ts_code, e in idx.items():
                    if ts_code not in stock_info:
                        continue
                    p = e["pos"].get(today)
                    if p is None or p < 4:
                        continue
                    ld = stock_info[ts_code].get("list_date")
                    if ld and str(ld).replace("-", "") > today:
                        continue
                    slices[ts_code] = e["df"].iloc[max(0, p - lookback + 1):p + 1] \
                        .reset_index(drop=True)
            up = dn = 0
            amt = 0.0
            for ts_code, e in idx.items():
                p = e["pos"].get(today)
                if p is None or p == 0:
                    continue
                cc = e["c"][p]; pc = e["c"][p - 1]
                if pc > 0:
                    if cc > pc:
                        up += 1
                    elif cc < pc:
                        dn += 1
                amt += e["amt"][p]
            mstats = {"up_count": up, "down_count": dn,
                      "total_amount": amt / 1e4 if amt > 1e6 else amt}
            isl = None
            if index_df is not None and not index_df.empty:
                idn = index_df["date"].astype(str).str.replace("-", "")
                iu = index_df[idn <= today]
                if len(iu) >= 5:
                    isl = iu.tail(lookback).reset_index(drop=True)

            # 情绪周期：全市场计算（无未来函数），记录序列；短线/打板按 gate 收缩放大
            emo = compute_emotion(idx, today)
            emotion_series.append({
                "date": today, "score": emo.score, "phase": emo.phase,
                "limit_up": emo.limit_up, "limit_down": emo.limit_down,
                "broken_rate": emo.broken_rate, "max_consecutive": emo.max_consecutive,
                "advance_rate": emo.advance_rate, "money_effect": emo.money_effect,
                "gate": emo.gate,
            })
            eff_top_n, eff_pos = st.top_n, st.position_pct
            if st.emotion_gated:
                if emo.gate <= 0:                       # 冰点 → 空仓
                    no_trade_days += 1
                    continue
                eff_pos = st.position_pct * min(emo.gate, 1.3)
                if emo.gate < 1.0:                      # 弱势减少持仓数
                    eff_top_n = max(1, round(st.top_n * emo.gate))

            picks = st.select(DayContext(today, slices, stock_info, mstats,
                                          isl, fast=idx))
            if not picks:
                no_trade_days += 1
                continue

            held = {h["ts_code"] for h in holdings}
            buyable = [p for p in picks if p.ts_code not in held][:eff_top_n]
            if not buyable:
                continue
            alloc = cash * eff_pos / len(buyable)
            next_open = st.entry_at == "next_open"
            nxt_date = trade_dates[di + 1]   # 已保证 di < len-1
            for pk in buyable:
                e = idx.get(pk.ts_code)
                if not e:
                    continue
                p = e["pos"].get(today)
                if p is None or p < 1:
                    continue
                _carr = e["c"]
                if next_open:
                    # 封死涨停按收盘买不进 → 真实 T+1 开盘进场；
                    # 仅当个股下一根 bar 恰为全局下一交易日(无停牌断档)才可净化进场
                    bp = p + 1
                    if e["pos"].get(nxt_date) != bp:
                        continue
                    entry = float(e["o"][bp])
                    if entry <= 0:
                        continue
                    # T+1 一字涨停同样买不进
                    if is_one_word_limit_up(entry, float(e["h"][bp]),
                                            float(e["l"][bp]), float(e["c"][bp]),
                                            float(_carr[p]), e["pct"]):
                        continue
                    buy_idx = di + 1
                    ref0 = float(_carr[p])           # T+1 前收 = T 收盘
                    anchor_p = bp
                else:
                    c = float(_carr[p])
                    if c <= 0:
                        continue
                    o, hi, lo = (float(e["o"][p]), float(e["h"][p]),
                                 float(e["l"][p]))
                    if is_one_word_limit_up(o, hi, lo, c, float(_carr[p - 1]),
                                            e["pct"]):
                        continue
                    entry = c
                    buy_idx = di
                    ref0 = c
                    anchor_p = p

                bpx = apply_slippage(entry, "buy", self.slippage_bps)
                sh = math.floor(alloc / (bpx * 100)) * 100
                if sh <= 0:
                    continue
                cost = buy_cost(sh, bpx, self.commission_rate)
                if cost > cash:
                    continue
                cash -= cost
                total_buy_notional += sh * entry
                fwd = [((float(_carr[anchor_p + k]) - entry) / entry
                        if anchor_p + k < e["n"] else None) for k in range(1, 6)]
                event_rows.append(fwd)
                holdings.append({
                    "ts_code": pk.ts_code, "name": pk.name,
                    "buy_date": nxt_date if next_open else today,
                    "buy_idx": buy_idx, "buy_px": bpx, "buy_close_raw": entry,
                    "ref_close": ref0, "shares": sh, "cost": cost,
                    "score": pk.score, "hold_days": 0,
                    "recent_closes": [float(x) for x in
                                      _carr[max(0, anchor_p - 119):anchor_p + 1]],
                })

        last = trade_dates[-1]
        for h in holdings:
            e, p = _at(h["ts_code"], last)
            px = float(e["c"][p]) if p is not None else h["ref_close"]
            _close(h, last, px, "backtest_end")

        res = self._M._calc_metrics(
            trades=trades, equity_curve=equity_curve, daily_returns=daily_returns,
            final_cash=cash, trade_dates=trade_dates, no_trade_days=no_trade_days,
            stuck_events=stuck_events, total_cost=total_cost,
            total_buy_notional=total_buy_notional, daily_ic=daily_ic,
            event_rows=event_rows,
        )
        res.realism_notes = [
            f"风格：{st.name}（目标持仓{st.target_hold_days}日，上限{st.max_hold_days}日）",
            "选股仅用≤T数据，T收盘买入(含滑点)，一字涨停买不进",
            "一字/封死涨跌停无法成交→持仓顺延，超上限强平",
            f"成本：佣金双边{self.commission_rate*1e4:.1f}‱(最低5元)+印花{self.stamp_tax_rate*1e4:.1f}‱(卖)+滑点{self.slippage_bps:.0f}bp",
            f"保守实盘预期 = 回测总收益×(1-{self.live_decay:.0%}) [经验衰减,非保证]",
            "幸存者偏差：需调用方提供退市股数据方可完全消除",
        ]
        if st.emotion_gated:
            res.realism_notes.insert(1, "情绪周期 gating：冰点空仓 / 退潮减半 / 高潮放大仓位")
        res.emotion_series = emotion_series
        return res
