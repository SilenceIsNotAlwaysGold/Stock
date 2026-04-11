"""
quant-platform-v8 异常定义
"""


class AppError(Exception):
    """应用基础异常"""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class DataSourceError(AppError):
    """数据源异常"""

    def __init__(self, message: str):
        super().__init__(message, code="DATA_SOURCE_ERROR")


class LLMError(AppError):
    """LLM 调用异常"""

    def __init__(self, message: str):
        super().__init__(message, code="LLM_ERROR")


class StrategyError(AppError):
    """策略执行异常"""

    def __init__(self, message: str):
        super().__init__(message, code="STRATEGY_ERROR")


class PaperTradingError(AppError):
    """模拟盘异常"""

    def __init__(self, message: str):
        super().__init__(message, code="PAPER_TRADING_ERROR")


class T1StrategyError(AppError):
    """T+1 策略异常"""

    def __init__(self, message: str):
        super().__init__(message, code="T1_STRATEGY_ERROR")


class DataValidationError(AppError):
    """数据验证异常"""

    def __init__(self, message: str = "数据格式或内容不符合要求"):
        super().__init__(message, code="DATA_VALIDATION_ERROR")
