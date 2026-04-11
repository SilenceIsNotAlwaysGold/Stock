"""
T1 v4 多维度评分引擎

聚合 5 个维度的评分，排序选 Top-N。
这是 v4 策略的核心模块。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from engine.t1_v4.tech_scorer import TechScorer
from engine.t1_v4.capital_scorer import CapitalScorer
from engine.t1_v4.fundamental_scorer import FundamentalScorer
from engine.t1_v4.sector_scorer import SectorScorer
from engine.t1_v4.market_scorer import MarketScorer
from engine.t1_v4.veto_filter import VetoFilter


@dataclass
class StockScore:
    """单只股票的综合评分"""

    ts_code: str
    stock_name: str = ""
    total_score: float = 0.0        # 0-100
    tech_score: float = 0.0         # 0-30
    capital_score: float = 0.0      # 0-25
    fundamental_score: float = 0.0  # 0-15
    sector_score: float = 0.0       # 0-15
    market_score: float = 0.0       # 0-15
    vetoed: bool = False
    veto_reason: str = ""
    details: dict = field(default_factory=dict)  # 各维度子项明细


class T1V4Scorer:
    """
    多维度评分引擎

    使用方式：
        scorer = T1V4Scorer()
        # 单只股票评分
        score = scorer.score_stock(ts_code, stock_name, daily_df, context)
        # 全市场排序选股
        candidates = scorer.rank_and_select(stock_pool, daily_data, context, top_n=5)
    """

    DEFAULT_CONFIG = {
        "top_n": 5,                    # 每日最多选 N 只
        "market_safe_threshold": 8.0,  # 市场面安全阈值（15分中的8分）
        "min_total_score": 50.0,       # 最低总分阈值
    }

    def __init__(self, **config_overrides):
        self.config = {**self.DEFAULT_CONFIG, **config_overrides}
        self.tech_scorer = TechScorer()
        self.capital_scorer = CapitalScorer()
        self.fundamental_scorer = FundamentalScorer()
        self.sector_scorer = SectorScorer()
        self.market_scorer = MarketScorer()
        self.veto_filter = VetoFilter()

    def score_stock(
        self,
        ts_code: str,
        stock_name: str,
        daily_df: pd.DataFrame,
        context: dict,
    ) -> StockScore:
        """
        计算单只股票的综合评分

        Args:
            ts_code: 股票代码
            stock_name: 股票名称
            daily_df: 日线 OHLCV 数据（至少30天）
            context: 外部数据上下文，包含：
                - money_flow_df: Optional[pd.DataFrame] 资金流数据
                - turnover_rate: Optional[float] 换手率
                - north_flow_df: Optional[pd.DataFrame] 北向资金
                - fina_df: Optional[pd.DataFrame] 财务指标
                - pe: Optional[float] 当前 PE
                - industry_pe_median: Optional[float] 行业 PE 中位数
                - sector_rank: Optional[int] 板块排名
                - total_sectors: Optional[int] 板块总数
                - sector_limit_up_count: int 板块涨停数
                - sector_consecutive_strong_days: int 板块连续强势天数
                - index_df: Optional[pd.DataFrame] 指数日线
                - market_stats: Optional[dict] 市场统计
                - list_date: Optional[str] 上市日期
                - is_suspended: bool 是否停牌

        Returns:
            StockScore
        """
        # 1. 一票否决检查
        list_date = context.get("list_date")
        is_suspended = context.get("is_suspended", False)

        veto_result = self.veto_filter.check(
            ts_code=ts_code,
            stock_name=stock_name,
            daily_df=daily_df if daily_df is not None else pd.DataFrame(),
            list_date=list_date,
            is_suspended=is_suspended,
        )

        if not veto_result.passed:
            return StockScore(
                ts_code=ts_code,
                stock_name=stock_name,
                vetoed=True,
                veto_reason="; ".join(veto_result.reject_reasons),
            )

        # 2. 调用 5 个评分器
        # 技术面：用 daily_df 最后一行
        i = len(daily_df) - 1 if daily_df is not None and not daily_df.empty else -1
        if i >= 0:
            tech_result = self.tech_scorer.score(daily_df, i)
        else:
            tech_result = self.tech_scorer._empty_scores()

        # 资金面
        capital_result = self.capital_scorer.score(
            money_flow_df=context.get("money_flow_df"),
            turnover_rate=context.get("turnover_rate"),
            north_flow_df=context.get("north_flow_df"),
        )

        # 基本面
        fundamental_result = self.fundamental_scorer.score(
            fina_df=context.get("fina_df"),
            pe=context.get("pe"),
            industry_pe_median=context.get("industry_pe_median"),
        )

        # 板块面
        sector_result = self.sector_scorer.score(
            sector_rank=context.get("sector_rank"),
            total_sectors=context.get("total_sectors"),
            sector_limit_up_count=context.get("sector_limit_up_count", 0),
            sector_consecutive_strong_days=context.get("sector_consecutive_strong_days", 0),
        )

        # 市场面
        market_result = self.market_scorer.score(
            index_df=context.get("index_df"),
            market_stats=context.get("market_stats"),
        )

        # 3. 汇总
        tech_score = float(tech_result.get("tech_total", 0.0))
        capital_score = float(capital_result.get("capital_total", 0.0))
        fundamental_score = float(fundamental_result.get("fundamental_total", 0.0))
        sector_score = float(sector_result.get("sector_total", 0.0))
        market_score = float(market_result.get("market_total", 0.0))

        total_score = tech_score + capital_score + fundamental_score + sector_score + market_score

        details = {}
        details.update(tech_result)
        details.update(capital_result)
        details.update(fundamental_result)
        details.update(sector_result)
        details.update(market_result)

        return StockScore(
            ts_code=ts_code,
            stock_name=stock_name,
            total_score=total_score,
            tech_score=tech_score,
            capital_score=capital_score,
            fundamental_score=fundamental_score,
            sector_score=sector_score,
            market_score=market_score,
            vetoed=False,
            veto_reason="",
            details=details,
        )

    def rank_and_select(
        self,
        stock_pool: List[dict],                      # [{ts_code, name, list_date, ...}]
        daily_data: Dict[str, pd.DataFrame],          # ts_code -> daily_df
        context: dict,                                # 全局 context（market_stats, index_df 等）
        stock_contexts: Optional[Dict[str, dict]] = None,  # ts_code -> 个股 context
        top_n: Optional[int] = None,
    ) -> List[StockScore]:
        """
        全市场评分排序，返回 Top-N 候选

        Args:
            stock_pool: 股票列表
            daily_data: 每只股票的日线数据
            context: 全局上下文（指数、市场统计等所有股票共享的数据）
            stock_contexts: 每只股票的个股上下文（资金流、财务等）
            top_n: 选几只，默认用 config

        Returns:
            按总分降序排列的 Top-N StockScore 列表
        """
        if top_n is None:
            top_n = self.config["top_n"]

        market_safe_threshold = self.config["market_safe_threshold"]
        min_total_score = self.config["min_total_score"]

        # 1. 市场面评分（所有股票共享，只计算一次）
        market_result = self.market_scorer.score(
            index_df=context.get("index_df"),
            market_stats=context.get("market_stats"),
        )
        market_score_val = float(market_result.get("market_total", 0.0))

        if market_score_val < market_safe_threshold:
            # 大盘环境不安全，不交易
            return []

        # 2. 对每只股票评分
        all_scores: List[StockScore] = []

        for stock_info in stock_pool:
            ts_code = str(stock_info.get("ts_code", ""))
            stock_name = str(stock_info.get("name", ""))

            daily_df = daily_data.get(ts_code)
            if daily_df is None:
                daily_df = pd.DataFrame()

            # 合并全局 context 和个股 context
            stock_ctx = dict(context)
            if stock_contexts and ts_code in stock_contexts:
                stock_ctx.update(stock_contexts[ts_code])

            # 补充 stock_info 中的字段（如 list_date）
            if "list_date" in stock_info and "list_date" not in stock_ctx:
                stock_ctx["list_date"] = stock_info["list_date"]

            stock_score = self.score_stock(
                ts_code=ts_code,
                stock_name=stock_name,
                daily_df=daily_df,
                context=stock_ctx,
            )

            all_scores.append(stock_score)

        # 3. 过滤被否决的
        valid_scores = [s for s in all_scores if not s.vetoed]

        # 4. 过滤低于 min_total_score 的
        valid_scores = [s for s in valid_scores if s.total_score >= min_total_score]

        # 5. 按 total_score 降序排序
        valid_scores.sort(key=lambda s: s.total_score, reverse=True)

        # 6. 取 top_n
        return valid_scores[:top_n]

    def _empty_scores(self) -> dict:
        """返回空的子项明细"""
        return {
            # 技术面
            "tech_total": 0.0,
            "trend_strength": 0.0,
            "momentum_quality": 0.0,
            "volume_price": 0.0,
            "candle_shape": 0.0,
            # 资金面
            "capital_total": 0.0,
            "main_inflow": 0.0,
            "turnover_score": 0.0,
            "continuous_inflow": 0.0,
            "north_fund": 0.0,
            # 基本面
            "fundamental_total": 0.0,
            "roe_score": 0.0,
            "profit_growth": 0.0,
            "pe_reasonable": 0.0,
            # 板块面
            "sector_total": 0.0,
            "rank_score": 0.0,
            "limit_up_score": 0.0,
            "consecutive_strong": 0.0,
            # 市场面
            "market_total": 0.0,
            "trend_score": 0.0,
            "sentiment_score": 0.0,
            "activity_score": 0.0,
        }
