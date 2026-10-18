"""Authoritative application state; private data never enters ranker inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class User(Entity, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED','DEACTIVATED')"),
    )
    issuer: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(100))
    verified_email: Mapped[str] = mapped_column(String(320), default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    platform_roles: Mapped[list[str]] = mapped_column(JSON, default=list)


class RevokedSession(Base):
    __tablename__ = "revoked_sessions"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Candidate(Entity, Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint("cap BETWEEN 1 AND 10"),
        CheckConstraint("state IN ('DRAFT','ACTIVE','PAUSED','DEACTIVATED')"),
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    professional_links: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    headline: Mapped[str] = mapped_column(String(180))
    summary: Mapped[str] = mapped_column(Text, default="")
    region: Mapped[str] = mapped_column(String(160), default="")
    state: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    cap: Mapped[int] = mapped_column(Integer, default=10)
    role_families: Mapped[list[str]] = mapped_column(JSON, default=list)
    employment_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_modes: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    compensation_floor_cipher: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    compensation_period: Mapped[str] = mapped_column(String(12), default="ANNUAL")
    experiences: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    education: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resume_object_ref: Mapped[str | None] = mapped_column(String(250))
    matching_learning_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    matching_learning_consent_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class Skill(Entity, Base):
    __tablename__ = "skills_taxonomy"
    name: Mapped[str] = mapped_column(String(100), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    ontology_version: Mapped[str] = mapped_column(String(40), default="structured-v1")


class CandidateSkill(Entity, Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (UniqueConstraint("candidate_id", "skill_id"),)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills_taxonomy.id"))
    level: Mapped[int] = mapped_column(Integer, default=1)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)


class Organization(Entity, Base):
    __tablename__ = "organizations"
    legal_name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(120))
    domain: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    verification_state: Mapped[str] = mapped_column(String(30), default="PENDING_VERIFICATION")
    verification_source_hash: Mapped[str | None] = mapped_column(String(64))
    verified_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    active_role_capacity: Mapped[int] = mapped_column(Integer, default=3)
    matching_learning_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    matching_learning_consent_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class OrgMember(Entity, Base):
    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "role"),
        CheckConstraint("role IN ('RECRUITER','HIRING_MANAGER','ORG_ADMIN','AUTHORIZED_SIGNATORY')"),
        CheckConstraint("status IN ('PENDING','ACTIVE','REVOKED')"),
    )
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    source_hash: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(Entity, Base):
    __tablename__ = "organization_invitations"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(40))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Vacancy(Entity, Base):
    __tablename__ = "vacancies"
    __table_args__ = (
        CheckConstraint("cap BETWEEN 1 AND 10"),
        CheckConstraint("pay_min >= 0 AND pay_max >= pay_min"),
        CheckConstraint("openings_remaining >= 0 AND openings_remaining <= openings_total"),
        CheckConstraint("state IN ('DRAFT','ACTIVE','PAUSED','CLOSED','FILLED')"),
        CheckConstraint("work_mode IN ('REMOTE','HYBRID','ONSITE')"),
    )
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    role_family: Mapped[str] = mapped_column(String(120), index=True)
    employment_type: Mapped[str] = mapped_column(String(40))
    work_mode: Mapped[str] = mapped_column(String(20))
    location_region: Mapped[str] = mapped_column(String(160), default="")
    pay_min: Mapped[float] = mapped_column(Numeric(14, 2))
    pay_max: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    compensation_period: Mapped[str] = mapped_column(String(12), default="ANNUAL")
    openings_total: Mapped[int] = mapped_column(Integer, default=1)
    openings_remaining: Mapped[int] = mapped_column(Integer, default=1)
    cap: Mapped[int] = mapped_column(Integer, default=10)
    state: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    terms_hash: Mapped[str] = mapped_column(String(64), default="")


class VacancyACL(Entity, Base):
    __tablename__ = "vacancy_acl"
    __table_args__ = (UniqueConstraint("vacancy_id", "user_id"),)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    can_review: Mapped[bool] = mapped_column(Boolean, default=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve_policy: Mapped[bool] = mapped_column(Boolean, default=False)


class Requirement(Entity, Base):
    __tablename__ = "vacancy_requirements"
    __table_args__ = (CheckConstraint("kind IN ('ESSENTIAL','PREFERENCE','AMBIGUOUS')"),)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    lawful_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class CandidateBlock(Entity, Base):
    __tablename__ = "candidate_blocks"
    __table_args__ = (UniqueConstraint("candidate_id", "org_id"),)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))


class PairCycle(Entity, Base):
    __tablename__ = "pair_cycles"
    __table_args__ = (
        UniqueConstraint("candidate_id", "vacancy_id", "cycle_number"),
        Index(
            "uq_open_pair",
            "candidate_id",
            "vacancy_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
    )
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    role_version: Mapped[int] = mapped_column(Integer)
    cycle_number: Mapped[int] = mapped_column(Integer, default=1)
    first_mover: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(50))
    candidate_interested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    employer_interested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80), default="manual-reviewed-v1")
    score_trace: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DecisionCard(Entity, Base):
    __tablename__ = "decision_cards"
    __table_args__ = (
        UniqueConstraint("pair_cycle_id", "side"),
        CheckConstraint("side IN ('CANDIDATE','EMPLOYER')"),
        CheckConstraint("status IN ('ACTIVE','INTERESTED','PASSED','EXPIRED','CANCELLED')"),
        Index(
            "uq_one_active_card_per_cycle",
            "pair_cycle_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    side: Mapped[str] = mapped_column(String(20))
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str] = mapped_column(String(64))
    token_cipher: Mapped[str] = mapped_column(Text)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)


class WaitingItem(Entity, Base):
    __tablename__ = "waiting_items"
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"), unique=True)
    side: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), default="WAITING")


class MutualMatch(Entity, Base):
    __tablename__ = "mutual_matches"
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class Exposure(Entity, Base):
    __tablename__ = "exposure_events"
    decision_card_id: Mapped[str] = mapped_column(ForeignKey("decision_cards.id"), unique=True)
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"))
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    recipient_side: Mapped[str] = mapped_column(String(20))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(80))
    score_trace: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Message(Entity, Base):
    __tablename__ = "match_messages"
    match_id: Mapped[str] = mapped_column(ForeignKey("mutual_matches.id"), index=True)
    sender_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    attachment_id: Mapped[str | None] = mapped_column(ForeignKey("match_attachments.id"))


class Attachment(Entity, Base):
    __tablename__ = "match_attachments"
    match_id: Mapped[str] = mapped_column(ForeignKey("mutual_matches.id"), index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    object_ref: Mapped[str] = mapped_column(String(250))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)


class InterviewProposal(Entity, Base):
    __tablename__ = "interview_proposals"
    match_id: Mapped[str] = mapped_column(ForeignKey("mutual_matches.id"))
    initiator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    slots: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    timezone_label: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED")


class Interview(Entity, Base):
    __tablename__ = "interview_events"
    proposal_id: Mapped[str] = mapped_column(ForeignKey("interview_proposals.id"), unique=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("mutual_matches.id"))
    candidate_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    employer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StageEvent(Entity, Base):
    __tablename__ = "process_stage_events"
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    stage: Mapped[str] = mapped_column(String(50))
    source_hash: Mapped[str | None] = mapped_column(String(64))


class Offer(Entity, Base):
    __tablename__ = "employment_offers"
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"), index=True)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="OFFERED")
    terms_cipher: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmploymentStart(Entity, Base):
    __tablename__ = "verified_employment_starts"
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"), unique=True)
    reported_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_hash: Mapped[str] = mapped_column(String(64))
    verified_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    verification_state: Mapped[str] = mapped_column(String(30), default="PENDING")
    disputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Entity, Base):
    __tablename__ = "outbox_events"
    aggregate_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    dead_letter_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(80))


class InboxConsumption(Base):
    __tablename__ = "inbox_consumptions"
    consumer_name: Mapped[str] = mapped_column(String(60), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("outbox_events.id"), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    route: Mapped[str] = mapped_column(String(400), primary_key=True)
    client_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(Entity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(100))
    after_hash: Mapped[str] = mapped_column(String(64))
    integrity_hash: Mapped[str] = mapped_column(String(64))


class Notification(Entity, Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (UniqueConstraint("user_id", "event_id", "kind"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("outbox_events.id"))
    kind: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(String(20), default="NOT_CONFIGURED")


class NotificationPreference(Entity, Base):
    __tablename__ = "notification_preferences"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    in_app_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PrivacyRequest(Entity, Base):
    __tablename__ = "privacy_requests"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="QUEUED")
    result_cipher: Mapped[str | None] = mapped_column(Text)


class AbuseReport(Entity, Base):
    __tablename__ = "abuse_reports"
    reporter_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(String(80))
    description_cipher: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    resolution: Mapped[str | None] = mapped_column(String(1000))


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    resets_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketPrice(Entity, Base):
    __tablename__ = "market_prices"
    cell: Mapped[str] = mapped_column(String(160), unique=True)
    candidate_price: Mapped[float] = mapped_column(Float, default=0)
    employer_price: Mapped[float] = mapped_column(Float, default=0)
    candidate_h: Mapped[float] = mapped_column(Float, default=0)
    employer_h: Mapped[float] = mapped_column(Float, default=0)


class CongestionPrice(Entity, Base):
    __tablename__ = "congestion_prices"
    __table_args__ = (
        UniqueConstraint("scope_id", "side"),
        CheckConstraint("side IN ('CANDIDATE','EMPLOYER')"),
        CheckConstraint("price >= 0 AND gradient_h >= 0"),
    )
    scope_id: Mapped[str] = mapped_column(String(36), index=True)
    side: Mapped[str] = mapped_column(String(20))
    price: Mapped[float] = mapped_column(Float, default=0)
    gradient_h: Mapped[float] = mapped_column(Float, default=0)
    controlled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MatchingLearningState(Entity, Base):
    __tablename__ = "matching_learning_state"
    # Singleton coordination row. Its version changes on every learning-consent change.
    scope: Mapped[str] = mapped_column(String(20), unique=True, default="GLOBAL")


class MatchingModel(Entity, Base):
    __tablename__ = "matching_models"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','RETIRED')"),
        Index(
            "uq_matching_model_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )
    model_key: Mapped[str] = mapped_column(String(64), unique=True)
    artifact: Mapped[dict[str, Any]] = mapped_column(JSON)
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    activated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class MatchingObservation(Entity, Base):
    __tablename__ = "matching_observations"
    __table_args__ = (Index("ix_matching_observations_created_at_id", "created_at", "id"),)
    pair_cycle_id: Mapped[str] = mapped_column(ForeignKey("pair_cycles.id"), unique=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    # An as-observed outcome snapshot, never today's profile joined to an old label.
    observation: Mapped[dict[str, Any]] = mapped_column(JSON)


class ShadowRun(Entity, Base):
    __tablename__ = "shadow_runs"
    event_id: Mapped[str] = mapped_column(ForeignKey("outbox_events.id"), unique=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    baseline_hash: Mapped[str] = mapped_column(String(64))
    proposal_hash: Mapped[str] = mapped_column(String(64))
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON)
    side_effect_count: Mapped[int] = mapped_column(Integer, default=0)


def _immutable(mapper: Any, connection: Any, target: Any) -> None:
    raise ValueError("Append-only event cannot be changed")


for _model in (AuditEvent, Exposure, StageEvent, MatchingObservation):
    event.listen(_model, "before_update", _immutable)
    event.listen(_model, "before_delete", _immutable)
