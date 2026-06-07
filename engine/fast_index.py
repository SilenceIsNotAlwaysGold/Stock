"""
回测/情绪共享的高速索引（消除 pandas 逐行访问瓶颈）

把每只股票的日线一次性转成 numpy 列数组 +
向量化预计算 涨停/跌停 掩码、连板 run-length。

热循环只做 O(1) 数组下标访问，不再 df.iloc[i]（原瓶颈 75% 在此）。
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from engine.t1_v4.market_rules import board_limit_pct

_EPS = 0.005


def build_fast_index(all_daily_data: Dict[str, pd.DataFrame]) -> Dict[str, dict]:
    """
    ts_code -> {
      pos: {dnorm: i}, dnorm: list[str], n: int,
      o,h,l,c,vol,amt,tr: np.ndarray(float),
      lu,ld: np.ndarray(bool)   # 当日是否涨/跌停（相对前收）
      cons: np.ndarray(int)     # 截至当日的连续涨停数
      df: 原 DataFrame（升序，供风格 select 切片）
      pct: float                # 该股涨跌停幅度
    }
    """
    out: Dict[str, dict] = {}
    for ts_code, df in all_daily_data.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        d["dnorm"] = d["date"].astype(str).str.replace("-", "")
        d = d.sort_values("dnorm").reset_index(drop=True)
        n = len(d)
        c = d["close"].astype(float).to_numpy()
        o = d["open"].astype(float).to_numpy()
        h = d["high"].astype(float).to_numpy()
        lo = d["low"].astype(float).to_numpy()
        vol = d["volume"].astype(float).to_numpy() if "volume" in d else np.zeros(n)
        amt = d["amount"].astype(float).to_numpy() if "amount" in d else np.zeros(n)
        tr = (d["turnover_rate"].astype(float).to_numpy()
              if "turnover_rate" in d else np.zeros(n))
        pct = board_limit_pct(ts_code)

        lu = np.zeros(n, dtype=bool)
        ld = np.zeros(n, dtype=bool)
        if n >= 2:
            prev = c[:-1]
            up_price = np.round(prev * (1 + pct), 2)
            dn_price = np.round(prev * (1 - pct), 2)
            lu[1:] = (c[1:] >= up_price - _EPS) & (prev > 0)
            ld[1:] = (c[1:] <= dn_price + _EPS) & (prev > 0)

        cons = np.zeros(n, dtype=int)
        run = 0
        for i in range(n):
            run = run + 1 if lu[i] else 0
            cons[i] = run

        out[ts_code] = {
            "pos": {v: i for i, v in enumerate(d["dnorm"])},
            "dnorm": d["dnorm"].tolist(),
            "n": n, "df": d, "pct": pct,
            "o": o, "h": h, "l": lo, "c": c,
            "vol": vol, "amt": amt, "tr": tr,
            "lu": lu, "ld": ld, "cons": cons,
        }
    return out
