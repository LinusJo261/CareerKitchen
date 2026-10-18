from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

from anyio import CancelScope, CapacityLimiter, to_thread
from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.auth import verify_access_token
from app.core.errors import AppError
from app.core.security import decrypt, encrypt, pseudonym
from app.db.models import IdempotencyRecord, RateBucket, RevokedSession, User
from app.services.common import Actor, digest, lock_scopes, utcnow


def db_dep(request: Request) -> Session:
    return request.state.db


def actor_dep(request: Request) -> Actor:
    if getattr(request.state, "actor", None):
        return request.state.actor
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise AppError(401, "UNAUTHORIZED", "A valid Supabase access token is required")
    settings = request.app.state.settings
    if (
        settings.auth_mode == "local"
        and request.client
        and request.client.host not in {"127.0.0.1", "::1", "testclient"}
    ):
        raise AppError(403, "LOCAL_AUTH_ONLY", "Development identity is restricted to loopback")
    identity = verify_access_token(auth[7:], settings=settings)
    db = request.state.db
    lock_scopes(db, f"identity:{identity.issuer}:{identity.subject}")
    user = db.scalar(
        select(User).where(User.issuer == identity.issuer, User.subject == str(identity.subject))
    )
    if user is None:
        user = User(
            id=str(identity.subject),
            issuer=identity.issuer,
            subject=str(identity.subject),
            verified_email=identity.email,
            platform_roles=[],
        )
        db.add(user)
        db.flush()
    if user.status != "ACTIVE" or not identity.email_verified:
        raise AppError(403, "ACCOUNT_INACTIVE", "An active account with verified email is required")
    if identity.email and user.verified_email != identity.email:
        user.verified_email = identity.email
    if db.get(RevokedSession, str(identity.session_id)):
        raise AppError(401, "SESSION_REVOKED", "This session has been revoked")
    actor = Actor(
        user.id,
        identity.auth_time,
        tuple(user.platform_roles),
        str(identity.session_id),
        request.state.request_id,
    )
    request.state.actor = actor
    return actor


def _rate_limit(db: Session, actor: Actor, settings) -> None:
    key = f"write:{actor.user_id}"
    lock_scopes(db, key)
    bucket = db.get(RateBucket, key)
    now = utcnow()
    if bucket is None:
        bucket = RateBucket(key=key, count=0, resets_at=now + timedelta(minutes=1))
        db.add(bucket)
    elif bucket.resets_at <= now:
        bucket.count = 0
        bucket.resets_at = now + timedelta(minutes=1)
    limit = settings.rate_limit_per_minute
    if bucket.count >= limit:
        raise AppError(429, "RATE_LIMITED", "Too many changes; try again shortly")
    bucket.count += 1


async def _buffer_request_body(request: Request) -> Any:
    limit = (
        request.app.state.settings.max_resume_bytes + 100000
        if "multipart/form-data" in request.headers.get("content-type", "")
        else 100000
    )
    buffered = bytearray()
    async for chunk in request.stream():
        if len(buffered) + len(chunk) > limit:
            raise AppError(413, "REQUEST_TOO_LARGE", "Request exceeds the size limit")
        buffered.extend(chunk)
    raw = bytes(buffered)
    request._body = raw
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form(max_files=1, max_fields=10, max_part_size=limit)
        parts: list[tuple] = []
        for name, value in form.multi_items():
            if isinstance(value, StarletteUploadFile):
                file_bytes = await value.read(limit + 1)
                await value.seek(0)
                parts.append(
                    (name, value.filename, value.content_type, hashlib.sha256(file_bytes).hexdigest())
                )
            else:
                parts.append((name, value))
        return sorted(parts, key=lambda value: value[0])
    try:
        return json.loads(raw) if raw and "application/json" in content_type else raw.hex()
    except ValueError:
        return raw.hex()


def _uses_actor(dependant) -> bool:
    return dependant.call is actor_dep or any(_uses_actor(item) for item in dependant.dependencies)


def _database_limiters(request: Request) -> tuple[CapacityLimiter, CapacityLimiter]:
    limiters = getattr(request.app.state, "transactional_database_limiters", None)
    if limiters is None:
        # Auth lock waiters must not consume FastAPI's endpoint worker capacity.
        # Finalization has separate capacity so lock holders can always commit or
        # roll back even while new requests wait for their authentication locks.
        limiters = (CapacityLimiter(32), CapacityLimiter(8))
        request.app.state.transactional_database_limiters = limiters
    return limiters


class TransactionalRoute(APIRoute):
    """One transaction covers authz, idempotency, business writes, audit and outbox.

    A Session moves between sequential worker calls; it is never used concurrently.
    Database I/O and lock waits run outside the event loop, including cleanup.
    """

    def get_route_handler(self):
        handler = super().get_route_handler()
        protected = _uses_actor(self.dependant)

        async def transactional(request: Request):
            db = Session(request.app.state.engine, expire_on_commit=False)
            request.state.db = db
            request.state.request_id = getattr(request.state, "request_id", str(uuid4()))
            prelude_limiter, finalizer_limiter = _database_limiters(request)
            record_key = None
            request_hash = None
            write = request.method not in {"GET", "HEAD", "OPTIONS"}
            try:
                # Buffer bounded async input before taking transaction locks. No
                # connection is acquired while waiting for a client upload.
                body = await _buffer_request_body(request) if write else None

                def prepare():
                    nonlocal record_key, request_hash
                    if not (write or protected):
                        return None
                    actor = actor_dep(request)
                    if not write:
                        return None
                    client_key = request.headers.get("idempotency-key", "")
                    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", client_key):
                        raise AppError(
                            422,
                            "IDEMPOTENCY_KEY_REQUIRED",
                            "Supply an Idempotency-Key of 8–128 safe characters",
                        )
                    route = f"{request.method}:{request.url.path}"
                    lock_scopes(db, f"idem:{actor.user_id}:{route}:{client_key}")
                    request_hash = pseudonym(digest([body, request.headers.get("if-match")]))
                    record_key = (actor.user_id, route, client_key)
                    old = db.get(IdempotencyRecord, record_key)
                    if old and old.expires_at <= utcnow():
                        db.delete(old)
                        db.flush()
                        old = None
                    if old:
                        if old.request_hash != request_hash:
                            raise AppError(
                                409,
                                "IDEMPOTENCY_CONFLICT",
                                "This key was already used with a different request",
                            )
                        from app.api.replay_acl import authorize_replay

                        authorize_replay(db, actor, request.url.path, body, request=request)
                        db.commit()
                        return Response(
                            content=decrypt(old.response_json),
                            status_code=old.status_code,
                            media_type="application/json",
                            headers={"Idempotency-Replayed": "true"},
                        )
                    if request.headers.get("if-match") and isinstance(body, dict):
                        version = body.get("expected_version", body.get("expected_cycle_version"))
                        if version is not None and request.headers["if-match"].strip('"') != str(version):
                            raise AppError(
                                412, "VERSION_CONFLICT", "If-Match must agree with the request version"
                            )
                    _rate_limit(db, actor, request.app.state.settings)
                    return None

                replay = (
                    await to_thread.run_sync(prepare, limiter=prelude_limiter) if write or protected else None
                )
                if replay is not None:
                    return replay
                response = await handler(request)

                def finish():
                    if response.status_code >= 400:
                        db.rollback()
                        return
                    if "application/json" in response.headers.get("content-type", ""):
                        content = json.loads(response.body)
                        if isinstance(content, dict):
                            data = content.get("data")
                            resource_version = (
                                data.get("version", data.get("cycle_version"))
                                if isinstance(data, dict)
                                else None
                            )
                            content.setdefault("meta", {}).update(
                                request_id=request.state.request_id,
                                server_time=utcnow().isoformat(),
                                resource_version=resource_version,
                            )
                        response.body = json.dumps(content, separators=(",", ":")).encode()
                        response.headers["content-length"] = str(len(response.body))
                    if record_key:
                        db.add(
                            IdempotencyRecord(
                                actor_id=record_key[0],
                                route=record_key[1],
                                client_key=record_key[2],
                                request_hash=request_hash,
                                response_json=encrypt(bytes(response.body)),
                                status_code=response.status_code,
                                expires_at=utcnow() + timedelta(days=7),
                            )
                        )
                    db.commit()

                await to_thread.run_sync(finish, limiter=finalizer_limiter)
                return response
            except (IntegrityError, OperationalError) as exc:
                with CancelScope(shield=True):
                    await to_thread.run_sync(db.rollback, limiter=finalizer_limiter)
                raise AppError(
                    409, "TRANSACTION_CONFLICT", "Conflicting update; refresh and retry with the same key"
                ) from exc
            except BaseException:
                with CancelScope(shield=True):
                    await to_thread.run_sync(db.rollback, limiter=finalizer_limiter)
                raise
            finally:
                with CancelScope(shield=True):
                    await to_thread.run_sync(db.close, limiter=finalizer_limiter)

        return transactional
