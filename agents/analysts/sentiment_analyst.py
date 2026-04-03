"""
市场情绪分析师 Agent - 涨跌比、涨停数、情绪指标
"""

import logging
from typing import Dict

from agents.analysts.base import BaseAnalyst

logger = logging.getLogger(__name__)

SENTIMENT_PROMPT = """你是一位专业的 A 股市场情绪分析师。请基于以下数据分析股票 {stock_code} 的市场情绪。

## 分析数据
{data}

## 分析要求
1. 量价关系分析（成交量变化趋势，是否有异常放量/缩量）
2. 换手率分析（活跃度判断）
3. 波动率分析（近期波动是否加大）
4. 资金流向推断（基于量价关系）
5. 市场情绪综合判断

## 输出格式
请用中文输出结构化分析报告，包含：
- 情绪综合评分（1-10分，10为极度乐观）
- 市场情绪状态（恐慌/谨慎/中性/乐观/狂热）
- 资金面判断
- 风险提示
"""


class SentimentAnalyst(BaseAnalyst):
    name = "sentiment_analyst"
    description = "市场情绪分析师 - 量价关系、换手率、波动率"

    async def analyze(self, stock_code: str, date: str) -> str:
        from datetime import datetime, timedelta

        end_date = date
        start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=60)
        start_date = start_dt.strftime("%Y-%m-%d")

        df = await self.data.get_daily_bars(stock_code, start_date, end_date)

        data_summary = self._build_data_summary(df)
        prompt = self.build_prompt(stock_code, data_summary)

        messages = [
            {"role": "system", "content": "你是专业的 A 股市场情绪分析师。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.3)

    def build_prompt(self, stock_code: str, data: Dict) -> str:
        return SENTIMENT_PROMPT.format(stock_code=stock_code, data=data)

    def _build_data_summary(self, df) -> Dict:
        if df is None or len(df) == 0:
            return {"error": "无数据"}
        recent = df.tail(20)
        daily_returns = df["close"].pct_change().dropna()
        return {
            "近20日平均成交量": float(recent["volume"].mean()),
            "近5日平均成交量": float(df.tail(5)["volume"].mean()),
            "量比(5日/20日)": round(
                float(df.tail(5)["volume"].mean())
                / max(float(recent["volume"].mean()), 1),
                2,
            ),
            "近20日波动率": round(float(daily_returns.tail(20).std()) * 100, 2),
            "近5日波动率": round(float(daily_returns.tail(5).std()) * 100, 2),
            "平均换手率": (
                round(float(recent["turnover_rate"].mean()), 2)
                if "turnover_rate" in recent.columns
                else 0
            ),
            "上涨天数": int((daily_returns.tail(20) > 0).sum()),
            "下跌天数": int((daily_returns.tail(20) < 0).sum()),
            "最大连涨天数": self._max_consecutive(daily_returns.tail(20) > 0),
            "最大连跌天数": self._max_consecutive(daily_returns.tail(20) < 0),
        }

    @staticmethod
    def _max_consecutive(series) -> int:
        max_count = count = 0
        for v in series:
            if v:
                count += 1
                max_count = max(max_count, count)
            else:
                count = 0
        return max_count
