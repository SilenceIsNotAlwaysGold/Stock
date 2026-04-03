"""
T+1 策略 v2 - 独立回测引擎

纯内存运行，不依赖数据库。
支持每个子策略单独回测，输出胜率、收益、回撤、夏普比率。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engine.base import BaseStrategy
from engine.t1_sell_engine import SmartSellEngine, SellDecision

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """单笔交易记录"""

    date: str
    ts_code: str
    stock_name: str
    strategy: str
    buy_price: float
    sell_price: float
    sell_reason: str
    pnl_pct: float
    is_win: bool


@dataclass
class BacktestResult:
    """回测结果"""

    strategy_name: str
    period: str
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    avg_return_pct: float = 0.0
    max_return_pct: float = 0.0
    min_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    trades: List[TradeRecord] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)


class T1Backtester:
    """
    T+1 隔夜策略回测器 (R-008)

    流程：
    1. 遍历每个交易日
    2. 用尾盘数据运行子策略 → 产生买入信号
    3. 用次日开盘数据运行智能卖出引擎 → 模拟卖出
    4. 记录每笔交易，计算统计指标
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        sell_engine: Optional[SmartSellEngine] = None,
    ):
        self.strategy = strategy
        self.sell_engine = sell_engine or SmartSellEngine()

    def run(
        self,
        daily_data: pd.DataFrame,
        stock_name: str = "",
        ts_code: str = "",
        context_fn=None,
    ) -> BacktestResult:
        """
        对单只股票运行回测。

        Args:
            daily_data: 日线数据，需含 date/open/high/low/close/volume 列，按日期正序
            stock_name: 股票名称
            ts_code: 股票代码
            context_fn: 可选，返回每日 context 的函数 fn(date, df_slice) -> dict
        """
        result = BacktestResult(
            strategy_name=self.strategy.name,
            period=(
                f"{daily_data['date'].iloc[0]} ~ {daily_data['date'].iloc[-1]}"
                if len(daily_data) > 0
                else ""
            ),
        )

        if len(daily_data) < 10:
            return result

        trades = []
        returns = []

        for i in range(30, len(daily_data) - 1):
            # 用截止到第 i 天的数据做分析（尾盘）
            df_slice = daily_data.iloc[: i + 1].copy()
            ctx = (
                context_fn(daily_data.iloc[i]["date"], df_slice) if context_fn else None
            )

            sig = self.strategy.signal(df_slice, context=ctx)

            if sig.action != "BUY" or sig.confidence < 0.5:
                returns.append(0.0)
                continue

            # 买入价 = 当天收盘价
            buy_price = float(daily_data.iloc[i]["close"])
            if buy_price <= 0:
                returns.append(0.0)
                continue

            # 次日数据
            next_day = daily_data.iloc[i + 1]
            open_price = float(next_day["open"])
            high_price = float(next_day["high"])
            low_price = float(next_day["low"])
            close_price = float(next_day["close"])

            # 智能卖出决策
            decision = self.sell_engine.simulate_morning_sell(
                buy_price=buy_price,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
            )

            sell_price = decision.sell_price if decision.sell_price > 0 else open_price
            pnl_pct = (sell_price - buy_price) / buy_price * 100

            trade = TradeRecord(
                date=str(daily_data.iloc[i].get("date", "")),
                ts_code=ts_code,
                stock_name=stock_name,
                strategy=self.strategy.name,
                buy_price=buy_price,
                sell_price=round(sell_price, 2),
                sell_reason=decision.reason.value,
                pnl_pct=round(pnl_pct, 2),
                is_win=pnl_pct > 0,
            )
            trades.append(trade)
            returns.append(pnl_pct)

        # 计算统计指标
        result.trades = trades
        result.daily_returns = returns
        result.total_trades = len(trades)

        if trades:
            pnls = [t.pnl_pct for t in trades]
            result.win_count = sum(1 for t in trades if t.is_win)
            result.loss_count = result.total_trades - result.win_count
            result.win_rate = result.win_count / result.total_trades
            result.total_return_pct = round(sum(pnls), 2)
            result.avg_return_pct = round(np.mean(pnls), 2)
            result.max_return_pct = round(max(pnls), 2)
            result.min_return_pct = round(min(pnls), 2)

            # 最大回撤
            cumulative = np.cumsum(pnls)
            peak = np.maximum.accumulate(cumulative)
            drawdown = cumulative - peak
            result.max_drawdown_pct = (
                round(float(np.min(drawdown)), 2) if len(drawdown) > 0 else 0.0
            )

            # 夏普比率（年化，假设 250 个交易日）
            if len(pnls) > 1:
                std = np.std(pnls)
                if std > 0:
                    result.sharpe_ratio = round(np.mean(pnls) / std * np.sqrt(250), 2)

        return result

    def format_report(self, result: BacktestResult) -> str:
        """格式化回测报告"""
        lines = [
            f"{'='*60}",
            f"  策略: {result.strategy_name}",
            f"  区间: {result.period}",
            f"{'='*60}",
            f"  总交易次数: {result.total_trades}",
            f"  胜率: {result.win_rate*100:.1f}% ({result.win_count}胜 / {result.loss_count}负)",
            f"  总收益: {result.total_return_pct:+.2f}%",
            f"  平均单次收益: {result.avg_return_pct:+.2f}%",
            f"  最大单次收益: {result.max_return_pct:+.2f}%",
            f"  最大单次亏损: {result.min_return_pct:+.2f}%",
            f"  最大回撤: {result.max_drawdown_pct:.2f}%",
            f"  夏普比率: {result.sharpe_ratio:.2f}",
            f"{'='*60}",
        ]

        # 卖出原因分布
        if result.trades:
            reason_counts: Dict[str, int] = {}
            for t in result.trades:
                reason_counts[t.sell_reason] = reason_counts.get(t.sell_reason, 0) + 1
            lines.append("  卖出原因分布:")
            for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
                lines.append(
                    f"    {reason}: {count} 次 ({count/result.total_trades*100:.1f}%)"
                )

        return "\n".join(lines)
