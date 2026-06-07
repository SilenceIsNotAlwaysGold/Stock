#!/usr/bin/env python3
"""
因子边际筛查（先验证再造策略）

对每个候选因子，全市场逐日横截面计算：
  - RankIC = Spearman(因子, T+1开盘→T+2开盘 真实可交易收益)
  - ICIR   = mean(IC) / std(IC)
  - IC>0 占比
  - 五分位多空价差（top20% - bottom20% 的 T+1 收益，看单调性）
  - top/bottom 十分位 T+1..T+5 远期收益（真实：T+1开盘买，T+1+h开盘量）

不含任何策略/择时/止盈止损 —— 纯看因子自身有没有预测力。
仅用 OHLCV+换手（DB 已有），研报实证因子。
口径：T 日收盘算因子 → 只能 T+1 开盘才动 → 远期收益从 T+1 开盘计（无未来函数）。
"""

import asyncio
import sys
import os
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.core.database import async_session
from app.models.pg_models import DailyBar, Stock
from engine.fast_index import build_fast_index

import os as _os
# 默认自动用全 DB 日期范围（同步 8 年后自动覆盖多牛熊周期）；可用环境变量覆盖
START = _os.environ.get("FS_START", "")   # 空 = DB 最早
END = _os.environ.get("FS_END", "")       # 空 = DB 最晚
_NON_MAIN = ("300", "301", "688", "8", "4", "920")


from sqlalchemy import func as _func


async def load():
    async with async_session() as db:
        global START, END
        if not START or not END:
            rng = await db.execute(select(_func.min(DailyBar.trade_date),
                                          _func.max(DailyBar.trade_date)))
            mn, mx = rng.one()
            START = START or str(mn)
            END = END or str(mx)
        print(f"筛查区间(全DB): {START} ~ {END}", flush=True)
        r = await db.execute(
            select(DailyBar).where(DailyBar.trade_date >= date.fromisoformat(START))
            .where(DailyBar.trade_date <= date.fromisoformat(END))
            .order_by(DailyBar.ts_code, DailyBar.trade_date))
        by = defaultdict(list)
        for b in r.scalars().all():
            by[b.ts_code].append({
                "date": str(b.trade_date), "open": float(b.open or 0),
                "high": float(b.high or 0), "low": float(b.low or 0),
                "close": float(b.close or 0), "volume": float(b.volume or 0),
                "amount": float(b.amount or 0),
                "turnover_rate": float(b.turnover_rate or 0)})
        data = {c: pd.DataFrame(v) for c, v in by.items()}
        r2 = await db.execute(select(Stock.ts_code, Stock.name)
                              .where(Stock.is_active == True))
        names = {x.ts_code: (x.name or "") for x in r2.all()}
        r3 = await db.execute(
            select(DailyBar.trade_date).where(DailyBar.trade_date >= date.fromisoformat(START))
            .where(DailyBar.trade_date <= date.fromisoformat(END))
            .group_by(DailyBar.trade_date).order_by(DailyBar.trade_date))
        dates = [str(x[0]).replace("-", "") for x in r3.all()]
    return data, names, dates


# ── 候选因子：给定 (e, p) 返回因子值（越大代表越"看多"假设；后看 IC 符号）──
def f_overnight_gap5(e, p):          # 近5日平均隔夜跳空（研报:负IC）
    if p < 6:
        return np.nan
    o, c = e["o"], e["c"]
    g = [(o[i] - c[i - 1]) / c[i - 1] for i in range(p - 4, p + 1) if c[i - 1] > 0]
    return float(np.mean(g)) if g else np.nan


def f_rps20(e, p):                   # 20日动量
    if p < 21 or e["c"][p - 20] <= 0:
        return np.nan
    return (e["c"][p] - e["c"][p - 20]) / e["c"][p - 20]


def f_reversal5(e, p):               # 5日反转（取负的近5日涨幅）
    if p < 6 or e["c"][p - 5] <= 0:
        return np.nan
    return -((e["c"][p] - e["c"][p - 5]) / e["c"][p - 5])


def f_turnover(e, p):                # 当日换手率
    return float(e["tr"][p]) if e["tr"][p] > 0 else np.nan


def f_vol_ratio(e, p):               # 量比 = 今量/5日均量
    if p < 6:
        return np.nan
    base = np.mean(e["vol"][p - 5:p])
    return float(e["vol"][p] / base) if base > 0 else np.nan


def f_amplitude20(e, p):             # 20日平均振幅（低波动因子→取负）
    if p < 21:
        return np.nan
    h, l, c = e["h"], e["l"], e["c"]
    a = [(h[i] - l[i]) / c[i - 1] for i in range(p - 19, p + 1) if c[i - 1] > 0]
    return -float(np.mean(a)) if a else np.nan


def f_dist_high60(e, p):             # 距60日高点（越接近高点值越大）
    if p < 61:
        return np.nan
    hi = np.max(e["c"][p - 59:p + 1])
    return (e["c"][p] - hi) / hi if hi > 0 else np.nan


def f_cons_board(e, p):              # 连板数（预计算）
    return float(e["cons"][p])


def f_toi20(e, p):                   # 隔夜-日内拉锯（负相关→正）
    if p < 21:
        return np.nan
    o, c = e["o"], e["c"]
    ov, it = [], []
    for i in range(p - 19, p + 1):
        if c[i - 1] > 0 and o[i] > 0:
            ov.append((o[i] - c[i - 1]) / c[i - 1])
            it.append((c[i] - o[i]) / o[i])
    if len(ov) < 8 or np.std(ov) == 0 or np.std(it) == 0:
        return np.nan
    return -float(np.corrcoef(ov, it)[0, 1])


FACTORS = {
    "隔夜跳空5": f_overnight_gap5, "RPS20动量": f_rps20,
    "5日反转": f_reversal5, "换手率": f_turnover, "量比": f_vol_ratio,
    "低波动20": f_amplitude20, "距60高": f_dist_high60,
    "连板数": f_cons_board, "TOI拉锯": f_toi20,
}


def main():
    data, names, dates = asyncio.run(load())
    idx = build_fast_index(data)
    # 主板 + 非ST
    codes = [c for c in idx
             if not c.split(".")[0].startswith(_NON_MAIN)
             and "ST" not in (names.get(c, "").upper())]
    print(f"载入 {len(idx)} 股，筛查池(主板非ST) {len(codes)}，{len(dates)} 日", flush=True)

    dpos = {dn: i for i, dn in enumerate(dates)}
    stats = {k: {"ic": [], "q_spread": [], "fwd": [[] for _ in range(5)]}
             for k in FACTORS}

    for di in range(60, len(dates) - 6):     # 留 60 回看 + 6 前瞻
        dn = dates[di]
        per_fac_vals = {k: [] for k in FACTORS}
        fwd1 = []   # T+1开→T+2开 收益（与因子对齐做 IC）
        fwdh = []   # [T+1开→T+1+h开] h=1..5
        keys = []
        for c in codes:
            e = idx.get(c)
            if not e:
                continue
            p = e["pos"].get(dn)
            if p is None or p < 61 or p + 6 >= e["n"]:
                continue
            o = e["o"]
            o1 = o[p + 1]
            if o1 <= 0:
                continue
            r1 = (o[p + 2] - o1) / o1
            rh = [(o[p + 1 + h] - o1) / o1 for h in range(1, 6)]
            row = {}
            ok = True
            for k, fn in FACTORS.items():
                v = fn(e, p)
                if v != v:           # nan
                    ok = False
                    break
                row[k] = v
            if not ok:
                continue
            for k in FACTORS:
                per_fac_vals[k].append(row[k])
            fwd1.append(r1)
            fwdh.append(rh)
            keys.append(c)

        if len(keys) < 50:
            continue
        fwd1 = np.array(fwd1)
        fwdh = np.array(fwdh)
        for k in FACTORS:
            fv = pd.Series(per_fac_vals[k])
            rv = pd.Series(fwd1)
            ic = fv.rank().corr(rv.rank())   # Spearman（无 scipy）
            if ic == ic:
                stats[k]["ic"].append(ic)
            # 五分位多空（按因子升序分5档，top档 - bottom档 的 T+1 收益）
            order = np.argsort(fv.values)
            n = len(order)
            q = n // 5
            if q >= 5:
                bot = fwd1[order[:q]].mean()
                top = fwd1[order[-q:]].mean()
                stats[k]["q_spread"].append(top - bot)
                for h in range(5):
                    stats[k]["fwd"][h].append(fwdh[order[-q:], h].mean())

    print("\n=== 因子边际筛查结果（2 年，真实 T+1 开盘进场口径）===")
    print(f"{'因子':<10}{'RankIC':>8}{'ICIR':>7}{'IC>0%':>7}"
          f"{'五分位价差%':>11}{'TopT+1%':>8}{'TopT+5%':>8}{'天数':>6}")
    print("-" * 70)
    rows = []
    for k in FACTORS:
        ics = np.array(stats[k]["ic"])
        if len(ics) < 20:
            continue
        icm = ics.mean()
        icir = icm / ics.std() if ics.std() > 0 else 0.0
        icpos = (ics > 0).mean()
        qs = np.mean(stats[k]["q_spread"]) * 100 if stats[k]["q_spread"] else 0.0
        t1 = np.mean(stats[k]["fwd"][0]) * 100 if stats[k]["fwd"][0] else 0.0
        t5 = np.mean(stats[k]["fwd"][4]) * 100 if stats[k]["fwd"][4] else 0.0
        rows.append((abs(icir), k, icm, icir, icpos, qs, t1, t5, len(ics)))
    for _, k, icm, icir, icpos, qs, t1, t5, n in sorted(rows, reverse=True):
        print(f"{k:<10}{icm:>8.4f}{icir:>7.2f}{icpos:>6.0%}"
              f"{qs:>11.3f}{t1:>8.3f}{t5:>8.3f}{n:>6}")
    print("\n判读：|ICIR|>0.3 且 五分位价差与 IC 同号、单调 → 有可用边际；"
          "RankIC 符号代表方向（负 IC = 因子越小越涨）。")


if __name__ == "__main__":
    main()
