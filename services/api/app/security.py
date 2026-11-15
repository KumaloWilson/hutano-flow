import hashlib
import hmac
import ipaddress
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


# Verified when an email is unknown so that response time does not reveal which
# accounts exist (the Argon2 cost dominates both paths).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(24))


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


COMMON_PASSWORDS = {
    "password1234", "password123!", "123456789012", "qwertyuiop12", "letmein12345", "welcome12345",
    "hutanoflow123", "changeme1234", "administrator", "zimbabwe1234", "harare123456",
}


def password_problems(password: str, email: str = "", display_name: str = "") -> list[str]:
    """Length-first policy (NIST SP 800-63B style): no composition rules, block the obvious."""
    problems = []
    lowered = password.lower()
    if len(password) < 12:
        problems.append("Use at least 12 characters")
    if len(password) > 128:
        problems.append("Use at most 128 characters")
    if lowered in COMMON_PASSWORDS or len(set(password)) < 5:
        problems.append("Choose a less common password")
    local = email.split("@")[0].lower()
    if (local and len(local) >= 4 and local in lowered) or (display_name and display_name.lower().replace(" ", "") in lowered.replace(" ", "")):
        problems.append("Do not include your name or email address")
    return problems


def create_session_token(user: User, auth_time: datetime | None = None) -> str:
    """Short idle window (`exp`) inside an absolute lifetime anchored at sign-in (`auth`)."""
    now = datetime.now(timezone.utc)
    auth_time = auth_time or now
    absolute = auth_time + timedelta(minutes=settings.session_minutes)
    return jwt.encode(
        {
            "sub": str(user.id),
            "fid": str(user.facility_id),
            "sv": user.session_version,
            "iat": now,
            "auth": int(auth_time.timestamp()),
            "exp": min(now + timedelta(minutes=settings.session_idle_minutes), absolute),
            "jti": secrets.token_urlsafe(16),
        },
        settings.secret_key,
        algorithm="HS256",
    )


def session_auth_time(payload: dict) -> datetime:
    value = payload.get("auth") or payload.get("iat")
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


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


# Endpoints a user with a temporary password may still reach.
PASSWORD_CHANGE_ALLOWED = {"/api/v1/me", "/api/v1/auth/password", "/api/v1/auth/logout", "/api/v1/auth/refresh"}


def get_current_user(
    request: Request,
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
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(status_code=403, detail="Change your temporary password before continuing")
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

    def _bucket(self, key: str, seconds: int) -> deque:
        now = time.monotonic()
        if len(self._events) > 10000:
            self._events = defaultdict(deque, {k: v for k, v in self._events.items() if v and v[-1] > now - 600})
        bucket = self._events[key]
        while bucket and bucket[0] <= now - seconds:
            bucket.popleft()
        return bucket

    def check(self, key: str, limit: int, seconds: int) -> None:
        bucket = self._bucket(key, seconds)
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail="Too many requests; try again later",
                                headers={"Retry-After": str(seconds)})
        bucket.append(time.monotonic())

    def guard(self, key: str, limit: int, seconds: int) -> None:
        """Reject when `limit` events were recorded, without counting this request."""
        if len(self._bucket(key, seconds)) >= limit:
            raise HTTPException(status_code=429, detail="Too many requests; try again later",
                                headers={"Retry-After": str(seconds)})

    def record(self, key: str) -> None:
        self._events[key].append(time.monotonic())


rate_limiter = SlidingWindowLimiter()


def _trusted_networks() -> list:
    networks = []
    for item in settings.trusted_proxies:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return networks


TRUSTED_NETWORKS = _trusted_networks()


def _is_trusted(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return any(ip in network for network in TRUSTED_NETWORKS)


def client_ip(request: Request) -> str:
    """Real client address behind the web proxy.

    X-Forwarded-For is honoured only when the direct peer is a trusted proxy. The chain
    is walked right-to-left and the first untrusted hop is returned, so a client cannot
    pick its own rate-limit bucket by sending a forged header (proxies append, never
    replace, so the right-most entries are the ones a trusted hop actually observed).
    """
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted(peer):
        return peer
    forwarded = request.headers.get("X-Forwarded-For", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop):
            return hop
    return hops[0] if hops else peer


def client_key(request: Request, prefix: str) -> str:
    return f"{prefix}:{client_ip(request)}"

