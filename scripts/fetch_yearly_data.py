"""
Tushare 批量拉取过去一年全A股日线数据

策略：按交易日拉取（每次获取当日所有股票），约250次调用完成全年数据
输出：data/yearly/ 目录下按日期存储 CSV，最终合并为一个完整文件
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import tushare as ts

# ── 配置 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings

OUTPUT_DIR = PROJECT_ROOT / "data" / "yearly"
MERGED_FILE = OUTPUT_DIR / "all_stocks_daily.csv"
STOCK_LIST_FILE = OUTPUT_DIR / "stock_list.csv"

# tushare 限流：普通用户约 200次/分钟，每次间隔 0.3s 比较安全
API_CALL_INTERVAL = 0.35

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def init_api():
    """初始化 tushare pro API"""
    token = settings.TUSHARE_TOKEN
    if not token:
        logger.error("TUSHARE_TOKEN 未配置，请在 .env 中设置")
        sys.exit(1)
    ts.set_token(token)
    return ts.pro_api()


def get_trade_calendar(api, start_date: str, end_date: str) -> list[str]:
    """获取交易日历，返回交易日列表"""
    logger.info(f"获取交易日历: {start_date} ~ {end_date}")
    df = api.trade_cal(
        exchange="SSE",
        start_date=start_date,
        end_date=end_date,
        is_open="1",
    )
    dates = sorted(df["cal_date"].tolist())
    logger.info(f"共 {len(dates)} 个交易日")
    return dates


def fetch_stock_list(api) -> pd.DataFrame:
    """获取当前全部A股列表"""
    logger.info("获取A股股票列表...")
    df = api.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date",
    )
    logger.info(f"共 {len(df)} 只股票")
    return df


def fetch_daily_by_date(api, trade_date: str) -> pd.DataFrame | None:
    """拉取某个交易日全部股票的日线数据"""
    try:
        df = api.daily(trade_date=trade_date)
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        logger.warning(f"拉取 {trade_date} 失败: {e}")
        return None


def fetch_adj_factor(api, trade_date: str) -> pd.DataFrame | None:
    """拉取复权因子"""
    try:
        df = api.adj_factor(trade_date=trade_date)
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    api = init_api()

    # 时间范围：过去一年
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    logger.info(f"数据范围: {start_date} ~ {end_date}")

    # 1. 拉取股票列表
    stock_df = fetch_stock_list(api)
    stock_df.to_csv(STOCK_LIST_FILE, index=False, encoding="utf-8-sig")
    logger.info(f"股票列表已保存: {STOCK_LIST_FILE}")
    time.sleep(API_CALL_INTERVAL)

    # 2. 获取交易日历
    trade_dates = get_trade_calendar(api, start_date, end_date)
    time.sleep(API_CALL_INTERVAL)

    # 3. 检查已下载的日期（支持断点续传）
    downloaded = set()
    for f in OUTPUT_DIR.glob("daily_*.csv"):
        date_str = f.stem.replace("daily_", "")
        downloaded.add(date_str)

    remaining = [d for d in trade_dates if d not in downloaded]
    logger.info(f"已下载 {len(downloaded)} 天，剩余 {len(remaining)} 天")

    # 4. 按交易日逐日拉取
    all_frames = []
    failed_dates = []

    for i, trade_date in enumerate(remaining):
        logger.info(f"[{i+1}/{len(remaining)}] 拉取 {trade_date} ...")

        df = fetch_daily_by_date(api, trade_date)
        if df is None:
            failed_dates.append(trade_date)
            logger.warning(f"  {trade_date} 无数据，跳过")
            time.sleep(API_CALL_INTERVAL)
            continue

        # 保存单日文件（断点续传用）
        day_file = OUTPUT_DIR / f"daily_{trade_date}.csv"
        df.to_csv(day_file, index=False)
        all_frames.append(df)

        logger.info(f"  {trade_date}: {len(df)} 条记录")
        time.sleep(API_CALL_INTERVAL)

    # 5. 合并所有数据（流式写入，避免内存溢出）
    logger.info("合并全部数据...")

    all_files = sorted(OUTPUT_DIR.glob("daily_*.csv"))
    if all_files:
        header_written = False
        total_rows = 0

        for f in all_files:
            chunk = pd.read_csv(f)
            chunk = chunk.rename(columns={"trade_date": "date", "vol": "volume"})
            chunk.to_csv(
                MERGED_FILE,
                mode="a" if header_written else "w",
                header=not header_written,
                index=False,
                encoding="utf-8-sig",
            )
            header_written = True
            total_rows += len(chunk)

        logger.info(f"合并完成: {total_rows} 条记录, 保存至 {MERGED_FILE}")
    else:
        logger.warning("没有数据文件可合并")

    # 6. 汇总
    if failed_dates:
        logger.warning(f"失败日期 ({len(failed_dates)}): {failed_dates}")
    logger.info("全部完成!")


if __name__ == "__main__":
    main()
