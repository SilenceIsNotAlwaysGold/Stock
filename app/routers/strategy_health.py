"""策略健康度 API"""

import logging
from typing import Dict, List

from fastapi import APIRouter

from engine.registry import StrategyRegistry

logger = logging.getLogger(__name__)
router = APIRouter()

# 模拟健康度数据（生产环境从 PG 读取历史信号表现）
_health_cache: Dict[str, Dict] = {}


@router.get("/list")
async def strategy_health_list():
    """获取所有策略健康度"""
    StrategyRegistry.auto_discover()
    strategies = StrategyRegistry.all()

    results = []
    for name, cls in strategies.items():
        health = _health_cache.get(name, _default_health(name))
        results.append(
            {
                "name": name,
                "description": cls.description,
                "category": cls.category,
                **health,
            }
        )
    return results


@router.get("/{strategy_name}")
async def strategy_health_detail(strategy_name: str):
    """获取单个策略健康度"""
    StrategyRegistry.auto_discover()
    cls = StrategyRegistry.get(strategy_name)
    if not cls:
        return {"error": f"Strategy {strategy_name} not found"}

    health = _health_cache.get(strategy_name, _default_health(strategy_name))
    return {
        "name": strategy_name,
        "description": cls.description,
        "category": cls.category,
        "params": cls.default_params,
        **health,
    }


def _default_health(name: str) -> Dict:
    """默认健康度（无历史数据时）"""
    return {
        "score": 50.0,
        "grade": "Experimental",
        "win_rate": 0.0,
        "avg_return": 0.0,
        "sharpe_ratio": 0.0,
        "stability": 0.0,
        "total_signals": 0,
        "last_evaluated": None,
    }


def calculate_health_score(
    win_rate: float,
    avg_return: float,
    sharpe: float,
    stability: float,
) -> float:
    """计算健康度评分"""
    score = (
        win_rate * 0.3
        + min(avg_return * 10, 30) * 0.3
        + min(sharpe, 3) / 3 * 100 * 0.2
        + stability * 100 * 0.2
    )
    return max(0, min(100, score))


def grade_strategy(score: float) -> str:
    """策略分级"""
    if score >= 75:
        return "Core"
    elif score >= 55:
        return "Plus"
    elif score >= 35:
        return "Experimental"
    return "Problematic"
