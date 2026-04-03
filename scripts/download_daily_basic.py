#!/usr/bin/env python3
"""
下载 tushare daily_basic 数据（换手率、量比、流通市值等）
按交易日批量拉取，保存到本地 CSV。
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from app.config import Settings

settings = Settings()
ts.set_token(settings.TUSHARE_TOKEN)
pro = ts.pro_api()

OUTPUT_FILE = PROJECT_ROOT / "data" / "yearly" / "daily_basic.csv"
START_DATE = "20250225"
END_DATE = "20260225"


def flush_print(msg):
    print(msg, flush=True)


def get_trade_dates(start, end):
    """获取交易日历"""
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end)
    if cal is not None:
        return cal[cal["is_open"] == 1]["cal_date"].tolist()
    return []


def main():
    flush_print("=" * 60)
    flush_print("  下载 daily_basic 数据")
    flush_print(f"  区间: {START_DATE} ~ {END_DATE}")
    flush_print(f"  输出: {OUTPUT_FILE}")
    flush_print("=" * 60)

    # 获取交易日
    flush_print("\n[1/2] 获取交易日历 ...")
    trade_dates = get_trade_dates(START_DATE, END_DATE)
    flush_print(f"  共 {len(trade_dates)} 个交易日")

    # 按日拉取 daily_basic
    flush_print("\n[2/2] 按日拉取 daily_basic ...")
    all_dfs = []
    fields = "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,pe_ttm,pb,total_mv,circ_mv,total_share,float_share,free_share"

    for idx, date in enumerate(trade_dates):
        try:
            df = pro.daily_basic(trade_date=date, fields=fields)
            if df is not None and not df.empty:
                all_dfs.append(df)
        except Exception as e:
            flush_print(f"  {date} 失败: {e}")
            time.sleep(1)

        # 进度 + 限频
        if (idx + 1) % 50 == 0:
            flush_print(
                f"  进度: {idx+1}/{len(trade_dates)} ({(idx+1)/len(trade_dates)*100:.0f}%)"
            )
        if (idx + 1) % 80 == 0:
            time.sleep(1)  # tushare 限频

    if not all_dfs:
        flush_print("  无数据！")
        return

    result = pd.concat(all_dfs, ignore_index=True)
    flush_print(f"\n  总记录: {len(result):,} 行, {result['ts_code'].nunique()} 只股票")

    # 保存
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)
    flush_print(f"  已保存: {OUTPUT_FILE}")
    flush_print(f"  文件大小: {OUTPUT_FILE.stat().st_size / 1024 / 1024:.1f} MB")
    flush_print("\n完成!")


if __name__ == "__main__":
    main()
