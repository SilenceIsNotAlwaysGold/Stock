"""策略与回测 API 测试"""

import pytest


@pytest.mark.anyio
async def test_strategy_health_list(client):
    resp = await client.get("/api/strategy/list")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.anyio
async def test_backtest_strategies(client):
    resp = await client.get("/api/backtest/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.anyio
async def test_emotion_today(client):
    resp = await client.get("/api/emotion/today")
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert 0 <= data["score"] <= 100


@pytest.mark.anyio
async def test_paper_account(client):
    resp = await client.get("/api/paper/account")
    assert resp.status_code == 200
    data = resp.json()
    assert "cash" in data or "total_equity" in data


@pytest.mark.anyio
async def test_scheduler_tasks(client):
    resp = await client.get("/api/scheduler/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
