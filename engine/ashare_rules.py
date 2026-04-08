"""
A 股交易规则引擎

包含：
- AShareFeeCalculator  - 费用计算（佣金 + 印花税 + 过户费）
- ASharePriceValidator - 涨跌停价格校验
- AShareCalendar       - 交易时间和节假日
- AShareLotValidator   - 手数校验（100股/手）
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# 费用计算
# ---------------------------------------------------------------------------


@dataclass
class FeeDetail:
    """A 股交易费用明细"""

    commission: float       # 佣金（买卖均有，最低5元）
    stamp_duty: float       # 印花税（仅卖出 0.1%）
    transfer_fee: float     # 过户费（仅沪市 0.002%）
    total: float            # 合计

    def __post_init__(self):
        self.total = round(self.commission + self.stamp_duty + self.transfer_fee, 4)


class AShareFeeCalculator:
    """
    A 股完整费用计算器

    费率说明：
    - 佣金：买卖均收，默认万三(0.03%)，最低5元
    - 印花税：仅卖出收取，固定 0.1%
    - 过户费：沪市(*.SH)买卖均收，0.002%；深市免收
    """

    MIN_COMMISSION = 5.0        # 最低佣金 5 元
    STAMP_DUTY_RATE = 0.001     # 印花税 0.1%（仅卖出）
    TRANSFER_FEE_RATE = 0.00002 # 过户费 0.002%（仅沪市）

    def __init__(self, commission_rate: float = 0.0003):
        self.commission_rate = commission_rate

    def _is_shanghai(self, ts_code: str) -> bool:
        return ts_code.upper().endswith(".SH")

    def calc_buy_fee(self, ts_code: str, amount: float) -> FeeDetail:
        """计算买入费用"""
        commission = max(round(amount * self.commission_rate, 4), self.MIN_COMMISSION)
        transfer_fee = round(amount * self.TRANSFER_FEE_RATE, 4) if self._is_shanghai(ts_code) else 0.0
        return FeeDetail(
            commission=commission,
            stamp_duty=0.0,
            transfer_fee=transfer_fee,
            total=0.0,  # __post_init__ 会重新计算
        )

    def calc_sell_fee(self, ts_code: str, amount: float) -> FeeDetail:
        """计算卖出费用"""
        commission = max(round(amount * self.commission_rate, 4), self.MIN_COMMISSION)
        stamp_duty = round(amount * self.STAMP_DUTY_RATE, 4)
        transfer_fee = round(amount * self.TRANSFER_FEE_RATE, 4) if self._is_shanghai(ts_code) else 0.0
        return FeeDetail(
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            total=0.0,
        )


# ---------------------------------------------------------------------------
# 涨跌停价格校验
# ---------------------------------------------------------------------------


class StockType(str, Enum):
    NORMAL = "normal"           # 主板，±10%
    ST = "st"                   # ST / *ST，±5%
    STAR = "star"               # 科创板 688xxx，±20%
    CHINEXT_REG = "chinext_reg" # 创业板注册制 300xxx（2020-08-24后），±20%


# 创业板注册制改革生效日
_CHINEXT_REG_DATE = date(2020, 8, 24)


class ASharePriceValidator:
    """
    A 股涨跌停价格校验

    规则：
    - 普通主板：±10%
    - ST / *ST：±5%
    - 科创板(688)：±20%
    - 创业板注册制(300，2020-08-24后上市)：±20%
    """

    LIMIT_PCT_MAP = {
        StockType.NORMAL: 0.10,
        StockType.ST: 0.05,
        StockType.STAR: 0.20,
        StockType.CHINEXT_REG: 0.20,
    }

    @staticmethod
    def get_stock_type(
        ts_code: str,
        stock_name: str,
        list_date: Optional[date] = None,
    ) -> StockType:
        """判断股票类型"""
        code = ts_code.split(".")[0] if "." in ts_code else ts_code
        name_upper = stock_name.upper()

        if "ST" in name_upper:
            return StockType.ST

        if code.startswith("688"):
            return StockType.STAR

        if code.startswith("300") and list_date and list_date >= _CHINEXT_REG_DATE:
            return StockType.CHINEXT_REG

        return StockType.NORMAL

    @classmethod
    def get_limit_pct(cls, stock_type: StockType) -> float:
        """获取涨跌幅限制比例"""
        return cls.LIMIT_PCT_MAP.get(stock_type, 0.10)

    @classmethod
    def calc_limit_prices(
        cls,
        prev_close: float,
        stock_type: StockType,
    ) -> Tuple[float, float]:
        """计算涨停价和跌停价（精确到分）"""
        pct = cls.get_limit_pct(stock_type)
        limit_up = round(prev_close * (1 + pct), 2)
        limit_down = round(prev_close * (1 - pct), 2)
        return limit_up, limit_down

    @staticmethod
    def validate_buy_price(price: float, limit_up: float) -> Tuple[bool, str]:
        """校验买入价格不超过涨停价"""
        if price > limit_up + 0.001:  # 浮点容差
            return False, f"买入价 {price:.2f} 超过涨停价 {limit_up:.2f}"
        return True, ""

    @staticmethod
    def validate_sell_price(price: float, limit_down: float) -> Tuple[bool, str]:
        """校验卖出价格不低于跌停价"""
        if price < limit_down - 0.001:
            return False, f"卖出价 {price:.2f} 低于跌停价 {limit_down:.2f}"
        return True, ""


# ---------------------------------------------------------------------------
# 交易时间和节假日
# ---------------------------------------------------------------------------


class AShareCalendar:
    """
    A 股交易日历

    交易时间：
    - 上午：09:30 - 11:30
    - 下午：13:00 - 15:00
    - 非工作日、法定节假日不交易
    """

    # 2025 - 2026 年 A 股节假日（含调休，交易所公告为准）
    HOLIDAYS: frozenset = frozenset({
        # 2025
        "2025-01-01",  # 元旦
        "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
        "2025-02-03", "2025-02-04",  # 春节
        "2025-04-04",  # 清明
        "2025-05-01", "2025-05-02",  # 劳动节
        "2025-05-31",  # 端午
        "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-06",
        "2025-10-07", "2025-10-08",  # 国庆
        # 2026（预估，实际以公告为准）
        "2026-01-01",  # 元旦
        "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
        "2026-02-23", "2026-02-24",  # 春节
        "2026-04-06",  # 清明
        "2026-05-01",  # 劳动节
        "2026-06-19",  # 端午
        "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06",
        "2026-10-07", "2026-10-08",  # 国庆
    })

    MORNING_START = time(9, 30)
    MORNING_END = time(11, 30)
    AFTERNOON_START = time(13, 0)
    AFTERNOON_END = time(15, 0)

    @classmethod
    def is_trading_day(cls, d: date) -> bool:
        """判断是否为交易日"""
        if d.weekday() >= 5:  # 周六=5, 周日=6
            return False
        return d.isoformat() not in cls.HOLIDAYS

    @classmethod
    def is_trading_time(cls, dt: Optional[datetime] = None) -> bool:
        """判断是否为交易时间（默认使用当前时间）"""
        if dt is None:
            dt = datetime.now()
        if not cls.is_trading_day(dt.date()):
            return False
        t = dt.time()
        in_morning = cls.MORNING_START <= t <= cls.MORNING_END
        in_afternoon = cls.AFTERNOON_START <= t <= cls.AFTERNOON_END
        return in_morning or in_afternoon

    @classmethod
    def next_trading_day(cls, d: date) -> date:
        """获取下一个交易日"""
        from datetime import timedelta
        next_d = d + timedelta(days=1)
        while not cls.is_trading_day(next_d):
            next_d += timedelta(days=1)
        return next_d


# ---------------------------------------------------------------------------
# 手数校验
# ---------------------------------------------------------------------------


class AShareLotValidator:
    """
    A 股手数校验

    规则：
    - 买入：必须为 100 股的整数倍（1手 = 100股）
    - 卖出：无最小单位限制，可卖零股
    """

    LOT_SIZE = 100

    @classmethod
    def validate_buy_quantity(cls, quantity: int) -> Tuple[bool, str]:
        """校验买入数量"""
        if quantity <= 0:
            return False, f"买入数量必须大于0，当前: {quantity}"
        if quantity % cls.LOT_SIZE != 0:
            return False, (
                f"买入数量必须为 {cls.LOT_SIZE} 的整数倍（1手={cls.LOT_SIZE}股），"
                f"当前: {quantity}"
            )
        return True, ""

    @classmethod
    def validate_sell_quantity(
        cls, quantity: int, available_quantity: int
    ) -> Tuple[bool, str]:
        """校验卖出数量（T+1 可卖数量限制）"""
        if quantity <= 0:
            return False, f"卖出数量必须大于0，当前: {quantity}"
        if quantity > available_quantity:
            return False, (
                f"可卖数量不足（T+1规则），可卖: {available_quantity} 股，"
                f"请求: {quantity} 股"
            )
        return True, ""
