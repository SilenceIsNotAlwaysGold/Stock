"""
技术面分析师 Agent - K线形态、均线、MACD、成交量
"""

import logging
from typing import Dict

from agents.analysts.base import BaseAnalyst

logger = logging.getLogger(__name__)

MARKET_PROMPT = """你是一位专业的 A 股技术面分析师。请基于以下数据对股票 {stock_code} 进行技术分析。

## 分析数据
{data}

## 分析要求
1. K线形态分析（近期是否出现典型形态：锤子线、十字星、吞没等）
2. 均线系统分析（MA5/MA10/MA20/MA60 排列状态，金叉/死叉）
3. MACD 指标分析（DIF/DEA 位置，柱状图变化趋势）
4. 成交量分析（量能变化，是否放量/缩量，量价配合）
5. 支撑位和压力位判断

## 输出格式
请用中文输出结构化分析报告，包含：
- 技术面综合评分（1-10分）
- 短期趋势判断（看多/看空/震荡）
- 关键技术位（支撑/压力）
- 操作建议
"""


class MarketAnalyst(BaseAnalyst):
    name = "market_analyst"
    description = "技术面分析师 - K线、均线、MACD、成交量"

    async def analyze(self, stock_code: str, date: str) -> str:
        # 获取近 60 个交易日数据
        from datetime import datetime, timedelta

        end_date = date
        start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=90)
        start_date = start_dt.strftime("%Y-%m-%d")

        df = await self.data.get_daily_bars(stock_code, start_date, end_date)

        data_summary = self._build_data_summary(df)
        prompt = self.build_prompt(stock_code, data_summary)

        messages = [
            {"role": "system", "content": "你是专业的 A 股技术面分析师。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.3)

    def build_prompt(self, stock_code: str, data: Dict) -> str:
        return MARKET_PROMPT.format(stock_code=stock_code, data=data)

    def _build_data_summary(self, df) -> Dict:
        if df is None or len(df) == 0:
            return {"error": "无数据"}
        recent = df.tail(20)
        latest = df.iloc[-1]
        return {
            "最新收盘价": float(latest["close"]),
            "近20日最高": float(recent["high"].max()),
            "近20日最低": float(recent["low"].min()),
            "近5日均价": float(df.tail(5)["close"].mean()),
            "近10日均价": float(df.tail(10)["close"].mean()),
            "近20日均价": float(recent["close"].mean()),
            "近5日均量": float(df.tail(5)["volume"].mean()),
            "近20日均量": float(recent["volume"].mean()),
            "最新成交量": float(latest["volume"]),
            "近5日涨跌幅": (
                round(
                    (float(latest["close"]) / float(df.iloc[-6]["close"]) - 1) * 100,
                    2,
                )
                if len(df) >= 6
                else 0
            ),
            "近20日数据": recent[["date", "open", "high", "low", "close", "volume"]]
            .tail(10)
            .to_string(index=False),
        }
