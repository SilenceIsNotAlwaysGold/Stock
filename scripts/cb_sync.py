#!/usr/bin/env python3
"""
可转债数据层同步（AKShare 免费源，幂等增量）

产出 data/cb/：
  universe.csv  —— 转债全集：债券代码/简称/正股代码/转股价/信用评级/发行规模/上市时间
  daily/<code>.csv —— 每只转债历史日线 date,open,high,low,close,volume

双低历史可由 [转债close + 已有8年正股close + 转股价] 重构（见 cb_backtest）。
转债优势：无印花税、佣金极低、T+0、规则透明 —— 正是杀死股票策略的成本项在此结构性小。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings("ignore")
import akshare as ak
import pandas as pd

CB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "cb")
DAILY_DIR = os.path.join(CB_DIR, "daily")
os.makedirs(DAILY_DIR, exist_ok=True)


def main():
    print("[1/2] 拉取转债全集 bond_zh_cov ...", flush=True)
    uni = ak.bond_zh_cov()
    keep = ["债券代码", "债券简称", "正股代码", "正股简称", "转股价",
            "发行规模", "上市时间", "信用评级"]
    uni = uni[[c for c in keep if c in uni.columns]].copy()
    # 仅保留已上市（有上市时间）的
    uni = uni[uni["上市时间"].astype(str).str.len() >= 8]
    uni.to_csv(os.path.join(CB_DIR, "universe.csv"), index=False)
    print(f"  转债全集 {len(uni)} 只 -> universe.csv", flush=True)

    codes = uni["债券代码"].astype(str).tolist()
    # 交易所前缀：1开头沪市 sh，否则深市 sz（11x沪 12x深 既有规则）
    def _sym(code):
        return ("sh" if code.startswith("11") or code.startswith("13")
                else "sz") + code

    print(f"[2/2] 拉取 {len(codes)} 只转债历史日线 ...", flush=True)
    ok = fail = skip = 0
    for i, code in enumerate(codes):
        fp = os.path.join(DAILY_DIR, f"{code}.csv")
        if os.path.exists(fp) and os.path.getsize(fp) > 200:
            skip += 1
            continue
        try:
            df = ak.bond_zh_hs_cov_daily(symbol=_sym(code))
            if df is not None and not df.empty and "close" in df.columns:
                df.to_csv(fp, index=False)
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            if "exceed" in str(e).lower() or "频" in str(e):
                time.sleep(30)
        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(codes)}] ok={ok} skip={skip} fail={fail}",
                  flush=True)
            time.sleep(1.0)
    print(f"\n完成：写入 {ok}，已存跳过 {skip}，失败 {fail}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
