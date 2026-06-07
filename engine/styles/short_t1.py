"""
短线 · T+1 隔夜风格

直接复用现有 T1V4Scorer（5维评分）选股 + SellEngineV2（4阶段）退出。
持仓周期 1 个交易日。这是系统原有主策略，归入"短线"风格。
"""

from __future__ import annotations

from typing import List

from engine.factors import factor_adjust, rps_map
from engine.styles.base import (
    DayContext,
    StyleExit,
    StylePick,
    TradingStyle,
    register_style,
)
from engine.t1_v4.scorer import T1V4Scorer
from engine.t1_v4.sell_engine_v2 import SellEngineV2


@register_style
class ShortT1Style(TradingStyle):
    key = "short_t1"
    name = "短线·T+1隔夜"
    desc = "5维评分(技术/资金/基本/板块/市场)选强势股，收盘买入，次日4阶段卖出。持仓1日。"
    verdict = "偏弱未充分验证"
    verdict_note = "短窗口薄样本~持平偏弱；T1V4评分器慢未做8年逐年。属追涨类，方向与已证伪一致，不推荐。"
    target_hold_days = 1
    top_n = 2
    position_pct = 0.6
    max_hold_days = 5   # 一字/停牌顺延上限
    min_lookback = 30
    emotion_gated = True   # 隔夜短线随情绪周期收缩/放大

    # 因子重排默认关闭（同 daban：未经按风格验证前不污染基线，保留开关）
    def __init__(self, scorer: T1V4Scorer = None, sell_engine: SellEngineV2 = None,
                 use_factors: bool = False, **overrides):
        super().__init__(**overrides)
        self.use_factors = use_factors
        self._scorer = scorer or T1V4Scorer(
            top_n=self.top_n,
            market_safe_threshold=overrides.get("market_safe_threshold", 8.0),
            min_total_score=overrides.get("min_total_score", 55.0),
        )
        self._sell = sell_engine or SellEngineV2(ambiguous_pessimistic=True)

    def select(self, day: DayContext) -> List[StylePick]:
        stock_pool, contexts = [], {}
        for ts_code, df in day.slices.items():
            info = day.stock_info.get(ts_code)
            if info is None or len(df) < 5:
                continue
            stock_pool.append({
                "ts_code": ts_code,
                "name": info.get("name", ""),
                "list_date": info.get("list_date"),
            })
            last = df.iloc[-1]
            contexts[ts_code] = {
                "turnover_rate": float(last.get("turnover_rate", 0)) or None,
                "is_suspended": False,
                "money_flow_df": None, "north_flow_df": None,
                "fina_df": None, "pe": None, "industry_pe_median": None,
                "sector_rank": None, "total_sectors": None,
                "sector_limit_up_count": 0,
            }
        ctx = {"index_df": day.index_slice, "market_stats": day.market_stats}
        # 取更多候选（重排前需冗余），再按因子重排取 top_n
        raw_n = max(self.top_n * 4, 12) if self.use_factors else self.top_n
        scores = self._scorer.rank_and_select(
            stock_pool=stock_pool, daily_data=day.slices,
            context=ctx, stock_contexts=contexts, top_n=raw_n,
        )
        if not self.use_factors:
            return [
                StylePick(ts_code=s.ts_code, name=s.stock_name,
                          score=round(s.total_score, 1),
                          reason=f"5维评分{s.total_score:.0f}")
                for s in scores[:self.top_n]
            ]
        rps = rps_map(day.slices, n=20)
        picks = []
        for s in scores:
            df = day.slices.get(s.ts_code)
            adj, det = factor_adjust(s.total_score, df, rps.get(s.ts_code))
            picks.append(StylePick(
                ts_code=s.ts_code, name=s.stock_name, score=adj,
                reason=(f"5维{s.total_score:.0f}×因子{det['factor_mult']}"
                        f"(RPS{det['rps']} 跳空{det['gap_penalty']} TOI{det['toi']})"),
                meta=det,
            ))
        picks.sort(key=lambda x: -x.score)
        return picks[:self.top_n]

    def should_exit(self, holding, bar, hold_days, prev_close) -> StyleExit:
        d = self._sell.decide(
            buy_price=holding["buy_px"],
            next_open=bar["open"], next_high=bar["high"],
            next_low=bar["low"], next_close=bar["close"],
            prev_close=prev_close,
        )
        if d.stuck:
            return StyleExit(sell=False, reason=d.sell_reason, stuck=True)
        return StyleExit(sell=True, price=d.sell_price, reason=d.sell_reason)
