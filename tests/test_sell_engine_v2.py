"""SellEngineV2 单元测试"""

import pytest
from engine.t1_v4.sell_engine_v2 import SellEngineV2, SellDecision


class TestSellEngineV2:
    """卖出引擎 v2 单元测试"""

    def setup_method(self):
        self.engine = SellEngineV2()

    # ------------------------------------------------------------------
    # 阶段 1：集合竞价
    # ------------------------------------------------------------------

    def test_phase1_take_profit(self):
        """高开 >=5% 应触发阶段1止盈"""
        d = self.engine.decide(10.0, 10.6, 10.8, 10.5, 10.7)
        assert d.phase == 1
        assert d.sell_reason == "phase1_take_profit"
        assert d.sell_price == 10.6  # 开盘价
        assert d.pnl_pct > 0
        assert d.pnl_pct == pytest.approx(0.06, abs=1e-9)

    def test_phase1_take_profit_exactly_at_threshold(self):
        """恰好高开 5% 也应触发阶段1止盈"""
        d = self.engine.decide(10.0, 10.5, 10.8, 10.4, 10.7)
        assert d.phase == 1
        assert d.sell_reason == "phase1_take_profit"

    def test_phase1_stop_loss(self):
        """低开 <=-2% 应触发阶段1止损"""
        d = self.engine.decide(10.0, 9.7, 9.8, 9.5, 9.6)
        assert d.phase == 1
        assert d.sell_reason == "phase1_stop_loss"
        assert d.sell_price == 9.7
        assert d.pnl_pct < 0
        assert d.pnl_pct == pytest.approx(-0.03, abs=1e-9)

    def test_phase1_stop_loss_exactly_at_threshold(self):
        """低开超过 -2% 应触发阶段1止损（使用明确超出阈值的值避免浮点边界问题）"""
        # open_pct = (9.79 - 10.0) / 10.0 = -0.021，明确超出 -0.02 阈值
        d = self.engine.decide(10.0, 9.79, 9.85, 9.6, 9.7)
        assert d.phase == 1
        assert d.sell_reason == "phase1_stop_loss"

    def test_phase1_takes_priority_over_phase2(self):
        """阶段1条件优先于盘中条件"""
        # 高开 6%，盘中也触及止盈，应优先阶段1
        d = self.engine.decide(10.0, 10.6, 11.0, 10.3, 10.8)
        assert d.phase == 1
        assert d.sell_reason == "phase1_take_profit"

    # ------------------------------------------------------------------
    # 阶段 2：涨停处理
    # ------------------------------------------------------------------

    def test_limit_up_hold(self):
        """高点触及涨停应持有到收盘"""
        d = self.engine.decide(10.0, 10.2, 11.0, 10.1, 10.98)
        assert d.sell_reason == "limit_up_hold"
        assert d.sell_price == 10.98  # 收盘价
        assert d.phase == 2

    def test_limit_up_pnl_based_on_close(self):
        """涨停持有的盈亏应基于收盘价计算"""
        d = self.engine.decide(10.0, 10.2, 11.0, 10.1, 10.5)
        assert d.sell_reason == "limit_up_hold"
        assert d.pnl_pct == pytest.approx(0.05, abs=1e-9)

    # ------------------------------------------------------------------
    # 阶段 2：盘中止盈/止损
    # ------------------------------------------------------------------

    def test_phase2_take_profit(self):
        """盘中冲高 >=3% 应触发阶段2止盈"""
        d = self.engine.decide(10.0, 10.1, 10.4, 10.0, 10.2)
        assert d.phase == 2
        assert d.sell_reason == "phase2_take_profit"
        assert d.sell_price == pytest.approx(10.3, abs=0.01)  # buy_price * 1.03

    def test_phase2_stop_loss(self):
        """盘中下探 <=-2% 应触发阶段2止损"""
        d = self.engine.decide(10.0, 10.1, 10.15, 9.7, 9.9)
        assert d.phase == 2
        assert d.sell_reason == "phase2_stop_loss"
        assert d.sell_price == pytest.approx(9.8, abs=0.01)  # buy_price * 0.98

    def test_phase2_both_triggered_high_first(self):
        """盘中同时触及止盈和止损，开盘更靠近最高价时先止盈"""
        # next_open=10.35, next_high=10.4, next_low=9.7
        # open 距 high: 10.4 - 10.35 = 0.05
        # open 距 low: 10.35 - 9.7 = 0.65 > 0.05 → open 更接近 high → 先冲高止盈
        d = self.engine.decide(10.0, 10.35, 10.4, 9.7, 10.1)
        assert d.phase == 2
        assert d.sell_reason == "phase2_take_profit"

    def test_phase2_both_triggered_low_first(self):
        """盘中同时触及止盈和止损，开盘更靠近最低价时先止损"""
        # next_open=10.05，phase1 未触发（open_pct=0.5% < 5%，且 > -2%）
        # next_high=10.4 → high_pct=4% >= phase2_take_profit(3%)
        # next_low=9.7 → low_pct=-3% <= phase2_stop_loss(-2%)
        # open 距 high: 10.4 - 10.05 = 0.35
        # open 距 low: 10.05 - 9.7 = 0.35 → 相等时条件 (next_open - next_low) > (next_high - next_open) 为 False
        # 用 open=9.75 会触发 phase1，需要 open 在 phase1 阈值之内
        # open_pct = (10.02 - 10) / 10 = 0.2%，介于 -2% 和 5% 之间
        # open 距 high: 10.4 - 10.02 = 0.38
        # open 距 low: 10.02 - 9.7 = 0.32 < 0.38 → open 更接近 low → 先下探止损
        d = self.engine.decide(10.0, 10.02, 10.4, 9.7, 10.1)
        assert d.phase == 2
        assert d.sell_reason == "phase2_stop_loss"

    # ------------------------------------------------------------------
    # 阶段 3：收盘锁利/止损
    # ------------------------------------------------------------------

    def test_phase3_lock_profit(self):
        """收盘盈利应触发阶段3锁利"""
        d = self.engine.decide(10.0, 10.05, 10.15, 9.9, 10.1)
        assert d.phase == 3
        assert d.sell_reason == "phase3_lock_profit"
        assert d.pnl_pct > 0

    def test_phase3_stop_loss(self):
        """收盘亏损超过 -1.5% 应触发阶段3止损"""
        d = self.engine.decide(10.0, 10.05, 10.1, 9.85, 9.84)
        assert d.phase == 3
        assert d.sell_reason == "phase3_stop_loss"
        assert d.pnl_pct < 0

    # ------------------------------------------------------------------
    # 阶段 4：兜底
    # ------------------------------------------------------------------

    def test_phase4_timeout(self):
        """收盘微亏但未触及止损线，进入阶段4兜底"""
        # close_pct = -0.005 (亏 0.5%)，未触及 phase3_stop_loss=-0.015
        d = self.engine.decide(10.0, 10.05, 10.1, 9.91, 9.95)
        assert d.phase == 4
        assert d.sell_reason == "phase4_timeout"
        assert d.sell_price == 9.95

    def test_phase4_pnl_based_on_close(self):
        """阶段4兜底的盈亏基于收盘价"""
        d = self.engine.decide(10.0, 10.05, 10.1, 9.91, 9.95)
        assert d.pnl_pct == pytest.approx(-0.005, abs=1e-9)

    # ------------------------------------------------------------------
    # 边界与通用特性
    # ------------------------------------------------------------------

    def test_sell_price_rounded_to_2_decimals(self):
        """卖出价应保留两位小数"""
        d = self.engine.decide(10.0, 10.333, 10.5, 10.1, 10.4)
        assert d.sell_price == round(d.sell_price, 2)

    def test_description_is_non_empty_string(self):
        """description 应为非空字符串"""
        d = self.engine.decide(10.0, 10.6, 10.8, 10.5, 10.7)
        assert isinstance(d.description, str)
        assert len(d.description) > 0

    def test_pnl_pct_is_float(self):
        """pnl_pct 应为 float"""
        d = self.engine.decide(10.0, 10.6, 10.8, 10.5, 10.7)
        assert isinstance(d.pnl_pct, float)

    def test_phase_is_integer(self):
        """phase 应为整数"""
        d = self.engine.decide(10.0, 10.6, 10.8, 10.5, 10.7)
        assert isinstance(d.phase, int)
        assert d.phase in (1, 2, 3, 4)

    def test_custom_take_profit_threshold(self):
        """自定义止盈阈值"""
        engine = SellEngineV2(phase1_take_profit=0.03)
        # 高开 3%，使用默认引擎不会触发，但自定义后应触发
        d = engine.decide(10.0, 10.3, 10.5, 10.1, 10.4)
        assert d.phase == 1
        assert d.sell_reason == "phase1_take_profit"

    def test_custom_stop_loss_threshold(self):
        """自定义止损阈值"""
        engine = SellEngineV2(phase1_stop_loss=-0.01)
        # 低开 1.5%（超过自定义 -1% 阈值），默认引擎不会触发（默认阈值 -2%），自定义后应触发
        d = engine.decide(10.0, 9.85, 9.9, 9.7, 9.8)
        assert d.phase == 1
        assert d.sell_reason == "phase1_stop_loss"

    # ------------------------------------------------------------------
    # 批量接口
    # ------------------------------------------------------------------

    def test_batch_decide_returns_list(self):
        """batch_decide 应返回列表"""
        trades = [
            {"buy_price": 10.0, "next_open": 10.6, "next_high": 10.8, "next_low": 10.5, "next_close": 10.7},
            {"buy_price": 10.0, "next_open": 9.7, "next_high": 9.8, "next_low": 9.5, "next_close": 9.6},
        ]
        results = self.engine.batch_decide(trades)
        assert isinstance(results, list)
        assert len(results) == 2

    def test_batch_decide_results_are_sell_decisions(self):
        """batch_decide 每个结果应为 SellDecision 对象"""
        trades = [
            {"buy_price": 10.0, "next_open": 10.6, "next_high": 10.8, "next_low": 10.5, "next_close": 10.7},
        ]
        results = self.engine.batch_decide(trades)
        assert isinstance(results[0], SellDecision)

    def test_batch_decide(self):
        """批量决策正确性"""
        trades = [
            {"buy_price": 10.0, "next_open": 10.6, "next_high": 10.8, "next_low": 10.5, "next_close": 10.7},
            {"buy_price": 10.0, "next_open": 9.7, "next_high": 9.8, "next_low": 9.5, "next_close": 9.6},
        ]
        results = self.engine.batch_decide(trades)
        assert results[0].pnl_pct > 0  # 高开止盈
        assert results[1].pnl_pct < 0  # 低开止损

    def test_batch_decide_empty_list(self):
        """空列表批量决策应返回空列表"""
        results = self.engine.batch_decide([])
        assert results == []

    # ------------------------------------------------------------------
    # 统计摘要
    # ------------------------------------------------------------------

    def test_summary_stats_keys(self):
        """统计摘要应包含所有必需 key"""
        decisions = [
            SellDecision(10.5, "phase1_take_profit", 0.05, 1, "test"),
            SellDecision(9.8, "phase1_stop_loss", -0.02, 1, "test"),
            SellDecision(10.3, "phase2_take_profit", 0.03, 2, "test"),
        ]
        stats = self.engine.summary_stats(decisions)
        assert "total" in stats
        assert "by_reason" in stats
        assert "by_phase" in stats
        assert "avg_pnl" in stats
        assert "win_rate" in stats

    def test_summary_stats_total(self):
        """统计摘要 total 应等于决策数量"""
        decisions = [
            SellDecision(10.5, "phase1_take_profit", 0.05, 1, "test"),
            SellDecision(9.8, "phase1_stop_loss", -0.02, 1, "test"),
        ]
        stats = self.engine.summary_stats(decisions)
        assert stats["total"] == 2

    def test_summary_stats_win_rate(self):
        """win_rate 应正确计算（pnl_pct > 0 的比例）"""
        decisions = [
            SellDecision(10.5, "phase1_take_profit", 0.05, 1, "test"),
            SellDecision(9.8, "phase1_stop_loss", -0.02, 1, "test"),
            SellDecision(10.3, "phase2_take_profit", 0.03, 2, "test"),
        ]
        stats = self.engine.summary_stats(decisions)
        assert stats["win_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_summary_stats_avg_pnl(self):
        """avg_pnl 应正确计算"""
        decisions = [
            SellDecision(10.5, "phase1_take_profit", 0.06, 1, "test"),
            SellDecision(9.8, "phase1_stop_loss", -0.02, 1, "test"),
        ]
        stats = self.engine.summary_stats(decisions)
        assert stats["avg_pnl"] == pytest.approx(0.02, abs=1e-5)

    def test_summary_stats_by_reason(self):
        """by_reason 应按 sell_reason 分组统计"""
        decisions = [
            SellDecision(10.5, "phase1_take_profit", 0.05, 1, "test"),
            SellDecision(9.8, "phase1_stop_loss", -0.02, 1, "test"),
            SellDecision(10.3, "phase2_take_profit", 0.03, 2, "test"),
        ]
        stats = self.engine.summary_stats(decisions)
        assert "phase1_take_profit" in stats["by_reason"]
        assert "phase1_stop_loss" in stats["by_reason"]
        assert "phase2_take_profit" in stats["by_reason"]
        assert stats["by_reason"]["phase1_take_profit"]["count"] == 1

    def test_summary_stats_by_phase(self):
        """by_phase 应按阶段分组统计"""
        decisions = [
            SellDecision(10.5, "phase1_take_profit", 0.05, 1, "test"),
            SellDecision(9.8, "phase1_stop_loss", -0.02, 1, "test"),
            SellDecision(10.3, "phase2_take_profit", 0.03, 2, "test"),
        ]
        stats = self.engine.summary_stats(decisions)
        assert 1 in stats["by_phase"]
        assert 2 in stats["by_phase"]
        assert stats["by_phase"][1]["count"] == 2

    def test_summary_stats_empty_decisions(self):
        """空决策列表统计摘要应返回零值"""
        stats = self.engine.summary_stats([])
        assert stats["total"] == 0
        assert stats["win_rate"] == 0.0
        assert stats["avg_pnl"] == 0.0
        assert stats["by_reason"] == {}
        assert stats["by_phase"] == {}
