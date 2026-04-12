"""JWT 用户认证"""

import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# JWT 简易实现（生产环境用 python-jose）
JWT_SECRET = settings.JWT_SECRET
JWT_EXPIRE_HOURS = 24

# 内存用户存储
_users: Dict[str, Dict] = {
    "admin": {
        "username": "admin",
        "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
        "role": "admin",
        "created_at": datetime.now().isoformat(),
    }
}

# 活跃 token
_tokens: Dict[str, Dict] = {}


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _generate_token(username: str) -> str:
    import secrets

    token = secrets.token_urlsafe(32)
    _tokens[token] = {
        "username": username,
        "created_at": time.time(),
        "expires_at": time.time() + JWT_EXPIRE_HOURS * 3600,
    }
    return token


def verify_token(token: str) -> Optional[Dict]:
    """验证 token"""
    info = _tokens.get(token)
    if not info:
        return None
    if time.time() > info["expires_at"]:
        del _tokens[token]
        return None
    return info


async def get_current_user(request: Request) -> Dict:
    """依赖注入：获取当前用户"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    token = auth[7:]
    info = verify_token(token)
    if not info:
        raise HTTPException(401, "Token 已过期")
    user = _users.get(info["username"])
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


@router.post("/login")
async def login(req: LoginRequest):
    """用户登录"""
    user = _users.get(req.username)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    if user["password_hash"] != _hash_password(req.password):
        raise HTTPException(401, "用户名或密码错误")

    token = _generate_token(req.username)
    return {
        "token": token,
        "username": req.username,
        "role": user["role"],
        "expires_in": JWT_EXPIRE_HOURS * 3600,
    }


@router.post("/register")
async def register(req: RegisterRequest):
    """用户注册"""
    if req.username in _users:
        raise HTTPException(400, "用户名已存在")
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少 6 位")

    _users[req.username] = {
        "username": req.username,
        "password_hash": _hash_password(req.password),
        "role": "user",
        "created_at": datetime.now().isoformat(),
    }
    token = _generate_token(req.username)
    return {
        "token": token,
        "username": req.username,
        "role": "user",
    }


@router.get("/me")
async def get_me(user: Dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "username": user["username"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


@router.post("/refresh")
async def refresh_token(request: Request):
    """刷新 Token"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    old_token = auth[7:]
    info = verify_token(old_token)
    if not info:
        raise HTTPException(401, "Token 已过期")

    # 删除旧 token，生成新 token
    del _tokens[old_token]
    new_token = _generate_token(info["username"])
    return {"token": new_token, "expires_in": JWT_EXPIRE_HOURS * 3600}
