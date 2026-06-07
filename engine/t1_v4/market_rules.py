"""
A 股成交现实化规则

回测必须建模的硬约束，否则收益系统性虚高：
  - 涨停买不进 / 一字涨停无法挂单
  - 跌停卖不出 / 一字跌停只能继续持有
  - 印花税（2023-08-28 起千 0.5，仅卖出）
  - 佣金双边 + 单笔最低 5 元
  - 滑点（冲击成本）

涨跌停幅度：主板/中小板 10%，创业板/科创板 20%，北交所 30%，ST 5%。
本系统 VetoFilter 已排除 688/300/8/4，主力为主板 10%，但仍按板块精确判定。
"""

from __future__ import annotations


# ── 涨跌停幅度 ──────────────────────────────────────────────

def board_limit_pct(ts_code: str, is_st: bool = False) -> float:
    """返回该股当日涨跌停幅度（小数）。"""
    if is_st:
        return 0.05
    code = ts_code.split(".")[0]
    if code.startswith(("300", "301", "688")):   # 创业板 / 科创板
        return 0.20
    if code.startswith(("8", "4", "920")):         # 北交所
        return 0.30
    return 0.10                                     # 主板 / 中小板


def limit_up_price(prev_close: float, pct: float) -> float:
    """涨停价（A 股按 0.01 四舍五入）。"""
    return round(prev_close * (1 + pct), 2)


def limit_down_price(prev_close: float, pct: float) -> float:
    """跌停价。"""
    return round(prev_close * (1 - pct), 2)


# 浮点容差：价格按分计，0.005 足够吸收四舍五入误差
_EPS = 0.005


def is_limit_up(close: float, prev_close: float, pct: float) -> bool:
    if prev_close <= 0:
        return False
    return close >= limit_up_price(prev_close, pct) - _EPS


def is_limit_down(close: float, prev_close: float, pct: float) -> bool:
    if prev_close <= 0:
        return False
    return close <= limit_down_price(prev_close, pct) + _EPS


def is_one_word_limit_up(
    o: float, h: float, l: float, c: float, prev_close: float, pct: float
) -> bool:
    """一字涨停：全天封死，无法买入。"""
    if not is_limit_up(c, prev_close, pct):
        return False
    return abs(h - l) <= _EPS and is_limit_up(o, prev_close, pct)


def is_one_word_limit_down(
    o: float, h: float, l: float, c: float, prev_close: float, pct: float
) -> bool:
    """一字跌停：全天封死，无法卖出。"""
    if not is_limit_down(c, prev_close, pct):
        return False
    return abs(h - l) <= _EPS and is_limit_down(o, prev_close, pct)


# ── 滑点 ────────────────────────────────────────────────────

def apply_slippage(price: float, side: str, bps: float) -> float:
    """
    滑点 / 冲击成本。
    买入向上滑、卖出向下滑，bps 为基点（10 bps = 0.1%）。
    """
    adj = bps / 10000.0
    if side == "buy":
        return price * (1 + adj)
    return price * (1 - adj)


# ── 交易成本 ────────────────────────────────────────────────

def buy_cost(shares: int, price: float, commission_rate: float,
             min_commission: float = 5.0) -> float:
    """买入总成本（含佣金，单笔最低 5 元）。"""
    notional = shares * price
    commission = max(notional * commission_rate, min_commission) if notional > 0 else 0.0
    return notional + commission


def sell_revenue(shares: int, price: float, commission_rate: float,
                 stamp_tax_rate: float, min_commission: float = 5.0) -> float:
    """卖出净回款（扣佣金 + 印花税，单笔最低佣金 5 元）。"""
    notional = shares * price
    commission = max(notional * commission_rate, min_commission) if notional > 0 else 0.0
    stamp = notional * stamp_tax_rate
    return notional - commission - stamp
