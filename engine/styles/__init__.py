"""
多交易风格框架

把"交易方式"抽象为 TradingStyle：短线(隔夜) / 打板 / 波段 / 长线。
每种风格定义自己的选股逻辑 + 退出逻辑 + 持仓周期，
统一走 StyleBacktester（复用阶段1 的成交现实化：涨跌停/印花税/滑点/顺延）。
"""

from engine.styles.base import (
    STYLE_REGISTRY,
    DayContext,
    StyleExit,
    StylePick,
    TradingStyle,
    get_style,
    list_styles,
)

# 导入各风格以触发注册
from engine.styles import (  # noqa: E402,F401
    broad_basket, broad_trend, daban, firstboard_pullback, long_term,
    multifactor, regime_gated, reversal, short_t1, swing,
)

__all__ = [
    "TradingStyle",
    "StylePick",
    "StyleExit",
    "DayContext",
    "STYLE_REGISTRY",
    "get_style",
    "list_styles",
]
