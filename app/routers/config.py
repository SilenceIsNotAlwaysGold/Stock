"""配置管理 API"""

import logging
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

_config_store: Dict[str, Dict] = {
    # ── 数据源 ──────────────────────────────────────────────
    "tushare_token": {
        "key": "tushare_token", "category": "data_source",
        "description": "Tushare API Token", "sensitive": True,
        "value": settings.TUSHARE_TOKEN or "",
    },
    "tushare_enabled": {
        "key": "tushare_enabled", "category": "data_source",
        "description": "是否启用 Tushare (true/false)", "sensitive": False,
        "value": str(settings.TUSHARE_ENABLED).lower(),
    },
    # ── LLM ─────────────────────────────────────────────────
    "deepseek_api_key": {
        "key": "deepseek_api_key", "category": "llm",
        "description": "DeepSeek API Key", "sensitive": True,
        "value": settings.DEEPSEEK_API_KEY or "",
    },
    "deepseek_model": {
        "key": "deepseek_model", "category": "llm",
        "description": "DeepSeek 模型名称", "sensitive": False,
        "value": settings.DEEPSEEK_MODEL,
    },
    # ── T1 策略基础 ──────────────────────────────────────────
    "t1_top_n": {
        "key": "t1_top_n", "category": "t1_strategy",
        "description": "每日最多选股数量", "sensitive": False,
        "value": str(settings.T1_TOP_N),
    },
    "t1_market_safe_threshold": {
        "key": "t1_market_safe_threshold", "category": "t1_strategy",
        "description": "市场安全分数阈值 (市场面满分15)", "sensitive": False,
        "value": str(settings.T1_MARKET_SAFE_THRESHOLD),
    },
    "t1_min_total_score": {
        "key": "t1_min_total_score", "category": "t1_strategy",
        "description": "候选股最低综合分数", "sensitive": False,
        "value": str(settings.T1_MIN_TOTAL_SCORE),
    },
    "t1_scan_days": {
        "key": "t1_scan_days", "category": "t1_strategy",
        "description": "评分时拉取的历史天数", "sensitive": False,
        "value": str(settings.T1_SCAN_DAYS),
    },
    "t1_excluded_prefixes": {
        "key": "t1_excluded_prefixes", "category": "t1_strategy",
        "description": "排除的股票代码前缀 (逗号分隔, 如 688,300)", "sensitive": False,
        "value": settings.T1_EXCLUDED_PREFIXES,
    },
    # ── T1 卖出参数 ──────────────────────────────────────────
    "t1_sell_phase1_take_profit": {
        "key": "t1_sell_phase1_take_profit", "category": "t1_sell",
        "description": "集合竞价止盈线 (如 0.05 = 5%)", "sensitive": False,
        "value": str(settings.T1_SELL_PHASE1_TAKE_PROFIT),
    },
    "t1_sell_phase1_stop_loss": {
        "key": "t1_sell_phase1_stop_loss", "category": "t1_sell",
        "description": "集合竞价止损线 (如 -0.03 = -3%)", "sensitive": False,
        "value": str(settings.T1_SELL_PHASE1_STOP_LOSS),
    },
    "t1_sell_phase2_take_profit": {
        "key": "t1_sell_phase2_take_profit", "category": "t1_sell",
        "description": "早盘止盈线 (如 0.05 = 5%)", "sensitive": False,
        "value": str(settings.T1_SELL_PHASE2_TAKE_PROFIT),
    },
    "t1_sell_phase2_stop_loss": {
        "key": "t1_sell_phase2_stop_loss", "category": "t1_sell",
        "description": "早盘止损线 (如 -0.03 = -3%)", "sensitive": False,
        "value": str(settings.T1_SELL_PHASE2_STOP_LOSS),
    },
    "t1_sell_phase3_stop_loss": {
        "key": "t1_sell_phase3_stop_loss", "category": "t1_sell",
        "description": "观察期止损线 (如 -0.025 = -2.5%)", "sensitive": False,
        "value": str(settings.T1_SELL_PHASE3_STOP_LOSS),
    },
    # ── T1 仓位管理 ──────────────────────────────────────────
    "t1_max_single_pct": {
        "key": "t1_max_single_pct", "category": "t1_position",
        "description": "单仓最大仓位比例 (如 0.60 = 60%)", "sensitive": False,
        "value": str(settings.T1_MAX_SINGLE_PCT),
    },
    "t1_cash_reserve_pct": {
        "key": "t1_cash_reserve_pct", "category": "t1_position",
        "description": "保留现金比例 (如 0.20 = 20%)", "sensitive": False,
        "value": str(settings.T1_CASH_RESERVE_PCT),
    },
    "t1_consecutive_loss_limit": {
        "key": "t1_consecutive_loss_limit", "category": "t1_position",
        "description": "触发减仓的连续亏损次数", "sensitive": False,
        "value": str(settings.T1_CONSECUTIVE_LOSS_LIMIT),
    },
    "t1_consecutive_loss_reduce": {
        "key": "t1_consecutive_loss_reduce", "category": "t1_position",
        "description": "连续亏损后仓位缩减比例 (如 0.5 = 减半)", "sensitive": False,
        "value": str(settings.T1_CONSECUTIVE_LOSS_REDUCE),
    },
    "t1_max_drawdown_pct": {
        "key": "t1_max_drawdown_pct", "category": "t1_position",
        "description": "最大回撤触发暂停阈值 (如 0.15 = 15%)", "sensitive": False,
        "value": str(settings.T1_MAX_DRAWDOWN_PCT),
    },
    "t1_drawdown_pause_days": {
        "key": "t1_drawdown_pause_days", "category": "t1_position",
        "description": "触发最大回撤后暂停交易天数", "sensitive": False,
        "value": str(settings.T1_DRAWDOWN_PAUSE_DAYS),
    },
    # ── 推送通知 ─────────────────────────────────────────────
    "feishu_webhook": {
        "key": "feishu_webhook", "category": "notification",
        "description": "飞书机器人 Webhook URL", "sensitive": True,
        "value": settings.FEISHU_WEBHOOK or "",
    },
    "dingtalk_webhook": {
        "key": "dingtalk_webhook", "category": "notification",
        "description": "钉钉机器人 Webhook URL", "sensitive": True,
        "value": settings.DINGTALK_WEBHOOK or "",
    },
    "notify_daily_push": {
        "key": "notify_daily_push", "category": "notification",
        "description": "启用每日 8:30 自动推送 (true/false)", "sensitive": False,
        "value": str(settings.NOTIFY_DAILY_PUSH).lower(),
    },
}

# settings 字段类型映射，用于更新时做类型转换
_SETTINGS_MAP: Dict[str, tuple] = {
    "tushare_token":              ("TUSHARE_TOKEN", str),
    "tushare_enabled":            ("TUSHARE_ENABLED", lambda v: v.lower() == "true"),
    "deepseek_api_key":           ("DEEPSEEK_API_KEY", str),
    "deepseek_model":             ("DEEPSEEK_MODEL", str),
    "t1_top_n":                   ("T1_TOP_N", int),
    "t1_market_safe_threshold":   ("T1_MARKET_SAFE_THRESHOLD", float),
    "t1_min_total_score":         ("T1_MIN_TOTAL_SCORE", float),
    "t1_scan_days":               ("T1_SCAN_DAYS", int),
    "t1_excluded_prefixes":       ("T1_EXCLUDED_PREFIXES", str),
    "t1_sell_phase1_take_profit": ("T1_SELL_PHASE1_TAKE_PROFIT", float),
    "t1_sell_phase1_stop_loss":   ("T1_SELL_PHASE1_STOP_LOSS", float),
    "t1_sell_phase2_take_profit": ("T1_SELL_PHASE2_TAKE_PROFIT", float),
    "t1_sell_phase2_stop_loss":   ("T1_SELL_PHASE2_STOP_LOSS", float),
    "t1_sell_phase3_stop_loss":   ("T1_SELL_PHASE3_STOP_LOSS", float),
    "t1_max_single_pct":          ("T1_MAX_SINGLE_PCT", float),
    "t1_cash_reserve_pct":        ("T1_CASH_RESERVE_PCT", float),
    "t1_consecutive_loss_limit":  ("T1_CONSECUTIVE_LOSS_LIMIT", int),
    "t1_consecutive_loss_reduce": ("T1_CONSECUTIVE_LOSS_REDUCE", float),
    "t1_max_drawdown_pct":        ("T1_MAX_DRAWDOWN_PCT", float),
    "t1_drawdown_pause_days":     ("T1_DRAWDOWN_PAUSE_DAYS", int),
    "feishu_webhook":             ("FEISHU_WEBHOOK", str),
    "dingtalk_webhook":           ("DINGTALK_WEBHOOK", str),
    "notify_daily_push":          ("NOTIFY_DAILY_PUSH", lambda v: v.lower() == "true"),
}


class ConfigUpdateRequest(BaseModel):
    value: str


# 固定路径必须在 /{key} 之前注册
@router.get("/categories/list")
async def list_categories():
    categories = list(set(item["category"] for item in _config_store.values()))
    return categories


@router.get("/list")
async def list_configs(category: str = ""):
    result = []
    for item in _config_store.values():
        entry = {**item}
        if entry.get("sensitive"):
            entry["value"] = "***" if entry["value"] else ""
        if category and entry["category"] != category:
            continue
        result.append(entry)
    return result


@router.get("/{key}")
async def get_config(key: str):
    if key not in _config_store:
        raise HTTPException(404, f"Config key '{key}' not found")
    item = {**_config_store[key]}
    if item.get("sensitive"):
        item["value"] = "***" if item["value"] else ""
    return item


@router.put("/{key}")
async def update_config(key: str, req: ConfigUpdateRequest):
    if key not in _config_store:
        raise HTTPException(404, f"Config key '{key}' not found")

    new_val = req.value.strip()

    # 敏感字段：若用户提交空字符串或 *** 则保持原值不变
    if _config_store[key].get("sensitive") and new_val in ("", "***"):
        return {"status": "skipped", "key": key, "reason": "sensitive field unchanged"}

    _config_store[key]["value"] = new_val

    # 同步写回 settings 对象（本进程立即生效）
    if key in _SETTINGS_MAP:
        attr, cast = _SETTINGS_MAP[key]
        try:
            object.__setattr__(settings, attr, cast(new_val))
            logger.info(f"Config applied: {attr} = {new_val!r}")
        except Exception as e:
            logger.warning(f"Config type cast failed for {key}: {e}")

    return {"status": "updated", "key": key}
