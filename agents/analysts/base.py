"""
分析师 Agent 基类
"""

from abc import ABC, abstractmethod
from typing import Dict


class BaseAnalyst(ABC):
    """分析师 Agent 基类 - 所有分析师继承此类"""

    name: str = ""
    description: str = ""

    def __init__(self, llm, data_interface):
        self.llm = llm
        self.data = data_interface

    @abstractmethod
    async def analyze(self, stock_code: str, date: str) -> str:
        """执行分析，返回分析报告文本"""
        pass

    def build_prompt(self, stock_code: str, data: Dict) -> str:
        """构建 LLM 提示词 - 子类可覆盖"""
        return f"请分析股票 {stock_code} 的相关数据: {data}"
