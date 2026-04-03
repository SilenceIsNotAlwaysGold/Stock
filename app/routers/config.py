"""配置管理 API"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存配置存储（生产环境从 PG system_config 表读取）
_config_store: Dict[str, Dict] = {
    "tushare_token": {
        "key": "tushare_token",
        "value": settings.TUSHARE_TOKEN or "",
        "category": "data_source",
        "description": "Tushare API Token",
        "sensitive": True,
    },
    "deepseek_api_key": {
        "key": "deepseek_api_key",
        "value": settings.DEEPSEEK_API_KEY or "",
        "category": "llm",
        "description": "DeepSeek API Key",
        "sensitive": True,
    },
    "deepseek_model": {
        "key": "deepseek_model",
        "value": settings.DEEPSEEK_MODEL,
        "category": "llm",
        "description": "DeepSeek 模型名称",
        "sensitive": False,
    },
    "tushare_enabled": {
        "key": "tushare_enabled",
        "value": str(settings.TUSHARE_ENABLED),
        "category": "data_source",
        "description": "是否启用 Tushare",
        "sensitive": False,
    },
}


class ConfigUpdateRequest(BaseModel):
    value: str


@router.get("/list")
async def list_configs(category: str = ""):
    """列出所有配置"""
    configs = []
    for item in _config_store.values():
        entry = {**item}
        if entry.get("sensitive"):
            entry["value"] = "***" if entry["value"] else ""
        if category and entry["category"] != category:
            continue
        configs.append(entry)
    return configs


@router.get("/{key}")
async def get_config(key: str):
    """获取单个配置"""
    if key not in _config_store:
        raise HTTPException(404, f"Config key '{key}' not found")
    item = {**_config_store[key]}
    if item.get("sensitive"):
        item["value"] = "***" if item["value"] else ""
    return item


@router.put("/{key}")
async def update_config(key: str, req: ConfigUpdateRequest):
    """更新配置"""
    if key not in _config_store:
        raise HTTPException(404, f"Config key '{key}' not found")
    _config_store[key]["value"] = req.value
    logger.info(f"Config updated: {key}")
    return {"status": "updated", "key": key}


@router.get("/categories/list")
async def list_categories():
    """列出配置分类"""
    categories = set(item["category"] for item in _config_store.values())
    return list(categories)
