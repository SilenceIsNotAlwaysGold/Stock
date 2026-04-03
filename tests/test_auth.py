"""认证 API 测试"""

import pytest


@pytest.mark.anyio
async def test_register_and_login(client):
    # 注册
    resp = await client.post(
        "/api/auth/register",
        json={"username": "testuser", "password": "testpass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert "token" in data

    # 登录
    resp = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    token = data["token"]

    # 获取当前用户
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"


@pytest.mark.anyio
async def test_login_wrong_password(client):
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpass"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_me_no_token(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
