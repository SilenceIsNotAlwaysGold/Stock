"""
基本面分析师 Agent - PE/PB/ROE、财务数据
"""

import logging
from typing import Dict

from agents.analysts.base import BaseAnalyst

logger = logging.getLogger(__name__)

FUNDAMENTAL_PROMPT = """你是一位专业的 A 股基本面分析师。请基于以下数据对股票 {stock_code} 进行基本面分析。

## 分析数据
{data}

## 分析要求
1. 估值分析（当前价格相对于历史估值水平）
2. 成长性分析（近期涨跌趋势、量价关系）
3. 盈利质量分析（基于价格走势推断市场对盈利的预期）
4. 行业对比（该股票在同类中的表现）

## 输出格式
请用中文输出结构化分析报告，包含：
- 基本面综合评分（1-10分）
- 估值判断（低估/合理/高估）
- 成长性评价
- 投资建议
"""


class FundamentalAnalyst(BaseAnalyst):
    name = "fundamental_analyst"
    description = "基本面分析师 - 估值、成长性、盈利质量"

    async def analyze(self, stock_code: str, date: str) -> str:
        from datetime import datetime, timedelta

        end_date = date
        start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=365)
        start_date = start_dt.strftime("%Y-%m-%d")

        df = await self.data.get_daily_bars(stock_code, start_date, end_date)

        data_summary = self._build_data_summary(df)
        prompt = self.build_prompt(stock_code, data_summary)

        messages = [
            {"role": "system", "content": "你是专业的 A 股基本面分析师。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.3)

    def build_prompt(self, stock_code: str, data: Dict) -> str:
        return FUNDAMENTAL_PROMPT.format(stock_code=stock_code, data=data)

    def _build_data_summary(self, df) -> Dict:
        if df is None or len(df) == 0:
            return {"error": "无数据"}
        latest = df.iloc[-1]
        first = df.iloc[0]
        return {
            "最新收盘价": float(latest["close"]),
            "年初价格": float(first["close"]),
            "年度涨跌幅": round(
                (float(latest["close"]) / float(first["close"]) - 1) * 100, 2
            ),
            "52周最高": float(df["high"].max()),
            "52周最低": float(df["low"].min()),
            "日均成交量": float(df["volume"].mean()),
            "日均成交额": float(df["amount"].mean()),
            "近30日均价": float(df.tail(30)["close"].mean()),
            "数据天数": len(df),
        }
