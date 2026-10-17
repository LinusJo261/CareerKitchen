"""Versioned PACT records. These never imply a hiring or matching decision."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now() -> datetime:
    return datetime.now(UTC)


class PactRecord:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class PactPolicy(PactRecord, Base):
    __tablename__ = "pact_policy_versions"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_text: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(30))
    # Each exact ID maps to immutable role version, terms hash and requirements hash.
    scope: Mapped[dict] = mapped_column(JSON)
    scope_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), default="DRAFT")
    __table_args__ = (
        CheckConstraint("stage IN ('SCREENING','INTERVIEW','CONDITIONAL_OFFER')", name="policy_stage"),
        CheckConstraint("state IN ('DRAFT','AUTHORIZED','REVOKED')", name="policy_state"),
    )


class PactAuthorization(PactRecord, Base):
    __tablename__ = "pact_policy_authorizations"
    policy_id: Mapped[str] = mapped_column(ForeignKey("pact_policy_versions.id"), unique=True)
    signatory_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    scope_hash: Mapped[str] = mapped_column(String(64))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(500))


class EvidenceClaim(PactRecord, Base):
    __tablename__ = "evidence_claims"
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    claim_type: Mapped[str] = mapped_column(String(40))
    requirement_keys: Mapped[list] = mapped_column(JSON)
    statement_hash: Mapped[str] = mapped_column(String(64))
    private_object_ref: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    verification_method: Mapped[str | None] = mapped_column(String(100))
    source_reference_hash: Mapped[str | None] = mapped_column(String(64))
    issuer: Mapped[str | None] = mapped_column(String(200))
    verifier_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','VERIFIED','FAILED','REVOKED')", name="evidence_status"),
    )


class EvidenceGrant(PactRecord, Base):
    __tablename__ = "evidence_access_grants"
    claim_id: Mapped[str] = mapped_column(ForeignKey("evidence_claims.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    role_version: Mapped[int] = mapped_column(Integer)
    terms_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30))
    consent_text_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("kind IN ('DISCLOSE_SUMMARY','DISCLOSE_DOCUMENT')", name="grant_kind"),)


class TermConsent(PactRecord, Base):
    __tablename__ = "candidate_term_consents"
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    role_version: Mapped[int] = mapped_column(Integer)
    terms_hash: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("scope IN ('PRELIMINARY_INTEREST','CONDITIONAL_TERMS')", name="terms_scope"),
    )


class ReadinessProof(PactRecord, Base):
    __tablename__ = "readiness_proofs"
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    role_version: Mapped[int] = mapped_column(Integer)
    authorization_id: Mapped[str] = mapped_column(ForeignKey("pact_policy_authorizations.id"))
    terms_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), default="READY")
    invalidated_reason: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (CheckConstraint("state IN ('READY','INVALIDATED','EXPIRED')", name="readiness_state"),)


class Clarification(PactRecord, Base):
    __tablename__ = "policy_clarification_requests"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("vacancy_requirements.id"))
    role_version: Mapped[int] = mapped_column(Integer)
    requirement_version: Mapped[int] = mapped_column(Integer)
    proposed_kind: Mapped[str] = mapped_column(String(20))
    proposed_text: Mapped[str] = mapped_column(String(2000))
    reason: Mapped[str] = mapped_column(String(1000))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    responded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('REQUESTED','APPROVED','DENIED','EXPIRED')", name="clarification_status"),
        CheckConstraint("proposed_kind = 'PREFERENCE'", name="clarification_proposed_kind"),
    )


class ExclusiveReservation(PactRecord, Base):
    __tablename__ = "exclusive_reservations"
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    vacancy_id: Mapped[str] = mapped_column(ForeignKey("vacancies.id"), index=True)
    role_version: Mapped[int] = mapped_column(Integer)
    terms_hash: Mapped[str] = mapped_column(String(64))
    consent_text_hash: Mapped[str] = mapped_column(String(64))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','RELEASED','EXPIRED')", name="reservation_status"),
        Index(
            "uq_exclusive_reservation_candidate_active",
            "candidate_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )
