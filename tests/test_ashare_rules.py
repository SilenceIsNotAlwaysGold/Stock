"""
A 股交易规则引擎单元测试

覆盖：
- AShareFeeCalculator  费用计算
- ASharePriceValidator 涨跌停校验
- AShareCalendar       交易时间
- AShareLotValidator   手数校验
"""

from datetime import date, datetime, time

import pytest

from engine.ashare_rules import (
    AShareCalendar,
    AShareFeeCalculator,
    AShareLotValidator,
    ASharePriceValidator,
    StockType,
)


# ---------------------------------------------------------------------------
# AShareFeeCalculator
# ---------------------------------------------------------------------------


class TestAShareFeeCalculator:
    def setup_method(self):
        self.calc = AShareFeeCalculator(commission_rate=0.0003)

    def test_sell_shanghai_100k(self):
        """沪市卖出10万：印花税100元，过户费2元，佣金30元，合计132元"""
        fee = self.calc.calc_sell_fee("600000.SH", 100_000.0)
        assert fee.stamp_duty == pytest.approx(100.0, abs=0.01)
        assert fee.transfer_fee == pytest.approx(2.0, abs=0.01)
        assert fee.commission == pytest.approx(30.0, abs=0.01)
        assert fee.total == pytest.approx(132.0, abs=0.01)

    def test_buy_shanghai_no_stamp_duty(self):
        """买入不收印花税"""
        fee = self.calc.calc_buy_fee("600000.SH", 100_000.0)
        assert fee.stamp_duty == 0.0
        assert fee.transfer_fee == pytest.approx(2.0, abs=0.01)

    def test_sell_shenzhen_no_transfer_fee(self):
        """深市卖出无过户费"""
        fee = self.calc.calc_sell_fee("000001.SZ", 100_000.0)
        assert fee.transfer_fee == 0.0
        assert fee.stamp_duty == pytest.approx(100.0, abs=0.01)

    def test_buy_shenzhen_no_transfer_fee(self):
        """深市买入无过户费"""
        fee = self.calc.calc_buy_fee("000001.SZ", 50_000.0)
        assert fee.transfer_fee == 0.0
        assert fee.stamp_duty == 0.0

    def test_min_commission(self):
        """小额交易佣金保底5元"""
        fee = self.calc.calc_buy_fee("000001.SZ", 1000.0)  # 1000*0.03% = 0.3 < 5
        assert fee.commission == 5.0

    def test_normal_commission_above_min(self):
        """正常佣金超过最低限"""
        fee = self.calc.calc_buy_fee("000001.SZ", 200_000.0)  # 200000*0.03% = 60 > 5
        assert fee.commission == pytest.approx(60.0, abs=0.01)


# ---------------------------------------------------------------------------
# ASharePriceValidator
# ---------------------------------------------------------------------------


class TestASharePriceValidator:
    def test_st_stock_limit_pct(self):
        """ST股涨跌停为5%"""
        st = ASharePriceValidator.get_stock_type("000001.SZ", "*ST示例")
        assert ASharePriceValidator.get_limit_pct(st) == 0.05

    def test_star_market_limit_pct(self):
        """科创板涨跌停为20%"""
        star = ASharePriceValidator.get_stock_type("688001.SH", "某科创")
        assert ASharePriceValidator.get_limit_pct(star) == 0.20

    def test_chinext_reg_limit_pct(self):
        """创业板注册制（2020-08-24后上市）涨跌停为20%"""
        stock_type = ASharePriceValidator.get_stock_type(
            "300999.SZ", "创业板新股", list_date=date(2021, 1, 1)
        )
        assert ASharePriceValidator.get_limit_pct(stock_type) == 0.20

    def test_normal_stock_limit_pct(self):
        """主板普通股涨跌停为10%"""
        stock_type = ASharePriceValidator.get_stock_type("600000.SH", "浦发银行")
        assert ASharePriceValidator.get_limit_pct(stock_type) == 0.10

    def test_calc_limit_prices(self):
        """计算涨跌停价精确到分"""
        limit_up, limit_down = ASharePriceValidator.calc_limit_prices(10.0, StockType.NORMAL)
        assert limit_up == pytest.approx(11.0, abs=0.001)
        assert limit_down == pytest.approx(9.0, abs=0.001)

    def test_buy_price_over_limit_rejected(self):
        """超过涨停价的买入被拒绝"""
        ok, msg = ASharePriceValidator.validate_buy_price(11.5, 11.0)
        assert not ok
        assert "涨停价" in msg

    def test_sell_price_under_limit_rejected(self):
        """低于跌停价的卖出被拒绝"""
        ok, msg = ASharePriceValidator.validate_sell_price(8.5, 9.0)
        assert not ok
        assert "跌停价" in msg

    def test_valid_prices_pass(self):
        """正常价格通过校验"""
        ok, _ = ASharePriceValidator.validate_buy_price(10.5, 11.0)
        assert ok
        ok, _ = ASharePriceValidator.validate_sell_price(9.5, 9.0)
        assert ok


# ---------------------------------------------------------------------------
# AShareCalendar
# ---------------------------------------------------------------------------


class TestAShareCalendar:
    def test_weekday_trading_time(self):
        """工作日 9:30 是交易时间"""
        dt = datetime(2026, 4, 7, 9, 30)  # 2026-04-07 是周二
        assert AShareCalendar.is_trading_time(dt) is True

    def test_noon_not_trading(self):
        """工作日 12:00 不是交易时间"""
        dt = datetime(2026, 4, 7, 12, 0)
        assert AShareCalendar.is_trading_time(dt) is False

    def test_weekend_not_trading(self):
        """周末不是交易日"""
        assert AShareCalendar.is_trading_day(date(2026, 4, 4)) is False  # 周六

    def test_holiday_not_trading(self):
        """节假日不是交易日"""
        assert AShareCalendar.is_trading_day(date(2026, 1, 1)) is False

    def test_afternoon_trading_time(self):
        """工作日 14:00 是交易时间"""
        dt = datetime(2026, 4, 7, 14, 0)
        assert AShareCalendar.is_trading_time(dt) is True

    def test_after_close_not_trading(self):
        """15:01 收盘后不是交易时间"""
        dt = datetime(2026, 4, 7, 15, 1)
        assert AShareCalendar.is_trading_time(dt) is False


# ---------------------------------------------------------------------------
# AShareLotValidator
# ---------------------------------------------------------------------------


class TestAShareLotValidator:
    def test_buy_150_rejected(self):
        """买入150股（非100整数倍）被拒绝"""
        ok, msg = AShareLotValidator.validate_buy_quantity(150)
        assert not ok
        assert "100" in msg

    def test_buy_200_ok(self):
        """买入200股通过"""
        ok, _ = AShareLotValidator.validate_buy_quantity(200)
        assert ok

    def test_sell_any_quantity_ok(self):
        """卖出任意数量（只要不超过可卖量）"""
        ok, _ = AShareLotValidator.validate_sell_quantity(50, 100)
        assert ok

    def test_sell_t1_lock_rejected(self):
        """卖出数量超过可卖量（T+1锁仓）被拒绝"""
        ok, msg = AShareLotValidator.validate_sell_quantity(200, 100)
        assert not ok
        assert "T+1" in msg

    def test_buy_zero_rejected(self):
        """买入0股被拒绝"""
        ok, _ = AShareLotValidator.validate_buy_quantity(0)
        assert not ok
