"""Supabase access-token verification; application roles are resolved from PostgreSQL.

No header-selected remote key URLs and no HS256 production fallback are accepted.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError

from app.core.errors import AppError
from app.core.settings import Settings, get_settings


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: UUID
    issuer: str
    session_id: UUID
    email: str | None
    email_verified: bool
    auth_time: datetime

    @property
    def sub(self) -> str:
        return str(self.subject)


@lru_cache(maxsize=8)
def _jwk_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)


def clear_jwks_cache() -> None:
    """Operations kill switch for urgent signing-key revocation."""
    _jwk_client.cache_clear()


def _supabase_user(token: str, settings: Settings, subject: UUID) -> dict[str, Any]:
    publishable_key = settings.supabase_publishable_key.get_secret_value()
    if not publishable_key:
        raise AppError(503, "AUTH_UNAVAILABLE", "Authentication provider is not configured")
    try:
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            response = client.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": publishable_key},
            )
        if response.status_code in {401, 403}:
            raise AppError(401, "INVALID_TOKEN", "The session is not valid")
        if response.status_code != 200:
            raise AppError(503, "AUTH_UNAVAILABLE", "Authentication provider is temporarily unavailable")
        user = response.json()
        if not isinstance(user, dict) or not isinstance(user.get("id"), str):
            raise ValueError("Malformed authentication provider identity")
        if UUID(user["id"]) != subject:
            raise AppError(401, "INVALID_TOKEN", "The session is not valid")
        return user
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise AppError(503, "AUTH_UNAVAILABLE", "Authentication provider is temporarily unavailable") from exc


def verify_access_token(token: str, settings: Settings | None = None) -> VerifiedIdentity:
    settings = settings or get_settings()
    if not token or len(token) > 16384:
        raise AppError(401, "INVALID_TOKEN", "A valid access token is required")
    if settings.auth_mode == "supabase" and not settings.supabase_url.startswith("https://"):
        raise AppError(503, "AUTH_UNAVAILABLE", "Authentication provider is not configured")
    try:
        header = jwt.get_unverified_header(token)
        if any(name in header for name in ("jku", "x5u", "jwk")):
            raise AppError(401, "INVALID_TOKEN", "The session is not valid")
        algorithm = header.get("alg")
        if settings.auth_mode == "local":
            # Settings rejects this mode unless development/test and explicitly enabled.
            if algorithm != "HS256":
                raise AppError(401, "INVALID_TOKEN", "The session is not valid")
            key: Any = settings.dev_jwt_secret.get_secret_value()
            allowed_algorithms = ["HS256"]
        else:
            if algorithm not in {"ES256", "RS256"} or not isinstance(header.get("kid"), str):
                raise AppError(401, "INVALID_TOKEN", "The session is not valid")
            key = _jwk_client(settings.jwks_url).get_signing_key_from_jwt(token).key
            allowed_algorithms = ["ES256", "RS256"]
        claims = jwt.decode(
            token,
            key=key,
            algorithms=allowed_algorithms,
            audience=settings.supabase_jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=settings.jwt_clock_skew_seconds,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "session_id"]},
        )
        subject = UUID(claims["sub"])
        if not isinstance(claims["session_id"], str):
            raise AppError(401, "INVALID_TOKEN", "The session is not valid")
        session_id = UUID(claims["session_id"])
        issued_at = datetime.fromtimestamp(claims["iat"], UTC)
        if claims["exp"] - claims["iat"] > settings.jwt_max_lifetime_seconds:
            raise AppError(401, "INVALID_TOKEN", "The token lifetime is not permitted")
        amr_times = [
            entry["timestamp"]
            for entry in claims.get("amr", [])
            if isinstance(entry, dict) and isinstance(entry.get("timestamp"), (int, float))
        ]
        auth_timestamp = claims.get("auth_time", min(amr_times) if amr_times else 0)
        auth_time = datetime.fromtimestamp(auth_timestamp, UTC)
        if auth_time > issued_at + timedelta(seconds=settings.jwt_clock_skew_seconds):
            raise AppError(401, "INVALID_TOKEN", "The session is not valid")
        if settings.auth_mode == "supabase":
            user = _supabase_user(token, settings, subject)
            # Confirmation is a provider-owned field, never user_metadata.email_verified.
            email_verified = bool(user.get("email_confirmed_at"))
            email = user.get("email")
        else:
            email_verified = claims.get("email_verified") is True
            email = claims.get("email")
        if not email_verified:
            raise AppError(403, "EMAIL_UNVERIFIED", "Verify your email before using Career Kitchen")
        return VerifiedIdentity(subject, settings.jwt_issuer, session_id, email, email_verified, auth_time)
    except PyJWKClientError as exc:
        # Unknown key, malformed provider response, and network failure all fail closed.
        raise AppError(401, "INVALID_TOKEN", "The session could not be verified") from exc
    except (PyJWTError, ValueError, TypeError, KeyError, OverflowError, OSError) as exc:
        raise AppError(401, "INVALID_TOKEN", "The session is not valid") from exc


def mint_dev_token(
    subject: UUID | str,
    *,
    email: str = "fictional@example.invalid",
    session_id: UUID | None = None,
    lifetime_seconds: int = 1800,
    settings: Settings | None = None,
) -> str:
    """CLI-only helper for fictional development fixtures; never exposed as an API login."""
    settings = settings or get_settings()
    if settings.auth_mode != "local" or settings.environment not in {"development", "test"}:
        raise AppError(403, "DEV_AUTH_DISABLED", "Development authentication is disabled")
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(UUID(str(subject))),
            "session_id": str(session_id or uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.supabase_jwt_audience,
            "iat": now,
            "exp": now + timedelta(seconds=min(lifetime_seconds, settings.jwt_max_lifetime_seconds)),
            "auth_time": int(now.timestamp()),
            "email": email,
            "email_verified": True,
        },
        settings.dev_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
