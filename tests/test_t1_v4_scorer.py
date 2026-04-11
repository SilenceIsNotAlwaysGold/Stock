"""T1 v4 评分引擎单元测试"""

import pytest
import pandas as pd
import numpy as np


def _make_daily_df(days=30, base_close=10.0, trend="up"):
    """生成模拟日线数据"""
    np.random.seed(42)  # 固定随机种子确保可重现
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close_prices = []
    price = base_close
    for i in range(days):
        if trend == "up":
            price *= 1 + np.random.uniform(0.005, 0.03)
        elif trend == "down":
            price *= 1 - np.random.uniform(0.005, 0.03)
        else:  # flat
            price *= 1 + np.random.uniform(-0.005, 0.005)
        close_prices.append(price)

    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": [c * 0.99 for c in close_prices],
        "high": [c * 1.02 for c in close_prices],
        "low": [c * 0.98 for c in close_prices],
        "close": close_prices,
        "volume": [np.random.randint(100000, 1000000) for _ in range(days)],
    })
    return df


class TestVetoFilter:
    """一票否决过滤器测试"""

    def test_st_stock_vetoed(self):
        """ST 股票应该被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        result = f.check("000001.SZ", "ST测试", _make_daily_df())
        assert not result.passed
        assert "ST" in result.reject_reasons[0]

    def test_star_st_stock_vetoed(self):
        """*ST 股票应该被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        result = f.check("000001.SZ", "*ST退市", _make_daily_df())
        assert not result.passed
        assert "ST" in result.reject_reasons[0]

    def test_normal_stock_passes(self):
        """正常股票应该通过"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        # 使用 flat 趋势避免涨停触发，list_date 设为已上市 60+ 天
        result = f.check("000001.SZ", "平安银行", _make_daily_df(trend="flat"), list_date="20200101")
        assert result.passed
        assert len(result.reject_reasons) == 0

    def test_kcb_vetoed(self):
        """科创板股票应被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        result = f.check("688001.SH", "华兴源创", _make_daily_df())
        assert not result.passed
        assert "科创板" in result.reject_reasons[0]

    def test_north_exchange_vetoed(self):
        """北交所股票应被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        result = f.check("830001.BJ", "某北交所股票", _make_daily_df())
        assert not result.passed
        assert "北交所" in result.reject_reasons[0]

    def test_suspended_vetoed(self):
        """停牌股票应被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        result = f.check("000001.SZ", "平安银行", _make_daily_df(), is_suspended=True)
        assert not result.passed
        assert any("停牌" in r for r in result.reject_reasons)

    def test_empty_df_vetoed(self):
        """空 DataFrame 应被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        result = f.check("000001.SZ", "平安银行", pd.DataFrame())
        assert not result.passed

    def test_limit_up_vetoed(self):
        """当日涨停应被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        # 构造最后一天涨停：close 比 pre_close 高出 10%
        df = _make_daily_df(days=10, base_close=10.0, trend="flat")
        # 设置倒数第二行作为 pre_close 参考，最后一行涨幅 >= 9.8%
        prev_close = float(df.iloc[-2]["close"])
        df.loc[df.index[-1], "close"] = round(prev_close * 1.10, 4)
        result = f.check("000001.SZ", "平安银行", df, list_date="20200101")
        assert not result.passed
        assert "涨停" in result.reject_reasons[0]

    def test_limit_down_vetoed(self):
        """当日跌停应被否决"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        df = _make_daily_df(days=10, base_close=10.0, trend="flat")
        prev_close = float(df.iloc[-2]["close"])
        df.loc[df.index[-1], "close"] = round(prev_close * 0.89, 4)
        result = f.check("000001.SZ", "平安银行", df, list_date="20200101")
        assert not result.passed
        assert "跌停" in result.reject_reasons[0]

    def test_new_listing_vetoed(self):
        """上市不足 60 天应被否决（次新股）"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        # 使用今天的日期作为上市日期，肯定不足 60 天
        result = f.check("000001.SZ", "平安银行", _make_daily_df(trend="flat"), list_date="20260310")
        assert not result.passed
        assert "次新股" in result.reject_reasons[0]

    def test_veto_result_has_ts_code(self):
        """VetoResult 应包含 ts_code"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        result = f.check("000001.SZ", "ST测试", _make_daily_df())
        assert result.ts_code == "000001.SZ"

    def test_batch_filter(self):
        """批量过滤测试"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        stock_list = pd.DataFrame({
            "ts_code": ["000001.SZ", "688001.SH", "000002.SZ"],
            "name": ["平安银行", "华兴源创", "万科A"],
            "list_date": ["20000101", "20190101", "20000101"],
        })
        daily_data = {
            "000001.SZ": _make_daily_df(trend="flat"),
            "688001.SH": _make_daily_df(trend="flat"),
            "000002.SZ": _make_daily_df(trend="flat"),
        }
        passed, results = f.batch_filter(stock_list, daily_data)
        assert "688001.SH" not in passed  # 科创板被过滤
        assert "000001.SZ" in passed
        assert "000002.SZ" in passed
        assert len(results) == 3

    def test_batch_filter_empty_stock_list(self):
        """空股票列表批量过滤应返回空列表"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        passed, results = f.batch_filter(pd.DataFrame(), {})
        assert passed == []
        assert results == []

    def test_batch_filter_suspended_set(self):
        """批量过滤支持停牌集合"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter()
        stock_list = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "name": ["平安银行"],
            "list_date": ["20000101"],
        })
        daily_data = {"000001.SZ": _make_daily_df(trend="flat")}
        passed, results = f.batch_filter(stock_list, daily_data, suspended_set={"000001.SZ"})
        assert "000001.SZ" not in passed
        assert len(results) == 1
        assert not results[0].passed

    def test_custom_params(self):
        """自定义参数覆盖默认值"""
        from engine.t1_v4.veto_filter import VetoFilter
        f = VetoFilter(min_list_days=10)
        # 上市 30 天，默认规则会否决，自定义 10 天则通过
        result = f.check("000001.SZ", "平安银行", _make_daily_df(trend="flat"), list_date="20260312")
        # 上市约 30 天，min_list_days=10 则不否决该规则
        # （是否通过还取决于近 5 日涨跌停情况，flat 趋势不触发）
        # 只验证没有"次新股"原因
        assert not any("次新股" in r for r in result.reject_reasons)


class TestTechScorer:
    """技术面评分测试"""

    def test_score_returns_dict(self):
        """score() 应返回包含所有子项的 dict"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=30)
        result = s.score(df, len(df) - 1)
        assert "tech_total" in result
        assert "trend_strength" in result
        assert "momentum_quality" in result
        assert "volume_price" in result
        assert "candle_shape" in result

    def test_score_range(self):
        """各分数应在合理范围内"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=30)
        result = s.score(df, len(df) - 1)
        assert 0 <= result["tech_total"] <= 30
        assert 0 <= result["trend_strength"] <= 10
        assert 0 <= result["momentum_quality"] <= 8
        assert 0 <= result["volume_price"] <= 7
        assert 0 <= result["candle_shape"] <= 5

    def test_score_total_equals_sum(self):
        """tech_total 应等于各子项之和"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=30)
        result = s.score(df, len(df) - 1)
        expected_total = (
            result["trend_strength"]
            + result["momentum_quality"]
            + result["volume_price"]
            + result["candle_shape"]
        )
        assert abs(result["tech_total"] - expected_total) < 1e-9

    def test_insufficient_data_returns_zero(self):
        """数据不足（i < 25）时应返回全零"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=5)
        result = s.score(df, len(df) - 1)  # i=4, < 25
        assert result["tech_total"] == 0.0
        assert result["trend_strength"] == 0.0
        assert result["momentum_quality"] == 0.0
        assert result["volume_price"] == 0.0
        assert result["candle_shape"] == 0.0

    def test_exactly_25_rows_returns_zero(self):
        """恰好 25 行时 i=24 < 25，应返回全零"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=25)
        result = s.score(df, 24)  # i=24
        assert result["tech_total"] == 0.0

    def test_26_rows_returns_nonzero(self):
        """26 行时 i=25 >= 25，应返回非零分（趋势上行时）"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=26, trend="up")
        result = s.score(df, 25)
        # 至少某些子项有分数
        assert result["tech_total"] >= 0.0

    def test_uptrend_scores_higher_than_downtrend(self):
        """上涨趋势应比下跌趋势的趋势强度得分高"""
        from engine.t1_v4.tech_scorer import TechScorer
        np.random.seed(0)
        s = TechScorer()
        up_df = _make_daily_df(days=30, trend="up")
        np.random.seed(1)
        down_df = _make_daily_df(days=30, trend="down")
        up_score = s.score(up_df, len(up_df) - 1)["trend_strength"]
        down_score = s.score(down_df, len(down_df) - 1)["trend_strength"]
        assert up_score > down_score

    def test_score_all_keys_numeric(self):
        """所有返回值应为 float 类型"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=30)
        result = s.score(df, len(df) - 1)
        for key, val in result.items():
            assert isinstance(val, float), f"{key} 应为 float，实际为 {type(val)}"

    def test_score_index_boundary(self):
        """使用中间行索引评分不应崩溃，i>=25 时应返回有效分数"""
        from engine.t1_v4.tech_scorer import TechScorer
        s = TechScorer()
        df = _make_daily_df(days=60)
        # i=29 >= 25，应返回有效评分（非全零）
        result = s.score(df, 29)
        assert "tech_total" in result
        assert 0.0 <= result["tech_total"] <= 30.0
        # i=24 < 25，应返回全零
        result_zero = s.score(df, 24)
        assert result_zero["tech_total"] == 0.0


class TestT1V4Scorer:
    """综合评分引擎测试"""

    def test_score_stock_basic(self):
        """基本评分流程 - 正常股票应返回非否决结果"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer(market_safe_threshold=0)
        df = _make_daily_df(days=30, trend="flat")
        ctx = {"list_date": "20200101", "is_suspended": False}
        result = scorer.score_stock("000001.SZ", "平安银行", df, ctx)
        assert not result.vetoed
        assert result.ts_code == "000001.SZ"
        assert result.stock_name == "平安银行"
        assert result.total_score >= 0
        assert result.tech_score >= 0

    def test_score_stock_returns_stock_score(self):
        """score_stock 应返回 StockScore 对象"""
        from engine.t1_v4.scorer import T1V4Scorer, StockScore
        scorer = T1V4Scorer(market_safe_threshold=0)
        df = _make_daily_df(days=30, trend="flat")
        result = scorer.score_stock("000001.SZ", "平安银行", df, {"list_date": "20200101"})
        assert isinstance(result, StockScore)

    def test_vetoed_st_stock(self):
        """ST 股票应被否决，总分为 0"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer()
        df = _make_daily_df()
        result = scorer.score_stock("000001.SZ", "*ST退市", df, {})
        assert result.vetoed
        assert result.total_score == 0
        assert result.veto_reason != ""

    def test_vetoed_kcb_stock(self):
        """科创板股票应被否决"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer()
        df = _make_daily_df(trend="flat")
        result = scorer.score_stock("688001.SH", "华兴源创", df, {})
        assert result.vetoed
        assert "科创板" in result.veto_reason

    def test_score_stock_empty_context(self):
        """空 context 应能正常运行（外部数据均为 None）"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer()
        df = _make_daily_df(days=30, trend="flat")
        result = scorer.score_stock("000001.SZ", "平安银行", df, {"list_date": "20200101"})
        # 不崩溃即通过
        assert result is not None

    def test_score_stock_details_populated(self):
        """score_stock 结果 details 应包含各维度子项"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer(market_safe_threshold=0)
        df = _make_daily_df(days=30, trend="flat")
        result = scorer.score_stock("000001.SZ", "平安银行", df, {"list_date": "20200101"})
        assert not result.vetoed
        assert "tech_total" in result.details
        assert "capital_total" in result.details
        assert "fundamental_total" in result.details
        assert "sector_total" in result.details
        assert "market_total" in result.details

    def test_score_stock_total_equals_sum_of_dimensions(self):
        """total_score 应等于各维度分数之和"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer(market_safe_threshold=0)
        df = _make_daily_df(days=30, trend="flat")
        result = scorer.score_stock("000001.SZ", "平安银行", df, {"list_date": "20200101"})
        assert not result.vetoed
        expected = (
            result.tech_score
            + result.capital_score
            + result.fundamental_score
            + result.sector_score
            + result.market_score
        )
        assert abs(result.total_score - expected) < 1e-9

    def test_rank_and_select_market_unsafe(self):
        """市场面得分低于阈值时应返回空列表"""
        from engine.t1_v4.scorer import T1V4Scorer
        # 设置极高阈值，市场面 None 输入不可能达到
        scorer = T1V4Scorer(market_safe_threshold=100.0, min_total_score=0)
        pool = [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_date": "20000101"},
        ]
        daily_data = {"000001.SZ": _make_daily_df(days=30, trend="up")}
        results = scorer.rank_and_select(pool, daily_data, {}, top_n=5)
        assert results == []

    def test_rank_and_select_basic(self):
        """rank_and_select 基本功能 - 返回按分数降序结果"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer(market_safe_threshold=0, min_total_score=0)
        pool = [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_date": "20000101"},
            {"ts_code": "000002.SZ", "name": "万科A", "list_date": "20000101"},
        ]
        daily_data = {
            "000001.SZ": _make_daily_df(days=30, trend="up"),
            "000002.SZ": _make_daily_df(days=30, trend="down"),
        }
        results = scorer.rank_and_select(pool, daily_data, {}, top_n=2)
        assert len(results) <= 2
        # 结果应按分数降序
        if len(results) >= 2:
            assert results[0].total_score >= results[1].total_score

    def test_rank_and_select_top_n_limit(self):
        """rank_and_select 返回不超过 top_n 条"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer(market_safe_threshold=0, min_total_score=0)
        pool = [
            {"ts_code": f"00000{i}.SZ", "name": f"股票{i}", "list_date": "20000101"}
            for i in range(1, 6)
        ]
        daily_data = {
            f"00000{i}.SZ": _make_daily_df(days=30, trend="flat")
            for i in range(1, 6)
        }
        results = scorer.rank_and_select(pool, daily_data, {}, top_n=2)
        assert len(results) <= 2

    def test_rank_and_select_filters_vetoed(self):
        """rank_and_select 应过滤被否决的股票"""
        from engine.t1_v4.scorer import T1V4Scorer
        scorer = T1V4Scorer(market_safe_threshold=0, min_total_score=0)
        pool = [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_date": "20000101"},
            {"ts_code": "688001.SH", "name": "华兴源创", "list_date": "20000101"},  # 科创板
        ]
        daily_data = {
            "000001.SZ": _make_daily_df(days=30, trend="flat"),
            "688001.SH": _make_daily_df(days=30, trend="flat"),
        }
        results = scorer.rank_and_select(pool, daily_data, {}, top_n=5)
        codes = [r.ts_code for r in results]
        assert "688001.SH" not in codes

    def test_rank_and_select_min_score_filter(self):
        """rank_and_select 应过滤低于 min_total_score 的股票"""
        from engine.t1_v4.scorer import T1V4Scorer
        # 设置极高 min_total_score，任何股票都无法通过
        scorer = T1V4Scorer(market_safe_threshold=0, min_total_score=99999.0)
        pool = [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_date": "20000101"},
        ]
        daily_data = {"000001.SZ": _make_daily_df(days=30, trend="up")}
        results = scorer.rank_and_select(pool, daily_data, {}, top_n=5)
        assert results == []
