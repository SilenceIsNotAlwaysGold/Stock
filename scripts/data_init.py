#!/usr/bin/env python3
"""
数据初始化脚本

一键从 Tushare 下载回测所需的全量数据。
使用方式: python scripts/data_init.py [--start 20250101] [--end 20260401] [--token YOUR_TOKEN]
"""

import sys
import time
import argparse
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
YEARLY_DIR = DATA_DIR / "yearly"
INDEX_DIR = DATA_DIR / "index"


def ensure_dirs():
    """确保数据目录存在"""
    for d in [DATA_DIR, YEARLY_DIR, INDEX_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def download_stock_list(pro) -> pd.DataFrame:
    """下载全市场股票列表"""
    print("  下载股票列表...")
    df = pro.stock_basic(exchange="", list_status="L",
                         fields="ts_code,name,industry,area,market,list_date")
    out = DATA_DIR / "stock_list.csv"
    df.to_csv(out, index=False)
    print(f"  保存 {out}: {len(df)} 只股票")
    return df


def download_daily_bars(pro, stock_list: pd.DataFrame, start: str, end: str):
    """
    逐只下载日线数据，合并为一个大 CSV。
    Tushare 限流：每分钟 200 次，每 10 只 sleep 1 秒。
    """
    print(f"  下载日线数据 {start} ~ {end}...")
    codes = stock_list["ts_code"].tolist()
    all_dfs = []
    errors = []

    for i, code in enumerate(codes):
        try:
            import tushare as ts
            df = ts.pro_bar(ts_code=code, start_date=start, end_date=end, adj="qfq")
            if df is not None and not df.empty:
                all_dfs.append(df)
        except Exception as e:
            errors.append(f"{code}: {str(e)[:50]}")

        # 进度 + 限流
        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{len(codes)} ({len(all_dfs)} 有数据, {len(errors)} 失败)")
        if (i + 1) % 10 == 0:
            time.sleep(0.6)  # Tushare 限流

    if all_dfs:
        big_df = pd.concat(all_dfs, ignore_index=True)
        out = YEARLY_DIR / "all_stocks_daily.csv"
        big_df.to_csv(out, index=False)
        print(f"  保存 {out}: {len(big_df):,} 行, {big_df['ts_code'].nunique()} 只股票")
    else:
        print("  警告：没有下载到任何日线数据!")

    if errors:
        print(f"  失败 {len(errors)} 只: {errors[:5]}...")


def download_index_daily(pro, start: str, end: str):
    """下载上证指数日线"""
    print("  下载上证指数日线...")
    import tushare as ts
    df = ts.pro_bar(ts_code="000001.SH", asset="I", start_date=start, end_date=end)
    if df is not None and not df.empty:
        out = INDEX_DIR / "index_daily.csv"
        df.to_csv(out, index=False)
        print(f"  保存 {out}: {len(df)} 行")


def main():
    parser = argparse.ArgumentParser(description="T1 v4 数据初始化")
    parser.add_argument("--start", default="20250101", help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default="20260401", help="结束日期 YYYYMMDD")
    parser.add_argument("--token", default=None, help="Tushare Token（也可通过 .env 配置）")
    args = parser.parse_args()

    import tushare as ts

    token = args.token
    if not token:
        try:
            from app.config import Settings
            token = Settings().TUSHARE_TOKEN
        except Exception:
            pass

    if not token:
        print("错误：请提供 Tushare Token（--token 参数或 .env 中的 TUSHARE_TOKEN）")
        sys.exit(1)

    ts.set_token(token)
    pro = ts.pro_api()

    ensure_dirs()
    stock_list = download_stock_list(pro)
    download_daily_bars(pro, stock_list, args.start, args.end)
    download_index_daily(pro, args.start, args.end)
    print("\n数据初始化完成!")


if __name__ == "__main__":
    main()
