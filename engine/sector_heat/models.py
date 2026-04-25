from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SectorScore:
    name: str
    code: str
    heat_score: float           # 综合热度 0-100

    # 分项得分
    price_score: float          # 价格动量 0-35
    fund_score: float           # 资金动向 0-35
    momentum_score: float       # 热度加速 0-30

    # 原始数据
    today_change: float         # 今日涨跌幅%
    period_return: float        # 窗口期累计涨幅% (无历史数据时 = today_change)
    net_inflow: float           # 今日主力净流入(亿元)
    inflow_ratio: float         # 净流入/总流入 (0-1)
    up_ratio: float             # 上涨家数/(上涨+下跌)
    turnover_rate: float        # 换手率%
    limit_up_in_period: int     # 窗口期涨停次数 (无历史时 = 0)
    acceleration: float         # 加速度 近3日/全程 (无历史时 = 0.5)
    trend: str                  # 升温 / 高位 / 退烧 / 低迷
    leader_stock: str           # 领涨股名称
    leader_change: float        # 领涨股涨跌幅%
    stock_count: int            # 板块成分股数量


@dataclass
class StockPick:
    ts_code: str
    name: str
    sector: str
    role: str                   # 龙头 / 次龙头 / 潜力股
    score: float
    today_change: float
    turnover_rate: float
    reason: str


@dataclass
class LLMAnalysis:
    sector_name: str
    catalyst: str               # 核心催化剂
    stage: str                  # 启动期 / 加速期 / 高位震荡 / 退潮期
    pick_direction: str         # 选股方向建议
    risks: str                  # 主要风险
    summary: str                # 一句话总结


@dataclass
class SectorRecommendation:
    sector: SectorScore
    stocks: List[StockPick] = field(default_factory=list)
    analysis: Optional[LLMAnalysis] = None


@dataclass
class SectorReport:
    generated_at: str
    window_days: int
    recommendations: List[SectorRecommendation]
