"""AESE 自进化引擎 API"""

import logging
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter

from agents.llm.factory import create_llm
from engine.registry import StrategyRegistry
from app.routers.strategy_health import (
    _health_cache,
    _default_health,
    calculate_health_score,
    grade_strategy,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 进化历史
_evolution_history: List[Dict] = []

# 策略权重
_strategy_weights: Dict[str, float] = {}

AESE_PROMPT = """你是 AESE（自适应进化策略引擎）的 AI 分析师。
请基于以下策略健康度数据，给出权重调整建议。

## 当前策略状态
{strategy_data}

## 要求
1. 分析每个策略的表现趋势
2. 建议权重调整（总权重 = 1.0）
3. 标记需要淘汰的策略（连续表现差）
4. 给出调整理由

请用 JSON 格式输出：
{{"adjustments": [{{"name": "策略名", "weight": 0.2, "action": "keep/boost/reduce/retire", "reason": "理由"}}]}}
"""


@router.get("/status")
async def aese_status():
    """获取 AESE 状态"""
    StrategyRegistry.auto_discover()
    strategies = StrategyRegistry.all()

    status = []
    for name, cls in strategies.items():
        health = _health_cache.get(name, _default_health(name))
        weight = _strategy_weights.get(name, 1.0 / max(len(strategies), 1))
        status.append(
            {
                "name": name,
                "weight": round(weight, 3),
                "health_score": health["score"],
                "grade": health["grade"],
            }
        )

    return {
        "strategies": status,
        "total_evaluations": len(_evolution_history),
        "last_evaluation": (
            _evolution_history[-1]["timestamp"] if _evolution_history else None
        ),
    }


@router.post("/evaluate")
async def aese_evaluate():
    """触发 AESE 评估"""
    StrategyRegistry.auto_discover()
    strategies = StrategyRegistry.all()

    strategy_data = []
    for name, cls in strategies.items():
        health = _health_cache.get(name, _default_health(name))
        weight = _strategy_weights.get(name, 1.0 / max(len(strategies), 1))
        strategy_data.append(
            {
                "name": name,
                "category": cls.category,
                "weight": weight,
                "health_score": health["score"],
                "grade": health["grade"],
                "win_rate": health["win_rate"],
            }
        )

    # AI 分析
    try:
        llm = create_llm()
        prompt = AESE_PROMPT.format(strategy_data=strategy_data)
        messages = [
            {"role": "system", "content": "你是 AESE 自进化引擎的 AI 分析师。"},
            {"role": "user", "content": prompt},
        ]
        ai_response = await llm.chat(messages, temperature=0.2)
    except Exception as e:
        logger.error(f"AESE AI evaluation failed: {e}")
        ai_response = "AI 评估失败，使用默认权重"

    # 记录评估历史
    record = {
        "timestamp": datetime.now().isoformat(),
        "strategy_data": strategy_data,
        "ai_response": ai_response,
    }
    _evolution_history.append(record)

    return {
        "status": "evaluated",
        "ai_analysis": ai_response,
        "strategies": strategy_data,
    }


@router.get("/history")
async def aese_history(limit: int = 10):
    """获取进化历史"""
    return _evolution_history[-limit:]
