"""JWT 用户认证（基于 python-jose 签名 token，重启不失效）"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

JWT_SECRET = settings.JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# 内存用户存储（仅 admin demo）
_users: Dict[str, Dict] = {}

# 演示账户（仅开发环境）
if settings.APP_ENV == "development":
    _users["admin"] = {
        "username": "admin",
        "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
        "role": "admin",
        "created_at": datetime.now().isoformat(),
    }
    logger.info("Development mode: demo account 'admin' created")


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _generate_token(username: str) -> str:
    """签名 JWT，重启不失效"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[Dict]:
    """验证 JWT 签名 + 过期时间"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
        return {"username": username, "expires_at": payload.get("exp", 0)}
    except JWTError:
        return None


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

    # JWT 自包含，旧 token 在 exp 内仍可用；签发新 token 即可
    new_token = _generate_token(info["username"])
    return {"token": new_token, "expires_in": JWT_EXPIRE_HOURS * 3600}
