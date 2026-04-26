"""
core/auth.py — JWT аутентификация и управление паролями для NeoRender Pro.

Используется в api_server.py для:
- Выдачи токенов (login / register)
- Проверки токена на каждом защищённом маршруте
- Хеширования/верификации паролей
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# ── Секретный ключ ────────────────────────────────────────────────────────────
# В продакшне обязательно задать через переменную окружения NEO_JWT_SECRET

_DEFAULT_SECRET = "neorender-super-secret-change-in-production-2025"
JWT_SECRET = os.environ.get("NEO_JWT_SECRET", _DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("NEO_JWT_EXPIRE_MINUTES", "1440"))  # 24h

# ── Пароли ────────────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(
    user_id: int,
    email: str,
    role: str,
    tenant_id: str,
    *,
    expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Декодирует и валидирует токен. Бросает HTTPException при ошибке."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Токен недействителен: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


class TokenData:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.user_id: int = int(payload["sub"])
        self.email: str = str(payload.get("email", ""))
        self.role: str = str(payload.get("role", "user"))
        self.tenant_id: str = str(payload.get("tenant_id", "default"))


async def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str | None:
    """Извлекает Bearer токен из заголовка Authorization или куки."""
    if credentials and credentials.credentials:
        return credentials.credentials
    # fallback: cookie
    cookie = request.cookies.get("neo_token")
    if cookie:
        return cookie
    return None


async def get_current_user(
    token: str | None = Depends(_extract_token),
) -> TokenData:
    """Требует валидного токена. Используется как Depends() для защищённых маршрутов."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Авторизация обязательна",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    return TokenData(payload)


async def get_optional_user(
    token: str | None = Depends(_extract_token),
) -> TokenData | None:
    """Опциональная авторизация — не бросает ошибку если токена нет."""
    if not token:
        return None
    try:
        payload = decode_token(token)
        return TokenData(payload)
    except HTTPException:
        return None


async def require_admin(
    user: TokenData = Depends(get_current_user),
) -> TokenData:
    """Разрешает доступ только администраторам."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ только для администраторов",
        )
    return user


# Готовые Annotated-типы для удобства в api_server.py
from typing import Annotated

CurrentUser = Annotated[TokenData, Depends(get_current_user)]
OptionalUser = Annotated[TokenData | None, Depends(get_optional_user)]
AdminUser = Annotated[TokenData, Depends(require_admin)]
