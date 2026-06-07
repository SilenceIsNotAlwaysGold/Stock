#!/usr/bin/env python3
"""
T1 v4 策略独立回测脚本

直接从 Tushare 拉取数据，运行回测引擎，输出结果。
无需启动 Docker/数据库。

用法: python scripts/run_backtest.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import tushare as ts
from app.config import settings
from engine.t1_v4.backtester import T1Backtester

# ── 配置 ──
START_DATE = "20251001"  # 回测起始
END_DATE = "20260411"    # 回测结束
INITIAL_CASH = 100000.0

# 排除的板块前缀（与系统配置一致）
EXCLUDED_PREFIXES = ("688", "300", "8", "4")


def main():
    print("=" * 60)
    print("T1 v4 策略历史回测")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: {INITIAL_CASH:,.0f}")
    print(f"参数: TOP_N={settings.T1_TOP_N}, 门槛={settings.T1_MIN_TOTAL_SCORE}, 安全门={settings.T1_MARKET_SAFE_THRESHOLD}")
    print("=" * 60)

    pro = ts.pro_api(settings.TUSHARE_TOKEN)

    # 1. 获取股票列表
    print("\n[1/4] 获取沪深主板+中小板股票列表...")
    stock_list = pro.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,name,industry,list_date",
    )

    # 过滤：仅保留主板+中小板
    def is_allowed(code):
        for prefix in EXCLUDED_PREFIXES:
            if code.startswith(prefix):
                return False
        # 排除ST
        return True

    stock_list = stock_list[
        stock_list["ts_code"].apply(lambda x: is_allowed(x.split(".")[0]))
    ]
    # 排除ST名称
    stock_list = stock_list[~stock_list["name"].str.contains("ST", case=False, na=False)]

    print(f"  符合条件的股票: {len(stock_list)} 只")

    stock_info = {}
    for _, row in stock_list.iterrows():
        stock_info[row["ts_code"]] = {
            "name": row["name"],
            "industry": row["industry"] or "",
            "list_date": row["list_date"],
        }

    # 2. 获取交易日历
    print("\n[2/4] 获取交易日历...")
    cal = pro.trade_cal(
        exchange="SSE",
        start_date=START_DATE,
        end_date=END_DATE,
        is_open="1",
    )
    trade_dates = sorted(cal["cal_date"].tolist())
    print(f"  交易日数: {len(trade_dates)} 天")

    # 3. 批量获取日线数据
    print(f"\n[3/4] 批量获取日线数据（{len(stock_info)} 只股票）...")
    print("  这可能需要几分钟，取决于 Tushare 积分和接口限制...")

    all_daily_data = {}
    total = len(stock_info)
    loaded = 0
    failed = 0

    # 按批次获取，避免超频
    codes = list(stock_info.keys())

    for i, ts_code in enumerate(codes):
        try:
            df = pro.daily(
                ts_code=ts_code,
                start_date=START_DATE,
                end_date=END_DATE,
                fields="trade_date,open,high,low,close,vol,amount,pct_chg",
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_date": "date",
                    "vol": "volume",
                })
                # 补充 turnover_rate（如果没有，设为0）
                if "turnover_rate" not in df.columns:
                    df["turnover_rate"] = 0.0
                df = df.sort_values("date").reset_index(drop=True)
                all_daily_data[ts_code] = df
                loaded += 1
        except Exception as e:
            failed += 1
            if "每分钟" in str(e) or "exceed" in str(e).lower():
                print(f"  触发频率限制，等待 60 秒...")
                time.sleep(60)
                # 重试
                try:
                    df = pro.daily(
                        ts_code=ts_code,
                        start_date=START_DATE,
                        end_date=END_DATE,
                        fields="trade_date,open,high,low,close,vol,amount,pct_chg",
                    )
                    if df is not None and not df.empty:
                        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
                        if "turnover_rate" not in df.columns:
                            df["turnover_rate"] = 0.0
                        df = df.sort_values("date").reset_index(drop=True)
                        all_daily_data[ts_code] = df
                        loaded += 1
                        failed -= 1
                except Exception:
                    pass

        if (i + 1) % 100 == 0:
            print(f"  进度: {i+1}/{total} ({loaded} 成功, {failed} 失败)")

        # Tushare 免费版限制：每分钟约 200 次
        if (i + 1) % 190 == 0:
            print(f"  等待频率限制冷却 (60s)...")
            time.sleep(61)

    print(f"  完成: {loaded} 只有数据, {failed} 只失败")

    if loaded < 100:
        print("\n数据量不足（<100只），回测结果可能不可靠")
        print("建议检查 Tushare 积分是否足够")

    # 4. 运行回测
    print(f"\n[4/4] 运行 T1 v4 回测引擎...")
    print(f"  股票池: {loaded} 只")
    print(f"  交易日: {len(trade_dates)} 天")

    bt = T1Backtester(
        initial_cash=INITIAL_CASH,
        top_n=settings.T1_TOP_N,
        market_safe_threshold=settings.T1_MARKET_SAFE_THRESHOLD,
        min_total_score=settings.T1_MIN_TOTAL_SCORE,
    )

    t0 = time.time()
    result = bt.run(
        all_daily_data=all_daily_data,
        stock_info=stock_info,
        trade_dates=trade_dates,
    )
    elapsed = time.time() - t0

    # 输出结果
    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)

    print(f"""
区间:         {result.start_date} ~ {result.end_date}
初始资金:     {result.initial_cash:>12,.2f}
最终资金:     {result.final_cash:>12,.2f}

总收益率:     {result.total_return_pct:>8.2f}%
年化收益率:   {result.annual_return_pct:>8.2f}%
最大回撤:     {result.max_drawdown_pct:>8.2f}%
Sharpe比率:   {result.sharpe_ratio:>8.2f}
Sortino比率:  {result.sortino_ratio:>8.2f}
盈亏比:       {result.profit_factor:>8.2f}
单笔期望:     {result.expectancy_pct:>8.2f}%

总交易次数:   {result.total_trades:>8d}
盈利/亏损:    {result.win_count:>4d} / {result.loss_count:<4d}
胜率:         {result.win_rate*100:>8.2f}%
平均盈利:     {result.avg_win_pct:>8.2f}%
平均亏损:     {result.avg_loss_pct:>8.2f}%
平均盈亏:     {result.avg_pnl_pct:>8.2f}%
最大单笔盈利: {result.max_win_pct:>8.2f}%
最大单笔亏损: {result.max_loss_pct:>8.2f}%
平均持仓:     {result.avg_holding_days:>8.2f} 个交易日
年化换手:     {result.annual_turnover:>8.2f} 倍
成本拖累:     {result.cost_drag_pct:>8.2f}% (佣金+印花+滑点/初始资金)
评分IC/ICIR:  {result.score_ic:>8.4f} / {result.score_icir:.2f}
顺延次数:     {result.stuck_events:>8d} (一字/停牌)

交易天数:     {result.trading_days:>8d}
空仓天数:     {result.no_trade_days:>8d} (大盘不安全)
回测耗时:     {elapsed:>8.1f}s

【保守实盘预期】 {result.expected_live_return_pct:>6.2f}%  = 回测总收益 ×(1-{result.live_decay:.0%})
   ⚠ 回测→实盘普遍衰减30-50%，请以保守值评估，非收益保证
""")

    if result.event_study:
        print("事件研究（买入后持有N日的毛收益分布，独立于卖出逻辑）:")
        print(f"  {'区间':<6} {'样本':>5} {'平均':>8} {'中位':>8} {'胜率':>7}")
        print("  " + "-" * 40)
        for ev in result.event_study:
            print(f"  {ev['horizon']:<6} {ev['n']:>5} {ev['avg_ret_pct']:>7.2f}% "
                  f"{ev['median_ret_pct']:>7.2f}% {ev['win_rate']*100:>6.1f}%")
        print()

    if result.realism_notes:
        print("成交现实化口径:")
        for n in result.realism_notes:
            print(f"  · {n}")
        print()

    if result.monthly_returns:
        print("月度收益:")
        print(f"  {'月份':<10} {'交易数':>6} {'胜率':>8} {'平均盈亏':>8} {'月总盈亏':>8}")
        print("  " + "-" * 48)
        for m in result.monthly_returns:
            print(
                f"  {m['month']:<10} {m['trades']:>6} "
                f"{m['win_rate']*100:>7.1f}% {m['avg_pnl_pct']:>7.2f}% {m['total_pnl_pct']:>7.2f}%"
            )

    if result.trades:
        print(f"\n最近 10 笔交易:")
        print(f"  {'买入日':>10} {'卖出日':>10} {'代码':<12} {'名称':<8} {'评分':>5} {'盈亏%':>7} {'原因'}")
        print("  " + "-" * 75)
        for t in result.trades[-10:]:
            win_mark = "+" if t.is_win else "-"
            print(
                f"  {t.buy_date:>10} {t.sell_date:>10} {t.ts_code:<12} "
                f"{t.stock_name:<8} {t.score:>5.1f} {win_mark}{abs(t.pnl_pct):>6.2f}% {t.sell_reason}"
            )

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
