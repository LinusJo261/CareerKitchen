"""Owner-scoped export and local erasure, with explicit provider-retention review."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.db.models import (
    Attachment,
    Candidate,
    CandidateBlock,
    CandidateSkill,
    DecisionCard,
    IdempotencyRecord,
    Message,
    Notification,
    NotificationPreference,
    Offer,
    OrgMember,
    PairCycle,
    PrivacyRequest,
    Skill,
    StageEvent,
    User,
    Vacancy,
)
from app.db.pact_models import (
    EvidenceClaim,
    EvidenceGrant,
    ExclusiveReservation,
    PactAuthorization,
    PactPolicy,
    TermConsent,
)
from app.integrations.storage import delete_private
from app.services import clearing
from app.services.common import Actor, emit, lock_scopes, utcnow
from app.services.pact import invalidate_readiness


def _fields(entity: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(entity, name) for name in fields}


def owner_export(db: Session, user: User) -> dict[str, Any]:
    """Explicit allowlists avoid counterpart content, storage paths and decision tokens."""
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    result: dict[str, Any] = {
        "format": "career-kitchen-owner-export-v1",
        "generated_at": utcnow(),
        "identity": _fields(user, ("id", "verified_email", "status", "created_at")),
        "candidate": None,
        "skills": [],
        "evidence_claims": [],
        "evidence_grants": [],
        "term_consents": [],
        "reservations": [],
        "blocks": [],
    }
    pair_ids: set[str] = set()
    if candidate:
        result["candidate"] = _fields(
            candidate,
            (
                "id",
                "headline",
                "summary",
                "region",
                "state",
                "cap",
                "role_families",
                "employment_types",
                "work_modes",
                "locations",
                "currency",
                "compensation_period",
                "experiences",
                "education",
                "available_from",
                "available_until",
                "terms_accepted",
                "privacy_accepted",
                "confirmed_at",
                "version",
            ),
        )
        result["candidate"]["private_compensation_floor"] = (
            decrypt(candidate.compensation_floor_cipher).decode()
            if candidate.compensation_floor_cipher
            else None
        )
        result["candidate"]["resume_document_present"] = bool(candidate.resume_object_ref)
        result["skills"] = [
            {
                "id": row.id,
                "skill_id": row.skill_id,
                "name": skill.name,
                "level": row.level,
                "confirmed": row.confirmed,
            }
            for row, skill in db.execute(
                select(CandidateSkill, Skill)
                .join(Skill, Skill.id == CandidateSkill.skill_id)
                .where(CandidateSkill.candidate_id == candidate.id)
            )
        ]
        result["evidence_claims"] = [
            _fields(
                row,
                (
                    "id",
                    "claim_type",
                    "requirement_keys",
                    "statement_hash",
                    "status",
                    "verification_method",
                    "issuer",
                    "verified_at",
                    "expires_at",
                    "revoked_at",
                    "version",
                ),
            )
            for row in db.scalars(select(EvidenceClaim).where(EvidenceClaim.candidate_id == candidate.id))
        ]
        result["evidence_grants"] = [
            _fields(
                row,
                (
                    "id",
                    "claim_id",
                    "org_id",
                    "vacancy_id",
                    "role_version",
                    "kind",
                    "granted_at",
                    "expires_at",
                    "revoked_at",
                )
                if hasattr(row, "granted_at")
                else (
                    "id",
                    "claim_id",
                    "org_id",
                    "vacancy_id",
                    "role_version",
                    "kind",
                    "created_at",
                    "expires_at",
                    "revoked_at",
                ),
            )
            for row in db.scalars(select(EvidenceGrant).where(EvidenceGrant.candidate_id == candidate.id))
        ]
        result["term_consents"] = [
            _fields(
                row,
                (
                    "id",
                    "vacancy_id",
                    "role_version",
                    "terms_hash",
                    "scope",
                    "created_at",
                    "expires_at",
                    "revoked_at",
                ),
            )
            for row in db.scalars(select(TermConsent).where(TermConsent.candidate_id == candidate.id))
        ]
        result["reservations"] = [
            _fields(row, ("id", "vacancy_id", "role_version", "consented_at", "expires_at", "status"))
            for row in db.scalars(
                select(ExclusiveReservation).where(ExclusiveReservation.candidate_id == candidate.id)
            )
        ]
        result["blocks"] = [
            _fields(row, ("id", "org_id", "created_at"))
            for row in db.scalars(select(CandidateBlock).where(CandidateBlock.candidate_id == candidate.id))
        ]
        pair_ids.update(db.scalars(select(PairCycle.id).where(PairCycle.candidate_id == candidate.id)))
    cards = list(db.scalars(select(DecisionCard).where(DecisionCard.recipient_user_id == user.id)))
    pair_ids.update(card.pair_cycle_id for card in cards)
    pair_ids.update(db.scalars(select(Offer.pair_cycle_id).where(Offer.issued_by == user.id)))
    result["decisions"] = [
        _fields(card, ("id", "pair_cycle_id", "side", "status", "created_at", "expires_at", "answered_at"))
        for card in cards
    ]
    result["process_stages"] = [
        _fields(row, ("id", "pair_cycle_id", "stage", "created_at"))
        for row in db.scalars(select(StageEvent).where(StageEvent.pair_cycle_id.in_(pair_ids)))
    ]
    result["offers"] = [
        _fields(row, ("id", "pair_cycle_id", "status", "created_at", "expires_at", "start_at"))
        for row in db.scalars(select(Offer).where(Offer.pair_cycle_id.in_(pair_ids)))
    ]
    result["authored_messages"] = [
        _fields(row, ("id", "match_id", "body", "created_at"))
        for row in db.scalars(select(Message).where(Message.sender_user_id == user.id))
    ]
    result["authored_attachments"] = [
        _fields(row, ("id", "match_id", "sha256", "size", "created_at"))
        for row in db.scalars(select(Attachment).where(Attachment.uploaded_by == user.id))
    ]
    result["memberships"] = [
        _fields(row, ("id", "org_id", "role", "status", "created_at", "expires_at"))
        for row in db.scalars(select(OrgMember).where(OrgMember.user_id == user.id))
    ]
    preference = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id))
    result["notification_preferences"] = (
        _fields(preference, ("email_opt_in", "in_app_opt_in", "quiet_hours")) if preference else None
    )
    result["document_note"] = (
        "Binary document content is available through authenticated document downloads while the account is active."
    )
    return jsonable_encoder(result)


def _delete_owned_blob(object_ref: str, user_id: str) -> None:
    """Idempotent safe adapter; a reference to another owner is an integrity error."""
    if not object_ref.startswith(str(UUID(user_id)) + "/"):
        raise AppError(409, "OBJECT_OWNER_MISMATCH", "Private object ownership requires review")
    try:
        delete_private(object_ref)
    except AppError as error:
        if error.code != "OBJECT_NOT_FOUND":
            raise


def erase_local_owner_data(db: Session, actor: Actor, user: User) -> None:
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if candidate:
        lock_scopes(db, f"candidate:{candidate.id}", f"user:{user.id}")
        if candidate.resume_object_ref:
            _delete_owned_blob(candidate.resume_object_ref, user.id)
        for claim in db.scalars(select(EvidenceClaim).where(EvidenceClaim.candidate_id == candidate.id)):
            if claim.private_object_ref:
                _delete_owned_blob(claim.private_object_ref, user.id)
            claim.private_object_ref = None
            claim.status, claim.revoked_at = "REVOKED", utcnow()
            claim.issuer = None
            claim.version += 1
        for grant in db.scalars(
            select(EvidenceGrant).where(
                EvidenceGrant.candidate_id == candidate.id, EvidenceGrant.revoked_at.is_(None)
            )
        ):
            grant.revoked_at, grant.version = utcnow(), grant.version + 1
        for consent in db.scalars(
            select(TermConsent).where(
                TermConsent.candidate_id == candidate.id, TermConsent.revoked_at.is_(None)
            )
        ):
            consent.revoked_at, consent.version = utcnow(), consent.version + 1
        for reserve in db.scalars(
            select(ExclusiveReservation).where(
                ExclusiveReservation.candidate_id == candidate.id, ExclusiveReservation.status == "ACTIVE"
            )
        ):
            reserve.status, reserve.version = "RELEASED", reserve.version + 1
        for cycle in db.scalars(
            select(PairCycle).where(PairCycle.candidate_id == candidate.id, PairCycle.closed_at.is_(None))
        ):
            clearing.close_cycle(db, actor, cycle, "CLOSED_WITHDRAWN")
        invalidate_readiness(db, candidate_id=candidate.id, reason="ACCOUNT_DELETED")
        candidate.headline, candidate.summary, candidate.region = "Deleted account", "", ""
        candidate.experiences, candidate.education = [], []
        candidate.role_families, candidate.employment_types, candidate.work_modes, candidate.locations = (
            [],
            [],
            [],
            [],
        )
        candidate.compensation_floor_cipher = candidate.resume_object_ref = None
        candidate.available_from = candidate.available_until = candidate.confirmed_at = None
        candidate.terms_accepted = candidate.privacy_accepted = False
        candidate.state, candidate.version = "DEACTIVATED", candidate.version + 1
        db.execute(delete(CandidateSkill).where(CandidateSkill.candidate_id == candidate.id))
        db.execute(delete(CandidateBlock).where(CandidateBlock.candidate_id == candidate.id))
    # Employer accounts cannot leave actionable cards owned by a disabled user.
    for vacancy in db.scalars(
        select(Vacancy).where(Vacancy.owner_user_id == user.id, Vacancy.state == "ACTIVE")
    ):
        lock_scopes(db, f"vacancy:{vacancy.id}")
        vacancy.state, vacancy.version = "PAUSED", vacancy.version + 1
        clearing.cancel_vacancy_pending(db, actor, vacancy.id, "OWNER_ACCOUNT_DELETED")
        invalidate_readiness(db, vacancy_id=vacancy.id, reason="OWNER_ACCOUNT_DELETED")
        emit(db, actor, "vacancy.paused", vacancy)
    for authorization in db.scalars(
        select(PactAuthorization).where(
            PactAuthorization.signatory_user_id == user.id, PactAuthorization.revoked_at.is_(None)
        )
    ):
        authorization.revoked_at, authorization.version = utcnow(), authorization.version + 1
        authorization.revocation_reason = "ACCOUNT_DELETED"
        policy = db.get(PactPolicy, authorization.policy_id)
        if policy:
            policy.state, policy.version = "REVOKED", policy.version + 1
            for vacancy_id in policy.scope:
                invalidate_readiness(db, vacancy_id=vacancy_id, reason="SIGNATORY_ACCOUNT_DELETED")
            emit(db, actor, "pact.policy_revoked", policy)
    for member in db.scalars(
        select(OrgMember).where(OrgMember.user_id == user.id, OrgMember.status == "ACTIVE")
    ):
        member.status, member.version = "REVOKED", member.version + 1
    for message in db.scalars(select(Message).where(Message.sender_user_id == user.id)):
        message.body, message.attachment_id, message.version = (
            "[Deleted by author]",
            None,
            message.version + 1,
        )
    for attachment in db.scalars(select(Attachment).where(Attachment.uploaded_by == user.id)):
        if attachment.object_ref != "DELETED":
            _delete_owned_blob(attachment.object_ref, user.id)
        # Other participants' messages can reference this attachment. Retain an
        # inaccessible tombstone to preserve referential integrity.
        attachment.object_ref, attachment.size, attachment.version = "DELETED", 0, attachment.version + 1
    for export in db.scalars(
        select(PrivacyRequest).where(PrivacyRequest.user_id == user.id, PrivacyRequest.kind == "EXPORT")
    ):
        export.result_cipher = None
        export.status = "ERASED"
    db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == user.id))
    db.execute(delete(Notification).where(Notification.user_id == user.id))
    preference = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id))
    if preference:
        preference.in_app_opt_in = preference.email_opt_in = False
        preference.quiet_hours = {}
    user.verified_email, user.status, user.platform_roles = "", "DEACTIVATED", []
    user.version += 1


def process_privacy_request(db: Session, actor: Actor, request_id: str) -> None:
    request = db.get(PrivacyRequest, request_id)
    if request is None or request.status != "QUEUED":
        return
    lock_scopes(db, f"privacy:{request.id}", f"user:{request.user_id}")
    request = db.scalar(
        select(PrivacyRequest)
        .where(PrivacyRequest.id == request_id)
        .execution_options(populate_existing=True)
    )
    if request is None or request.status != "QUEUED":
        return
    user = db.get(User, request.user_id)
    if user is None:
        raise AppError(404, "NOT_FOUND", "Privacy account is unavailable")
    if request.kind == "EXPORT":
        if user.status != "ACTIVE":
            request.status = "ACCOUNT_INACTIVE"
            return
        request.result_cipher = encrypt(
            json.dumps(owner_export(db, user), sort_keys=True, separators=(",", ":"))
        )
        request.status = "COMPLETE"
        request.version += 1
        emit(db, actor, "privacy.export_ready", request)
    elif request.kind == "DELETE":
        erase_local_owner_data(db, actor, user)
        request.status = "NEEDS_PROVIDER_REVIEW"
        request.result_cipher = None
        request.version += 1
        emit(db, actor, "privacy.local_erasure_completed", request)
    else:
        raise ValueError("unknown privacy request kind")
