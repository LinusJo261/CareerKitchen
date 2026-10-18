from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.models import AuditEvent, Candidate, OrgMember, OutboxEvent, Vacancy, VacancyACL

T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Actor:
    user_id: str
    auth_time: datetime
    platform_roles: tuple[str, ...] = ()
    session_id: str = ""
    request_id: str = "worker"


def lock_scopes(db: Session, *keys: str) -> None:
    """Transaction-scoped authoritative locks, shared by API and workers."""
    for key in sorted(set(keys)):
        if db.get_bind().dialect.name == "postgresql":
            lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        else:
            raise RuntimeError("Authoritative state requires PostgreSQL")


def load(db: Session, model: type[T], entity_id: str, lock: bool = False) -> T:
    identified = cast(Any, model)
    query = select(model).where(identified.id == str(entity_id))
    if lock:
        query = query.with_for_update()
    entity = db.scalar(query.execution_options(populate_existing=True))
    if entity is None:
        raise AppError(404, "NOT_FOUND", "Resource was not found")
    return entity


def require_version(entity: Any, expected: int) -> None:
    if entity.version != expected:
        raise AppError(412, "VERSION_CONFLICT", "Resource changed; refresh before trying again")


def require_platform(actor: Actor, *roles: str) -> None:
    if not set(actor.platform_roles).intersection(roles):
        raise AppError(403, "FORBIDDEN", "This operation requires a separately approved platform role")


def require_candidate(db: Session, actor: Actor) -> Candidate:
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == actor.user_id))
    if candidate is None:
        raise AppError(404, "PROFILE_REQUIRED", "Create a candidate profile first")
    return candidate


def require_org_role(
    db: Session, actor: Actor, org_id: str, roles: list[str] | tuple[str, ...] | set[str]
) -> OrgMember:
    member = db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == str(org_id),
            OrgMember.user_id == actor.user_id,
            OrgMember.role.in_(roles),
            OrgMember.status == "ACTIVE",
            (OrgMember.expires_at.is_(None) | (OrgMember.expires_at > utcnow())),
        )
    )
    if member is None:
        raise AppError(403, "FORBIDDEN", "You do not have permission in this organization")
    return member


def require_vacancy(db: Session, actor: Actor, vacancy_id: str, permission: str = "review") -> Vacancy:
    vacancy = load(db, Vacancy, vacancy_id)
    roles = {"RECRUITER", "HIRING_MANAGER", "ORG_ADMIN", "AUTHORIZED_SIGNATORY"}
    if permission in {"approve_policy", "policy", "sign"}:
        roles = {"AUTHORIZED_SIGNATORY"}
    require_org_role(db, actor, vacancy.org_id, roles)
    acl = db.scalar(
        select(VacancyACL).where(VacancyACL.vacancy_id == vacancy.id, VacancyACL.user_id == actor.user_id)
    )
    permitted = acl is not None and getattr(
        acl,
        "can_approve_policy"
        if permission in {"approve_policy", "policy", "sign"}
        else "can_edit"
        if permission in {"edit", "activate", "close"}
        else "can_review",
    )
    if not permitted:
        raise AppError(403, "VACANCY_FORBIDDEN", "You are not assigned to this job opening")
    return vacancy


def emit(
    db: Session,
    actor: Actor,
    action: str,
    entity: Any,
    org_id: str | None = None,
    payload: dict | None = None,
) -> OutboxEvent:
    db.flush()
    safe_payload = {
        "entity_id": entity.id,
        "entity_type": entity.__tablename__,
        "version": entity.version,
        **(payload or {}),
    }
    # Events contain references only; private content remains behind service ACLs.
    after_hash = digest(safe_payload)
    row_hash = digest(
        [actor.user_id, org_id, action, entity.__tablename__, entity.id, after_hash, actor.request_id]
    )
    settings = get_settings()
    key = settings.audit_hmac_key.get_secret_value()
    if len(key) < 32:
        raise AppError(503, "AUDIT_UNAVAILABLE", "Audit integrity key is not configured")
    db.add(
        AuditEvent(
            actor_id=actor.user_id,
            org_id=org_id,
            action=action,
            entity_type=entity.__tablename__,
            entity_id=entity.id,
            request_id=actor.request_id,
            after_hash=after_hash,
            integrity_hash=hmac.new(key.encode(), row_hash.encode(), hashlib.sha256).hexdigest(),
        )
    )
    event = OutboxEvent(aggregate_id=entity.id, kind=action, payload=safe_payload)
    db.add(event)
    return event


def verify_audit_integrity(row: AuditEvent) -> bool:
    key = get_settings().audit_hmac_key.get_secret_value()
    signed = digest(
        [row.actor_id, row.org_id, row.action, row.entity_type, row.entity_id, row.after_hash, row.request_id]
    )
    return len(key) >= 32 and hmac.compare_digest(
        row.integrity_hash, hmac.new(key.encode(), signed.encode(), hashlib.sha256).hexdigest()
    )


def invalidate(
    db: Session,
    *,
    candidate_id: str | None = None,
    vacancy_id: str | None = None,
    reason: str = "STATE_CHANGED",
    actor: Actor | None = None,
) -> None:
    from app.db.pact_models import ExclusiveReservation
    from app.services.pact import invalidate_readiness

    invalidate_readiness(db, candidate_id=candidate_id, vacancy_id=vacancy_id, reason=reason)
    query = select(ExclusiveReservation).where(ExclusiveReservation.status == "ACTIVE")
    if candidate_id:
        query = query.where(ExclusiveReservation.candidate_id == candidate_id)
    if vacancy_id:
        query = query.where(ExclusiveReservation.vacancy_id == vacancy_id)
    if candidate_id or vacancy_id:
        for reservation in db.scalars(query):
            reservation.status, reservation.version = "RELEASED", reservation.version + 1
            if actor:
                emit(db, actor, "candidate.reservation_released", reservation)
