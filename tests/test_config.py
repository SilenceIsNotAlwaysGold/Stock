"""配置管理 API 测试"""

import pytest


@pytest.mark.anyio
async def test_list_configs(client):
    resp = await client.get("/api/config/list")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.anyio
async def test_get_config(client):
    resp = await client.get("/api/config/deepseek_model")
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "deepseek_model"


@pytest.mark.anyio
async def test_sensitive_config_masked(client):
    resp = await client.get("/api/config/deepseek_api_key")
    assert resp.status_code == 200
    data = resp.json()
    # 敏感值应被掩码
    assert data["value"] in ("***", "")


@pytest.mark.anyio
async def test_update_config(client):
    resp = await client.put(
        "/api/config/deepseek_model",
        json={"value": "deepseek-chat-v2"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "updated"


@pytest.mark.anyio
async def test_list_categories(client):
    resp = await client.get("/api/config/categories/list")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
