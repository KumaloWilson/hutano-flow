import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_session_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "fid": str(user.facility_id),
            "sv": user.session_version,
            "iat": now,
            "exp": now + timedelta(minutes=settings.session_minutes),
            "jti": secrets.token_urlsafe(16),
        },
        settings.secret_key,
        algorithm="HS256",
    )


def decode_session_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid or expired") from exc


def csrf_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def status_secret(visit_id: uuid.UUID, public_token: str) -> str:
    secret = hmac.new(settings.secret_key.encode(), f"patient-status:{visit_id}".encode(), hashlib.sha256).hexdigest()
    return f"{public_token}.{secret}"


def get_current_user(
    session: Annotated[str | None, Cookie(alias="hutano_session")] = None,
    db: Session = Depends(get_db, scope="function"),
) -> User:
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_session_token(session)
    user = db.scalar(
        select(User).where(
            User.id == uuid.UUID(payload["sub"]),
            User.facility_id == uuid.UUID(payload["fid"]),
            User.active.is_(True),
        )
    )
    if not user or user.session_version != payload.get("sv"):
        raise HTTPException(status_code=401, detail="Session has been revoked")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def role_names(user: User) -> set[str]:
    return {role.role for role in user.roles}


def require_roles(*allowed: str) -> Callable:
    def dependency(user: CurrentUser) -> User:
        if not role_names(user).intersection(allowed):
            raise HTTPException(status_code=403, detail="You are not authorised for this operation")
        return user

    return dependency


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, seconds: int) -> None:
        now = time.monotonic()
        if len(self._events) > 10000:
            self._events = defaultdict(deque, {k: v for k, v in self._events.items() if v and v[-1] > now - 600})
        bucket = self._events[key]
        while bucket and bucket[0] <= now - seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail="Too many requests; try again later")
        bucket.append(now)


rate_limiter = SlidingWindowLimiter()


def client_key(request: Request, prefix: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{prefix}:{host}"

