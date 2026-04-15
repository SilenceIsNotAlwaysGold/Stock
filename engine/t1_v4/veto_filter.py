"""
T1 v4 一票否决过滤器

在评分之前先过滤掉不合格的股票，任一条件触发即排除。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class VetoResult:
    """否决过滤结果"""

    ts_code: str
    passed: bool = True
    reject_reasons: List[str] = field(default_factory=list)


class VetoFilter:
    """
    一票否决过滤器

    7条否决规则：
    1. ST 或 *ST 股票
    2. 上市不足 60 天（次新股）
    3. 板块权限过滤 — 默认排除科创板(688)/创业板(300)/北交所(8/4)，可配置
    4. 当日涨停（无法买入）
    5. 当日跌停（趋势极弱）
    6. 停牌
    7. 近 5 日有涨跌停（波动过大）
    """

    # 板块代码前缀 → 可读名称
    PREFIX_LABELS = {
        "688": "科创板",
        "300": "创业板",
        "8": "北交所",
        "4": "北交所",
    }

    DEFAULT_PARAMS = {
        "min_list_days": 60,
        "limit_up_pct": 0.098,    # 主板涨停阈值 9.8%（留余量）
        "limit_down_pct": -0.098,
        "recent_limit_days": 5,   # 检查近 N 日是否有涨跌停
        "excluded_prefixes": ["688", "300", "8", "4"],  # 排除的板块前缀（可配置）
    }

    def __init__(self, **overrides):
        self.params = {**self.DEFAULT_PARAMS, **overrides}

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _calc_change_pct(self, df: pd.DataFrame, idx: int) -> Optional[float]:
        """计算 df 第 idx 行的涨跌幅。优先使用 pre_close 列，否则用前一行 close。"""
        row = df.iloc[idx]
        close = float(row["close"])

        if "pre_close" in df.columns:
            pre_close = float(row["pre_close"])
        else:
            if idx == 0:
                return None  # 没有前一日数据
            pre_close = float(df.iloc[idx - 1]["close"])

        if pre_close <= 0:
            return None
        return (close - pre_close) / pre_close

    def _is_limit_event(self, change_pct: Optional[float]) -> Tuple[bool, bool]:
        """返回 (is_limit_up, is_limit_down)，change_pct 为 None 时均返回 False。"""
        if change_pct is None:
            return False, False
        is_up = change_pct >= self.params["limit_up_pct"]
        is_down = change_pct <= self.params["limit_down_pct"]
        return is_up, is_down

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def check(
        self,
        ts_code: str,
        stock_name: str,
        daily_df: pd.DataFrame,
        list_date: Optional[str] = None,
        is_suspended: bool = False,
        check_date: Optional[str] = None,
    ) -> VetoResult:
        """
        检查单只股票是否被否决。

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            stock_name: 股票名称
            daily_df: 日线数据，至少最近5天，含 date/open/high/low/close/pre_close 列。
                      如果没有 pre_close，用前一天 close 计算。行按日期升序排列。
            list_date: 上市日期 "YYYYMMDD" 或 "YYYY-MM-DD"
            is_suspended: 是否停牌
            check_date: 检查的日期，None 则用 daily_df 最后一行

        Returns:
            VetoResult
        """
        result = VetoResult(ts_code=ts_code)

        # ---- 规则 1：ST / *ST ----------------------------------------
        if "ST" in stock_name.upper():
            result.passed = False
            result.reject_reasons.append("ST或*ST股票")
            return result

        # ---- 规则 2：上市不足 60 天 -----------------------------------
        if list_date:
            try:
                ld = datetime.strptime(list_date.replace("-", ""), "%Y%m%d")
                min_days = self.params["min_list_days"]
                if (datetime.now() - ld).days < min_days:
                    result.passed = False
                    result.reject_reasons.append(f"上市不足{min_days}天（次新股）")
                    return result
            except (ValueError, TypeError):
                pass  # 日期格式异常时跳过此规则

        # ---- 规则 3：板块权限过滤（科创板/创业板/北交所）--------------
        code = ts_code.split(".")[0] if "." in ts_code else ts_code
        for prefix in self.params["excluded_prefixes"]:
            if code.startswith(prefix):
                label = self.PREFIX_LABELS.get(prefix, prefix)
                result.passed = False
                result.reject_reasons.append(f"{label}（{prefix}xxx）")
                return result

        # ---- 规则 6：停牌（先判停牌，后续规则需要数据）----------------
        if is_suspended:
            result.passed = False
            result.reject_reasons.append("当日停牌")
            return result

        # ---- DataFrame 基础校验 --------------------------------------
        if daily_df is None or daily_df.empty:
            result.passed = False
            result.reject_reasons.append("日线数据为空，无法判断")
            return result

        required_cols = {"close"}
        missing = required_cols - set(daily_df.columns)
        if missing:
            result.passed = False
            result.reject_reasons.append(f"日线数据缺少列：{missing}")
            return result

        df = daily_df.copy()

        # 定位"当日"行：check_date 指定则找对应行，否则取最后一行
        if check_date is not None and "date" in df.columns:
            # 统一格式后匹配
            norm_date = check_date.replace("-", "")
            df["_date_norm"] = df["date"].astype(str).str.replace("-", "", regex=False)
            matched = df[df["_date_norm"] == norm_date]
            if matched.empty:
                result.passed = False
                result.reject_reasons.append(f"check_date {check_date} 在日线数据中不存在")
                return result
            today_idx = matched.index.get_loc(matched.index[-1])
            # 将 iloc 索引转为整数位置
            today_pos = df.index.get_loc(matched.index[-1])
        else:
            today_pos = len(df) - 1

        # ---- 规则 4 & 5：当日涨停 / 跌停 ----------------------------
        today_pct = self._calc_change_pct(df, today_pos)
        is_up_today, is_down_today = self._is_limit_event(today_pct)

        if is_up_today:
            result.passed = False
            pct_str = f"{today_pct * 100:.2f}%" if today_pct is not None else "N/A"
            result.reject_reasons.append(f"当日涨停（涨幅 {pct_str}，无法买入）")
            return result

        if is_down_today:
            result.passed = False
            pct_str = f"{today_pct * 100:.2f}%" if today_pct is not None else "N/A"
            result.reject_reasons.append(f"当日跌停（跌幅 {pct_str}，趋势极弱）")
            return result

        # ---- 规则 7：近 N 日有涨跌停 ---------------------------------
        recent_n = self.params["recent_limit_days"]
        # 取今天之前的 recent_n 天（不含今天）
        start_pos = max(0, today_pos - recent_n)
        end_pos = today_pos  # exclusive

        # 需要 pre_close 或至少两行才能计算涨跌幅
        if end_pos > start_pos:
            for i in range(start_pos, end_pos):
                # 计算第 i 行时需要第 i-1 行（或 pre_close），确保 i >= 1
                if i == 0 and "pre_close" not in df.columns:
                    continue
                pct = self._calc_change_pct(df, i)
                is_up, is_down = self._is_limit_event(pct)
                if is_up or is_down:
                    event = "涨停" if is_up else "跌停"
                    result.passed = False
                    pct_str = f"{pct * 100:.2f}%" if pct is not None else "N/A"
                    result.reject_reasons.append(
                        f"近{recent_n}日内有{event}（第{today_pos - i}日前，涨跌幅 {pct_str}）"
                    )
                    return result

        return result

    def batch_filter(
        self,
        stock_list: pd.DataFrame,
        daily_data: Dict[str, pd.DataFrame],
        suspended_set: Optional[set] = None,
    ) -> Tuple[List[str], List[VetoResult]]:
        """
        批量过滤。

        Args:
            stock_list: 含 ts_code, name, list_date 列的 DataFrame
            daily_data: ts_code -> daily_df 的字典
            suspended_set: 停牌股票集合（ts_code）

        Returns:
            (passed_codes, all_results)
        """
        if suspended_set is None:
            suspended_set = set()

        passed_codes: List[str] = []
        all_results: List[VetoResult] = []

        if stock_list is None or stock_list.empty:
            return passed_codes, all_results

        for _, row in stock_list.iterrows():
            ts_code = str(row.get("ts_code", ""))
            name = str(row.get("name", ""))
            list_date = row.get("list_date", None)
            if list_date is not None:
                list_date = str(list_date)

            df = daily_data.get(ts_code)
            is_suspended = ts_code in suspended_set

            result = self.check(
                ts_code=ts_code,
                stock_name=name,
                daily_df=df if df is not None else pd.DataFrame(),
                list_date=list_date,
                is_suspended=is_suspended,
            )
            all_results.append(result)
            if result.passed:
                passed_codes.append(ts_code)

        return passed_codes, all_results
