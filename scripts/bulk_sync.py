"""
全市场日线数据批量同步脚本
按交易日批量拉取，每天一次请求拿到全市场 ~5000 只股票数据
用法：python3 scripts/bulk_sync.py [--days 30]
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime, timedelta, date
from decimal import Decimal

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text

from app.config import settings
from app.models.pg_models import Stock, DailyBar, Base

parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=30, help="同步最近N天")
args = parser.parse_args()

TOKEN = settings.TUSHARE_TOKEN
if not TOKEN:
    print("❌ TUSHARE_TOKEN 未配置，请在 .env 里设置")
    sys.exit(1)

import tushare as ts
ts.set_token(TOKEN)
api = ts.pro_api()


def _safe_str(val, default=""):
    if val is None or (isinstance(val, float) and val != val):
        return default
    return str(val)


async def main():
    engine = create_async_engine(settings.pg_dsn, pool_size=5, max_overflow=10)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        # 1. 同步股票列表
        print("📋 同步股票列表...", end=" ", flush=True)
        stock_df = await asyncio.to_thread(
            api.stock_basic, exchange="", list_status="L",
            fields="ts_code,name,industry,area,market,list_date",
        )
        new_stocks = 0
        for _, row in stock_df.iterrows():
            existing = await db.get(Stock, row["ts_code"])
            if not existing:
                db.add(Stock(
                    ts_code=row["ts_code"],
                    name=_safe_str(row["name"]),
                    industry=_safe_str(row.get("industry")),
                    area=_safe_str(row.get("area")),
                    market=_safe_str(row.get("market")),
                    list_date=(
                        datetime.strptime(row["list_date"], "%Y%m%d").date()
                        if row.get("list_date") else None
                    ),
                    is_active=True,
                ))
                new_stocks += 1
        await db.commit()
        print(f"✅ 共 {len(stock_df)} 只，新增 {new_stocks} 只")

        # 2. 获取交易日历
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=args.days + 15)
        print(f"📅 获取交易日历...", end=" ", flush=True)
        try:
            cal_df = await asyncio.to_thread(
                api.trade_cal,
                exchange="SSE",
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d"),
                fields="cal_date,is_open",
            )
            trade_dates = (
                cal_df[cal_df["is_open"] == 1]["cal_date"]
                .sort_values(ascending=False)
                .head(args.days)
                .tolist()
            )
        except Exception as e:
            print(f"降级自生成... ({e})")
            trade_dates = []
            cur = end_dt
            while len(trade_dates) < args.days:
                if cur.weekday() < 5:
                    trade_dates.append(cur.strftime("%Y%m%d"))
                cur -= timedelta(days=1)

        print(f"✅ {len(trade_dates)} 个交易日 ({trade_dates[-1]} ~ {trade_dates[0]})")

        # 3. 按日期批量拉取
        total_bars = 0
        errors = []
        for i, trade_date in enumerate(trade_dates):
            try:
                # OHLCV（全市场）
                day_df = await asyncio.to_thread(
                    api.daily,
                    trade_date=trade_date,
                    fields="ts_code,trade_date,open,high,low,close,vol,amount",
                )
                if day_df is None or day_df.empty:
                    print(f"  {trade_date}: 无数据（跳过）")
                    continue

                # 换手率（全市场）
                try:
                    basic_df = await asyncio.to_thread(
                        api.daily_basic,
                        trade_date=trade_date,
                        fields="ts_code,trade_date,turnover_rate,volume_ratio",
                    )
                    turnover_map = {}
                    if basic_df is not None and not basic_df.empty:
                        for _, br in basic_df.iterrows():
                            turnover_map[br["ts_code"]] = float(br.get("turnover_rate") or 0)
                except Exception:
                    turnover_map = {}

                td = datetime.strptime(trade_date, "%Y%m%d").date()
                rows = [
                    {
                        "ts_code":      b["ts_code"],
                        "trade_date":   td,
                        "open":         Decimal(str(b.get("open") or 0)),
                        "high":         Decimal(str(b.get("high") or 0)),
                        "low":          Decimal(str(b.get("low") or 0)),
                        "close":        Decimal(str(b.get("close") or 0)),
                        "volume":       int(b.get("vol") or 0),
                        "amount":       Decimal(str(b.get("amount") or 0)),
                        "turnover_rate": turnover_map.get(b["ts_code"], 0.0),
                    }
                    for _, b in day_df.iterrows()
                ]

                # 先确保当日所有 ts_code 在 stocks 表（历史含退市股 → 避免外键违例，
                # 同时保留退市股日线 = 消除回测幸存者偏差）
                day_codes = sorted({r["ts_code"] for r in rows})
                for s0 in range(0, len(day_codes), 2000):
                    cs = day_codes[s0: s0 + 2000]
                    sstmt = pg_insert(Stock).values(
                        [{"ts_code": c, "name": c, "is_active": False} for c in cs]
                    ).on_conflict_do_nothing(index_elements=["ts_code"])
                    await db.execute(sstmt)
                await db.commit()

                # 分批 upsert（每批 2000 行，避免超过 asyncpg 32767 参数限制）
                BATCH = 2000
                for start in range(0, len(rows), BATCH):
                    chunk = rows[start: start + BATCH]
                    stmt = pg_insert(DailyBar).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["ts_code", "trade_date"],
                        set_={"turnover_rate": stmt.excluded.turnover_rate},
                    )
                    await db.execute(stmt)
                await db.commit()
                total_bars += len(rows)

                print(f"  [{i+1:2d}/{len(trade_dates)}] {trade_date}: {len(rows):5d} 只 ✓")

                # 限流
                if (i + 1) % 5 == 0:
                    await asyncio.sleep(1.5)

            except Exception as e:
                # 关键：回滚以解除 session 事务污染，避免后续日期级联全挂
                try:
                    await db.rollback()
                except Exception:
                    pass
                errors.append(f"{trade_date}: {e}")
                print(f"  [{i+1:2d}/{len(trade_dates)}] {trade_date}: ❌ {str(e)[:120]}")
                await asyncio.sleep(2)

        print(f"\n✅ 同步完成！共写入 {total_bars:,} 条日线数据")
        if errors:
            print(f"⚠️  {len(errors)} 个日期失败: {errors[:3]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
