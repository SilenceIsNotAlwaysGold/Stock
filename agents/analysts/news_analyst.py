"""
新闻分析师 Agent - 财经新闻摘要和情绪判断
"""

import logging
from typing import Dict

from agents.analysts.base import BaseAnalyst

logger = logging.getLogger(__name__)

NEWS_PROMPT = """你是一位专业的 A 股财经新闻分析师。请基于以下股票信息进行新闻面分析。

## 股票信息
- 股票代码: {stock_code}
- 分析日期: {date}

## 近期市场数据
{data}

## 分析要求
1. 基于价格走势推断可能的新闻面影响
2. 分析近期是否有异常波动（可能对应重大事件）
3. 判断市场对该股票的情绪倾向
4. 评估潜在的政策风险和行业利好

## 输出格式
请用中文输出结构化分析报告，包含：
- 新闻面综合评分（1-10分）
- 情绪判断（积极/中性/消极）
- 潜在风险提示
- 关注要点
"""


class NewsAnalyst(BaseAnalyst):
    name = "news_analyst"
    description = "新闻分析师 - 财经新闻摘要和情绪判断"

    async def analyze(self, stock_code: str, date: str) -> str:
        from datetime import datetime, timedelta

        end_date = date
        start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=30)
        start_date = start_dt.strftime("%Y-%m-%d")

        df = await self.data.get_daily_bars(stock_code, start_date, end_date)

        data_summary = self._build_data_summary(df)
        prompt = NEWS_PROMPT.format(stock_code=stock_code, date=date, data=data_summary)

        messages = [
            {"role": "system", "content": "你是专业的 A 股财经新闻分析师。"},
            {"role": "user", "content": prompt},
        ]
        return await self.llm.chat(messages, temperature=0.4)

    def _build_data_summary(self, df) -> str:
        if df is None or len(df) == 0:
            return "无数据"
        recent = df.tail(10)
        # 检测异常波动
        daily_returns = df["close"].pct_change().dropna()
        max_gain = daily_returns.max() * 100
        max_loss = daily_returns.min() * 100
        return (
            f"近10日行情:\n{recent[['date','close','volume']].to_string(index=False)}\n"
            f"最大单日涨幅: {max_gain:.2f}%\n"
            f"最大单日跌幅: {max_loss:.2f}%\n"
            f"近10日涨跌幅: {((float(recent.iloc[-1]['close'])/float(recent.iloc[0]['close']))-1)*100:.2f}%"
        )
