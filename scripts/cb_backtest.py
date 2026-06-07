#!/usr/bin/env python3
"""
可转债 双低+信用过滤 月度轮动 —— 重构 + 诚实多周期回测

CB-2 重构：双低 = 转债close + 溢价率×100；溢价率 = 转债close/转股价值 - 1；
          转股价值 = 100/转股价 × 正股close。正股 close 用 PG 已有 A 股日线。
CB-3 回测：月度选 双低最低 N 只(信用过滤后)，等权，转债低成本(无印花/佣金极低)，
          逐年样本外 + 全程 + 2024H2 尾部压测 vs 转债等权基准。

诚实声明的局限（必须随结果一并报告）：
  - universe 的转股价是【当前值】；历史下修未还原 → 下修过的债历史溢价率有偏（有界但真实）
  - 信用评级为【当前快照】，作静态过滤代理，非时点评级
  - 故本回测为"方向性可信"而非"精确"；以逐年样本外是否打不倒为准
"""

import asyncio
import glob
import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sqlalchemy import select, func

from app.core.database import async_session
from app.models.pg_models import DailyBar

CB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "cb")
RATING_OK = {"AAA", "AA+", "AA", "AA-"}     # 信用过滤：AA- 及以上
TOP_N = 20
MIN_SIZE = 3.0          # 发行规模 ≥ 3 亿（剔除迷你盘流动性差）
PRICE_CAP = 135.0       # 价格 > 135 多为强赎博弈尾部，剔除
PRICE_FLOOR = 70.0      # 价格 < 70 深度违约风险（信用过滤已挡，再兜底）
# 转债成本：佣金极低、无印花税、滑点小 → 单边约 0.06%，双边 ~0.12%
CB_RT_COST = 0.0012


def _stk_ts(code: str) -> str:
    c = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)
    if c[0] in ("6", "9", "5"):
        return f"{c}.SH"
    if c[0] in ("4", "8") or c.startswith("92"):
        return f"{c}.BJ"
    return f"{c}.SZ"


async def load_stock_closes(codes_needed):
    """从 PG 取所需正股的全历史收盘：{ts_code: {dnorm: close}}"""
    async with async_session() as db:
        rng = await db.execute(select(func.min(DailyBar.trade_date),
                                      func.max(DailyBar.trade_date)))
        mn, mx = rng.one()
        r = await db.execute(
            select(DailyBar.ts_code, DailyBar.trade_date, DailyBar.close)
            .where(DailyBar.ts_code.in_(list(codes_needed)))
            .where(DailyBar.trade_date >= mn).where(DailyBar.trade_date <= mx)
            .order_by(DailyBar.ts_code, DailyBar.trade_date))
        out = defaultdict(dict)
        for ts, d, c in r.all():
            out[ts][str(d).replace("-", "")] = float(c or 0)
    return out


def main():
    uni = pd.read_csv(os.path.join(CB_DIR, "universe.csv"), dtype=str)
    uni["转股价"] = pd.to_numeric(uni["转股价"], errors="coerce")
    uni["发行规模"] = pd.to_numeric(uni["发行规模"], errors="coerce")
    uni = uni.dropna(subset=["转股价", "正股代码"])
    uni = uni[uni["转股价"] > 0]
    info = {}
    for _, r in uni.iterrows():
        info[str(r["债券代码"])] = {
            "name": r["债券简称"], "stk": _stk_ts(r["正股代码"]),
            "cvt": float(r["转股价"]),
            "rating": str(r.get("信用评级", "")).strip(),
            "size": float(r["发行规模"]) if r["发行规模"] == r["发行规模"] else 0.0,
        }

    # 载入每债日线
    cb_daily = {}
    for fp in glob.glob(os.path.join(CB_DIR, "daily", "*.csv")):
        code = os.path.splitext(os.path.basename(fp))[0]
        if code not in info:
            continue
        try:
            d = pd.read_csv(fp)
            if "date" not in d or "close" not in d or d.empty:
                continue
            d["dn"] = d["date"].astype(str).str.replace("-", "")
            cb_daily[code] = dict(zip(d["dn"], d["close"].astype(float)))
        except Exception:
            continue
    stk_needed = {info[c]["stk"] for c in cb_daily}
    stk = asyncio.run(load_stock_closes(stk_needed))
    print(f"转债 {len(cb_daily)} 只有日线 / 正股 {len(stk)} 只命中 PG", flush=True)

    # 全交易日（用转债日期并集，按月取月末）
    alld = sorted({dn for m in cb_daily.values() for dn in m})
    alld = [d for d in alld if d >= "20180101"]
    # 月末再平衡日
    rebal = []
    cur_m = None
    for i, d in enumerate(alld):
        m = d[:6]
        if cur_m is None:
            cur_m = m
        elif m != cur_m:
            rebal.append(alld[i - 1])
            cur_m = m
    rebal.append(alld[-1])

    def dual_low(code, dn):
        """返回 (双低, 价格) 或 None"""
        px = cb_daily[code].get(dn)
        if not px or px <= 0:
            return None
        st = stk.get(info[code]["stk"], {}).get(dn)
        if not st or st <= 0:
            return None
        cv = 100.0 / info[code]["cvt"] * st        # 转股价值
        if cv <= 0:
            return None
        prem = px / cv - 1.0                         # 转股溢价率
        return px + prem * 100.0, px

    def passes(code, px):
        v = info[code]
        if v["rating"] not in RATING_OK:
            return False
        if v["size"] < MIN_SIZE:
            return False
        if px > PRICE_CAP or px < PRICE_FLOOR:
            return False
        return True

    # 月度等权轮动回测（持有到下个再平衡日）
    def run(dates_seg, label):
        reb = [d for d in rebal if dates_seg[0] <= d <= dates_seg[-1]]
        if len(reb) < 3:
            return None
        equity = 1.0
        curve = [equity]
        held = []          # [(code, entry_px)]
        for k in range(len(reb) - 1):
            d0, d1 = reb[k], reb[k + 1]
            # 选 双低 最低 N
            cand = []
            for code in cb_daily:
                dl = dual_low(code, d0)
                if dl is None:
                    continue
                if not passes(code, dl[1]):
                    continue
                cand.append((dl[0], code, dl[1]))
            cand.sort(key=lambda x: x[0])
            pick = [(c, px) for _, c, px in cand[:TOP_N]]
            if not pick:
                curve.append(equity)
                continue
            # 该期等权收益（用各债 d0->d1 收盘）
            rets = []
            for code, p0 in pick:
                p1 = cb_daily[code].get(d1)
                if not p1 or p1 <= 0:
                    # 期间退市/停牌：用最后可得价近似
                    seg = [v for dd, v in cb_daily[code].items()
                           if d0 < dd <= d1]
                    p1 = seg[-1] if seg else p0
                rets.append((p1 - p0) / p0)
            gross = float(np.mean(rets)) if rets else 0.0
            equity *= (1 + gross - CB_RT_COST)       # 每月换仓计一次双边成本
            curve.append(equity)
        total = (equity - 1) * 100
        arr = np.array(curve)
        rets = np.diff(arr) / arr[:-1]
        sharpe = (rets.mean() / rets.std() * np.sqrt(12)) if rets.std() > 0 else 0.0
        peak = np.maximum.accumulate(arr)
        mdd = float(((peak - arr) / peak).max()) * 100
        n_years = len(reb) / 12.0
        ann = ((equity ** (1 / n_years) - 1) * 100) if n_years > 0 and equity > 0 else 0.0
        return total, ann, sharpe, mdd, len(reb)

    def bench(dates_seg):
        """转债等权买入持有(信用过滤后池子)"""
        reb = [d for d in rebal if dates_seg[0] <= d <= dates_seg[-1]]
        if len(reb) < 2:
            return float("nan")
        d0, d1 = reb[0], reb[-1]
        rs = []
        for code in cb_daily:
            p0 = cb_daily[code].get(d0)
            p1 = cb_daily[code].get(d1)
            if p0 and p1 and p0 > 0 and passes(code, p0):
                rs.append((p1 - p0) / p0)
        return float(np.mean(rs)) * 100 if rs else float("nan")

    years = sorted({d[:4] for d in alld})
    print("\n年 | 转债等权基准% | 双低+信用过滤策略 (总/年化/夏普/回撤/月数)", flush=True)
    for y in years:
        seg = [d for d in alld if d[:4] == y]
        if len(seg) < 40:
            continue
        r = run(seg, y)
        if r:
            print(f"[{y}] 基准 {bench(seg):+6.1f}% | 策略 {r[0]:+7.1f}% "
                  f"年化{r[1]:+6.1f}% 夏普{r[2]:.2f} 回撤{r[3]:.1f}% ({r[4]}月)",
                  flush=True)
    full = run(alld, "FULL")
    print(f"[FULL] 基准 {bench(alld):+6.1f}% | 策略 {full[0]:+7.1f}% "
          f"年化{full[1]:+6.1f}% 夏普{full[2]:.2f} 回撤{full[3]:.1f}% ({full[4]}月)",
          flush=True)
    # 2024H2 尾部压测
    h2 = [d for d in alld if "20240701" <= d <= "20241231"]
    if len(h2) > 30:
        r = run(h2, "2024H2")
        print(f"[2024H2压测] 基准 {bench(h2):+.1f}% | 策略 {r[0]:+.1f}% "
              f"回撤{r[3]:.1f}%", flush=True)
    print("\n局限：转股价用当前值(下修未还原)/评级为当前快照→方向性可信非精确；"
          "以逐年样本外是否打不倒为准。", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
