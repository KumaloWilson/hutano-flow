"""Single-facility command transaction boundary, including durable replay.

Serializing facility mutations is a deliberate prototype tradeoff: conservative,
small-site throughput in exchange for straightforward cross-aggregate invariants.
"""
import hashlib
import json
import threading
import uuid
from collections import defaultdict

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.responses import Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.database import SessionLocal, get_db
from app.models import Facility, IdempotencyRecord, User
from app.security import decode_session_token, status_secret

_local_locks = defaultdict(threading.Lock)


class CommandRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            path = request.url.path
            if request.method not in {"POST", "PATCH", "PUT", "DELETE"} or path in {
                "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/patient-status/lookup"
            }:
                return await original(request)
            token = request.cookies.get("hutano_session")
            if not token:
                raise HTTPException(401, "Authentication required")
            identity = decode_session_token(token)
            key = request.headers.get("Idempotency-Key", "")
            if not 8 <= len(key) <= 100:
                raise HTTPException(400, "A valid Idempotency-Key header is required")
            raw = await request.body()
            if len(raw) > 5_100_000:
                raise HTTPException(413, "Request exceeds the upload limit")
            digest = hashlib.sha256(raw).hexdigest()
            override = request.app.dependency_overrides.get(get_db)
            iterator = override() if override else None
            db = next(iterator) if iterator else SessionLocal()
            request.state.command_db = db
            facility_id = uuid.UUID(identity["fid"])
            lock = _local_locks[str(facility_id)]
            await run_in_threadpool(lock.acquire)
            try:
                actor = db.get(User, uuid.UUID(identity["sub"]))
                if not actor or not actor.active or actor.facility_id != facility_id or actor.session_version != identity["sv"]:
                    raise HTTPException(401, "Session is invalid or revoked")
                db.scalar(select(Facility.id).where(Facility.id == facility_id).with_for_update())
                endpoint = f"{request.method} {path}"
                previous = db.scalar(select(IdempotencyRecord).where(
                    IdempotencyRecord.actor_id == actor.id, IdempotencyRecord.endpoint == endpoint,
                    IdempotencyRecord.key == key))
                if previous:
                    if previous.request_hash != digest:
                        raise HTTPException(409, "Idempotency key was already used with different content")
                    result = dict(previous.response_json)
                    if path == "/api/v1/visits":
                        result["opaque_status_token"] = status_secret(uuid.UUID(result["id"]), result["public_token"])
                    code = previous.status_code
                    db.rollback()
                    return Response(json.dumps(result), status_code=code,
                                    media_type="application/json", headers={"Idempotent-Replayed": "true"})
                response = await original(request)
                if response.status_code < 400:
                    result = json.loads(response.body)
                    # Receipt secrets are reproducible via keyed HMAC, never stored as plaintext.
                    result.pop("opaque_status_token", None)
                    db.add(IdempotencyRecord(facility_id=facility_id, actor_id=actor.id, endpoint=endpoint,
                        key=key, request_hash=digest, response_json=result, status_code=response.status_code))
                    db.commit()
                else:
                    db.rollback()
                return response
            except Exception:
                db.rollback()
                raise
            finally:
                lock.release()
                if not iterator:
                    db.close()
                request.state.command_db = None
        return handler
