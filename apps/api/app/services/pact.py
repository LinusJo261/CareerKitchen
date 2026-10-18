"""PACT prerequisites, explicit disclosure and current-state agreement readiness.

Caller owns the transaction. No function commits, hires, issues decision cards or
contacts a human. Stored proofs are hints; all uses revalidate current DB state.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Candidate, Organization, Requirement, User, Vacancy
from app.db.pact_models import (
    Clarification,
    EvidenceClaim,
    EvidenceGrant,
    ExclusiveReservation,
    PactAuthorization,
    PactPolicy,
    ReadinessProof,
    TermConsent,
)
from app.schemas import pact as schemas
from app.services.common import (
    Actor,
    digest,
    emit,
    load,
    lock_scopes,
    require_candidate,
    require_org_role,
    require_vacancy,
    require_version,
    utcnow,
)

NOTICE = "Ready means prerequisites verified, not an employment offer or hire"


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def future(value: datetime | None, now: datetime | None = None) -> bool:
    return value is not None and aware(value) > (now or utcnow())


def ttl(value: datetime, days: int = 30) -> None:
    now = utcnow()
    if not now < aware(value) <= now + timedelta(days=days):
        raise AppError(422, "INVALID_EXPIRY", f"Expiry must be in the next {days} days")


def signatory(db: Session, actor: Actor, vacancy_id: str, recent: bool = True) -> Vacancy:
    vacancy = require_vacancy(db, actor, vacancy_id, permission="approve_policy")
    require_org_role(db, actor, vacancy.org_id, {"AUTHORIZED_SIGNATORY"})
    if recent and not timedelta(0) <= utcnow() - aware(actor.auth_time) <= timedelta(minutes=10):
        raise AppError(403, "REAUTH_REQUIRED", "Recent authentication is required for policy approval")
    return vacancy


def require_verifier(db: Session, actor: Actor) -> User:
    # Actor/JWT role flags are insufficient, including after a mid-session revocation.
    user = load(db, User, actor.user_id)
    if user.status != "ACTIVE" or "VERIFIER" not in user.platform_roles:
        raise AppError(403, "VERIFIER_REQUIRED", "An active independent verifier is required")
    return user


def active_vacancy(db: Session, vacancy_id: str) -> Vacancy:
    vacancy = load(db, Vacancy, vacancy_id, lock=True)
    org = load(db, Organization, vacancy.org_id)
    if (
        vacancy.state != "ACTIVE"
        or org.verification_state != "VERIFIED"
        or (vacancy.deadline_at and not future(vacancy.deadline_at))
    ):
        raise AppError(409, "ROLE_UNAVAILABLE", "The verified vacancy must be active")
    return vacancy


def current_terms(vacancy: Vacancy, version: int, terms_hash: str) -> None:
    require_version(vacancy, version)
    if terms_hash != vacancy.terms_hash:
        raise AppError(412, "STALE_TERMS", "The displayed terms have changed")


def requirements_hash(db: Session, vacancy_id: str) -> str:
    requirements = db.scalars(
        select(Requirement).where(Requirement.vacancy_id == vacancy_id).order_by(Requirement.id)
    ).all()
    return digest([(r.id, r.version, r.key, r.kind, r.lawful_reason, r.reviewed_by) for r in requirements])


def invalidate_readiness(
    db: Session,
    *,
    candidate_id: str | None = None,
    vacancy_id: str | None = None,
    reason: str = "DEPENDENCY_CHANGED",
) -> None:
    if candidate_id is None and vacancy_id is None:
        raise ValueError("Invalidation must be scoped")
    query = select(ReadinessProof).where(ReadinessProof.state == "READY")
    if candidate_id:
        query = query.where(ReadinessProof.candidate_id == candidate_id)
    if vacancy_id:
        query = query.where(ReadinessProof.vacancy_id == vacancy_id)
    for proof in db.scalars(query):
        proof.state = "INVALIDATED"
        proof.invalidated_reason = reason
        proof.version += 1


def policy_out(policy: PactPolicy) -> dict:
    return {
        "id": policy.id,
        "version": policy.version,
        "org_id": policy.org_id,
        "policy_text": policy.policy_text,
        "stage": policy.stage,
        "scope": policy.scope,
        "scope_hash": policy.scope_hash,
        "state": policy.state,
        "expires_at": policy.expires_at,
    }


def policy_digest(policy: PactPolicy) -> str:
    return digest(
        {
            "org_id": policy.org_id,
            "roles": policy.scope,
            "policy_text": policy.policy_text,
            "stage": policy.stage,
            "expires_at": aware(policy.expires_at).astimezone(UTC),
        }
    )


def create_policy(db: Session, actor: Actor, request: schemas.CreatePolicy) -> dict:
    ttl(request.expires_at)
    ids = sorted(str(r.vacancy_id) for r in request.roles)
    lock_scopes(db, *(f"vacancy:{i}" for i in ids))
    scope, org_id = {}, None
    for role in request.roles:
        vacancy = signatory(db, actor, str(role.vacancy_id))
        current_terms(vacancy, role.expected_version, role.terms_hash)
        if org_id is not None and org_id != vacancy.org_id:
            raise AppError(422, "CROSS_ORG_POLICY", "A policy must belong to one organization")
        org_id = vacancy.org_id
        if vacancy.state not in {"ACTIVE", "DRAFT"}:
            raise AppError(409, "ROLE_UNAVAILABLE", "The role cannot be authorized")
        scope[vacancy.id] = {
            "version": vacancy.version,
            "terms_hash": vacancy.terms_hash,
            "requirements_hash": requirements_hash(db, vacancy.id),
        }
    policy = PactPolicy(
        org_id=org_id,
        policy_text=request.policy_text,
        stage=request.stage,
        scope=scope,
        expires_at=request.expires_at,
    )
    policy.scope_hash = policy_digest(policy)
    db.add(policy)
    db.flush()
    emit(db, actor, "pact.policy_created", policy, org_id=org_id)
    return policy_out(policy)


def read_policy(db: Session, actor: Actor, policy_id: str) -> dict:
    policy = load(db, PactPolicy, policy_id)
    for vacancy_id in policy.scope:
        try:
            require_vacancy(db, actor, vacancy_id)
        except AppError as exc:
            if exc.status != 403:
                raise
            # A policy-only signatory need not receive candidate review rights.
            signatory(db, actor, vacancy_id, recent=False)
    return policy_out(policy)


def authorize_policy(db: Session, actor: Actor, policy_id: str, request: schemas.AuthorizePolicy) -> dict:
    initial = load(db, PactPolicy, policy_id)
    lock_scopes(db, *(f"vacancy:{i}" for i in sorted(initial.scope)))
    policy = load(db, PactPolicy, policy_id, lock=True)
    require_version(policy, request.expected_version)
    if policy.state != "DRAFT" or not future(policy.expires_at):
        raise AppError(409, "POLICY_UNAVAILABLE", "Policy must be a current draft")
    if request.scope_hash != policy.scope_hash or policy_digest(policy) != policy.scope_hash:
        raise AppError(412, "STALE_POLICY_SCOPE", "Exact policy scope must match")
    for vacancy_id, scope in policy.scope.items():
        vacancy = signatory(db, actor, vacancy_id)
        current_terms(vacancy, scope["version"], scope["terms_hash"])
        if requirements_hash(db, vacancy_id) != scope["requirements_hash"]:
            raise AppError(412, "STALE_REQUIREMENTS", "Requirements have changed")
    auth = PactAuthorization(
        policy_id=policy.id,
        signatory_user_id=actor.user_id,
        scope_hash=policy.scope_hash,
        authenticated_at=actor.auth_time,
    )
    db.add(auth)
    policy.state = "AUTHORIZED"
    policy.version += 1
    db.flush()
    emit(db, actor, "pact.policy_authorized", policy, org_id=policy.org_id)
    return {**policy_out(policy), "authorization_id": auth.id}


def revoke_policy(db: Session, actor: Actor, policy_id: str, request: schemas.Revoke) -> dict:
    initial = load(db, PactPolicy, policy_id)
    lock_scopes(db, *(f"vacancy:{i}" for i in sorted(initial.scope)))
    policy = load(db, PactPolicy, policy_id, lock=True)
    for vacancy_id in sorted(policy.scope):
        signatory(db, actor, vacancy_id, recent=False)
    require_version(policy, request.expected_version)
    if policy.state == "REVOKED":
        raise AppError(409, "POLICY_REVOKED", "Policy is already revoked")
    auth = db.scalar(select(PactAuthorization).where(PactAuthorization.policy_id == policy.id))
    if auth:
        auth.revoked_at = utcnow()
        auth.revocation_reason = request.reason
        auth.version += 1
    policy.state = "REVOKED"
    policy.version += 1
    for vacancy_id in policy.scope:
        invalidate_readiness(db, vacancy_id=vacancy_id, reason="POLICY_REVOKED")
    emit(db, actor, "pact.policy_revoked", policy, org_id=policy.org_id)
    return policy_out(policy)


def claim_out(claim: EvidenceClaim) -> dict:
    # No object reference, source reference, blob, raw statement or verifier PII.
    return {
        "id": claim.id,
        "version": claim.version,
        "candidate_id": claim.candidate_id,
        "claim_type": claim.claim_type,
        "requirement_keys": claim.requirement_keys,
        "statement_hash": claim.statement_hash,
        "status": claim.status,
        "verified_at": claim.verified_at,
        "expires_at": claim.expires_at,
        "has_document": claim.private_object_ref is not None,
    }


def attach_document(
    db: Session, actor: Actor, claim_id: str, expected_version: int, content: bytes, mime: str
) -> dict:
    from app.integrations.storage import store_resume

    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    claim = load(db, EvidenceClaim, claim_id, lock=True)
    if claim.candidate_id != candidate.id:
        raise AppError(403, "FORBIDDEN", "Only the candidate may attach claim evidence")
    require_version(claim, expected_version)
    if claim.status != "PENDING" or claim.private_object_ref:
        raise AppError(
            409, "CLAIM_DOCUMENT_IMMUTABLE", "Attach one document before the independent verification"
        )
    stored = store_resume(content, mime, candidate.user_id)
    claim.private_object_ref = stored.object_key
    claim.version += 1
    emit(db, actor, "candidate.evidence_document_attached", claim)
    return claim_out(claim)


def document_content(db: Session, actor: Actor, claim_id: str, vacancy_id: str | None) -> bytes:
    from app.integrations.storage import read_private

    claim = load(db, EvidenceClaim, claim_id)
    lock_scopes(db, f"candidate:{claim.candidate_id}", *([f"vacancy:{vacancy_id}"] if vacancy_id else []))
    claim = load(db, EvidenceClaim, claim_id)
    candidate = load(db, Candidate, claim.candidate_id)
    org_id = None
    if candidate.user_id != actor.user_id:
        if vacancy_id is None:
            raise AppError(
                403, "EXACT_VACANCY_REQUIRED", "Document access requires an exact consented vacancy"
            )
        vacancy = require_vacancy(db, actor, vacancy_id)
        active_vacancy(db, vacancy_id)
        if not any(
            c.id == claim.id and g.kind == "DISCLOSE_DOCUMENT"
            for c, g in current_evidence(db, candidate.id, vacancy)
        ):
            raise AppError(
                403, "DISCLOSURE_NOT_CONSENTED", "A current document-specific disclosure grant is required"
            )
        org_id = vacancy.org_id
    if not claim.private_object_ref:
        raise AppError(404, "DOCUMENT_UNAVAILABLE", "No evidence document is attached")
    emit(db, actor, "evidence.document_accessed", claim, org_id=org_id)
    return read_private(claim.private_object_ref)


def create_claim(db: Session, actor: Actor, request: schemas.CreateClaim) -> dict:
    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    candidate = load(db, Candidate, candidate.id)
    require_version(candidate, request.expected_version)
    claim = EvidenceClaim(
        candidate_id=candidate.id,
        claim_type=request.claim_type,
        requirement_keys=request.requirement_keys,
        statement_hash=digest(request.statement),
    )
    db.add(claim)
    db.flush()
    emit(db, actor, "candidate.evidence_pending", claim)
    return claim_out(claim)


def list_claims(db: Session, actor: Actor) -> list[dict]:
    candidate = require_candidate(db, actor)
    return [
        claim_out(c)
        for c in db.scalars(
            select(EvidenceClaim)
            .where(EvidenceClaim.candidate_id == candidate.id)
            .order_by(EvidenceClaim.created_at.desc())
            .limit(200)
        )
    ]


def verify_claim(db: Session, actor: Actor, claim_id: str, request: schemas.VerifyClaim) -> dict:
    require_verifier(db, actor)
    initial = load(db, EvidenceClaim, claim_id)
    lock_scopes(db, f"candidate:{initial.candidate_id}")
    claim = load(db, EvidenceClaim, claim_id, lock=True)
    candidate = load(db, Candidate, claim.candidate_id)
    if candidate.user_id == actor.user_id:
        raise AppError(403, "SELF_VERIFICATION_FORBIDDEN", "Evidence requires an independent verifier")
    require_version(claim, request.expected_version)
    if claim.status != "PENDING":
        raise AppError(409, "CLAIM_NOT_PENDING", "Only pending evidence can be attested")
    ttl(request.expires_at, days=366)
    claim.status = request.decision
    claim.issuer = request.issuer
    claim.verification_method = request.method
    claim.source_reference_hash = digest(request.source_reference)
    claim.verifier_user_id = actor.user_id
    claim.verified_at = utcnow() if request.decision == "VERIFIED" else None
    claim.expires_at = request.expires_at
    claim.version += 1
    invalidate_readiness(db, candidate_id=candidate.id, reason="EVIDENCE_CHANGED")
    emit(db, actor, "candidate.evidence_changed", claim)
    return claim_out(claim)


def revoke_claim(db: Session, actor: Actor, claim_id: str, request: schemas.Revoke) -> dict:
    initial = load(db, EvidenceClaim, claim_id)
    lock_scopes(db, f"candidate:{initial.candidate_id}")
    claim = load(db, EvidenceClaim, claim_id, lock=True)
    candidate = load(db, Candidate, claim.candidate_id)
    if candidate.user_id != actor.user_id:
        require_verifier(db, actor)
    require_version(claim, request.expected_version)
    if claim.revoked_at:
        raise AppError(409, "CLAIM_REVOKED", "Claim is already revoked")
    claim.status, claim.revoked_at = "REVOKED", utcnow()
    claim.version += 1
    invalidate_readiness(db, candidate_id=candidate.id, reason="EVIDENCE_REVOKED")
    emit(db, actor, "candidate.evidence_changed", claim)
    return claim_out(claim)


def valid_claim(claim: EvidenceClaim) -> bool:
    return (
        claim.status == "VERIFIED"
        and claim.revoked_at is None
        and future(claim.expires_at)
        and claim.verifier_user_id is not None
        and claim.verified_at is not None
        and bool(claim.verification_method)
        and bool(claim.source_reference_hash)
    )


def grant_out(grant: EvidenceGrant) -> dict:
    return {
        "id": grant.id,
        "version": grant.version,
        "claim_id": grant.claim_id,
        "vacancy_id": grant.vacancy_id,
        "org_id": grant.org_id,
        "role_version": grant.role_version,
        "kind": grant.kind,
        "expires_at": grant.expires_at,
        "revoked_at": grant.revoked_at,
    }


def consent_evidence(db: Session, actor: Actor, request: schemas.ConsentEvidence) -> dict:
    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{request.vacancy_id}")
    vacancy = active_vacancy(db, str(request.vacancy_id))
    claim = load(db, EvidenceClaim, str(request.claim_id), lock=True)
    if claim.candidate_id != candidate.id or str(request.org_id) != vacancy.org_id:
        raise AppError(403, "INVALID_CONSENT_SCOPE", "Consent must cover your claim and the exact employer")
    current_terms(vacancy, request.expected_version, request.terms_hash)
    require_version(claim, request.claim_expected_version)
    ttl(request.expires_at)
    if (
        not valid_claim(claim)
        or claim.expires_at is None
        or aware(request.expires_at) > aware(claim.expires_at)
    ):
        raise AppError(409, "EVIDENCE_UNAVAILABLE", "Evidence must remain verified for the consent duration")
    if request.kind == "DISCLOSE_DOCUMENT" and not claim.private_object_ref:
        raise AppError(409, "DOCUMENT_UNAVAILABLE", "No privately stored verified document is attached")
    grant = EvidenceGrant(
        claim_id=claim.id,
        candidate_id=candidate.id,
        org_id=vacancy.org_id,
        vacancy_id=vacancy.id,
        role_version=vacancy.version,
        terms_hash=vacancy.terms_hash,
        kind=request.kind,
        expires_at=request.expires_at,
        consent_text_hash=digest(request.consent_text),
    )
    db.add(grant)
    db.flush()
    invalidate_readiness(db, candidate_id=candidate.id, vacancy_id=vacancy.id, reason="CONSENT_CHANGED")
    emit(db, actor, "candidate.consent_granted", grant, org_id=vacancy.org_id)
    return grant_out(grant)


def valid_grant(grant: EvidenceGrant, vacancy: Vacancy) -> bool:
    return (
        grant.revoked_at is None
        and future(grant.expires_at)
        and grant.org_id == vacancy.org_id
        and grant.vacancy_id == vacancy.id
        and grant.role_version == vacancy.version
        and grant.terms_hash == vacancy.terms_hash
    )


def current_evidence(
    db: Session, candidate_id: str, vacancy: Vacancy
) -> list[tuple[EvidenceClaim, EvidenceGrant]]:
    rows = db.execute(
        select(EvidenceClaim, EvidenceGrant)
        .join(EvidenceGrant, EvidenceGrant.claim_id == EvidenceClaim.id)
        .where(
            EvidenceClaim.candidate_id == candidate_id,
            EvidenceGrant.candidate_id == candidate_id,
            EvidenceGrant.vacancy_id == vacancy.id,
            EvidenceGrant.org_id == vacancy.org_id,
        )
        .execution_options(populate_existing=True)
    ).all()
    return [(c, g) for c, g in rows if valid_claim(c) and valid_grant(g, vacancy)]


def has_current_evidence(db: Session, candidate_id: str, vacancy: Vacancy, requirement_key: str) -> bool:
    return any(requirement_key in c.requirement_keys for c, _ in current_evidence(db, candidate_id, vacancy))


def disclosed_claim(db: Session, actor: Actor, claim_id: str, vacancy_id: str) -> dict:
    initial = load(db, EvidenceClaim, claim_id)
    lock_scopes(db, f"candidate:{initial.candidate_id}", f"vacancy:{vacancy_id}")
    vacancy = require_vacancy(db, actor, vacancy_id)
    claim = load(db, EvidenceClaim, claim_id)
    active_vacancy(db, vacancy_id)
    if not any(c.id == claim_id for c, _ in current_evidence(db, claim.candidate_id, vacancy)):
        raise AppError(
            403, "DISCLOSURE_NOT_CONSENTED", "A current exact-vacancy disclosure grant is required"
        )
    emit(db, actor, "evidence.summary_accessed", claim, org_id=vacancy.org_id)
    return claim_out(claim)


def consent_out(consent: TermConsent) -> dict:
    return {
        "id": consent.id,
        "version": consent.version,
        "vacancy_id": consent.vacancy_id,
        "role_version": consent.role_version,
        "terms_hash": consent.terms_hash,
        "scope": consent.scope,
        "expires_at": consent.expires_at,
        "revoked_at": consent.revoked_at,
    }


def consent_terms(db: Session, actor: Actor, request: schemas.ConsentTerms) -> dict:
    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{request.vacancy_id}")
    candidate = load(db, Candidate, candidate.id)
    require_version(candidate, request.candidate_expected_version)
    vacancy = active_vacancy(db, str(request.vacancy_id))
    current_terms(vacancy, request.expected_version, request.terms_hash)
    ttl(request.expires_at)
    consent = TermConsent(
        candidate_id=candidate.id,
        vacancy_id=vacancy.id,
        role_version=vacancy.version,
        terms_hash=vacancy.terms_hash,
        scope=request.scope,
        expires_at=request.expires_at,
    )
    db.add(consent)
    db.flush()
    invalidate_readiness(db, candidate_id=candidate.id, vacancy_id=vacancy.id, reason="TERMS_CONSENT_CHANGED")
    emit(db, actor, "candidate.consent_granted", consent, org_id=vacancy.org_id)
    return consent_out(consent)


def consent_ledger(db: Session, actor: Actor) -> dict:
    candidate = require_candidate(db, actor)
    terms = db.scalars(
        select(TermConsent)
        .where(TermConsent.candidate_id == candidate.id)
        .order_by(TermConsent.created_at.desc())
        .limit(200)
    )
    grants = db.scalars(
        select(EvidenceGrant)
        .where(EvidenceGrant.candidate_id == candidate.id)
        .order_by(EvidenceGrant.created_at.desc())
        .limit(200)
    )
    return {"terms": [consent_out(c) for c in terms], "evidence": [grant_out(g) for g in grants]}


def revoke_consent(db: Session, actor: Actor, consent_id: str, request: schemas.Revoke) -> dict:
    candidate = require_candidate(db, actor)
    consent = db.get(EvidenceGrant, consent_id) or db.get(TermConsent, consent_id)
    if consent is None:
        raise AppError(404, "NOT_FOUND", "Consent was not found")
    if consent.candidate_id != candidate.id:
        raise AppError(403, "FORBIDDEN", "Only the owner can revoke consent")
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{consent.vacancy_id}")
    consent = load(db, type(consent), consent_id, lock=True)
    require_version(consent, request.expected_version)
    if consent.revoked_at:
        raise AppError(409, "CONSENT_REVOKED", "Consent is already revoked")
    consent.revoked_at = utcnow()
    consent.version += 1
    invalidate_readiness(
        db, candidate_id=candidate.id, vacancy_id=consent.vacancy_id, reason="CONSENT_REVOKED"
    )
    emit(db, actor, "candidate.consent_revoked", consent)
    return grant_out(consent) if isinstance(consent, EvidenceGrant) else consent_out(consent)


def evaluator(db: Session, actor: Actor, candidate_id: str, vacancy_id: str) -> tuple[Candidate, Vacancy]:
    candidate = load(db, Candidate, candidate_id)
    vacancy = load(db, Vacancy, vacancy_id)
    if candidate.user_id != actor.user_id:
        require_vacancy(db, actor, vacancy_id)
        # A member may not probe undisclosed candidates' readiness by guessed UUID.
        if not current_evidence(db, candidate_id, vacancy):
            raise AppError(403, "CANDIDATE_NOT_DISCLOSED", "Candidate has not consented to this vacancy")
    return candidate, vacancy


def readiness_state(db: Session, candidate: Candidate, vacancy: Vacancy) -> dict[str, Any]:
    now, reasons = utcnow(), []
    org = load(db, Organization, vacancy.org_id)
    if candidate.state != "ACTIVE" or vacancy.state != "ACTIVE" or org.verification_state != "VERIFIED":
        reasons.append("PARTICIPANT_UNAVAILABLE")
    from app.services.clearing import feasible

    eligible, _ = feasible(db, candidate, vacancy)
    if not eligible:
        reasons.append("CURRENT_REQUIREMENTS_NOT_MET")
    policies = db.execute(
        select(PactPolicy, PactAuthorization)
        .join(PactAuthorization, PactAuthorization.policy_id == PactPolicy.id)
        .where(PactPolicy.org_id == vacancy.org_id, PactPolicy.state == "AUTHORIZED")
        .order_by(PactAuthorization.approved_at.desc())
    ).all()
    selected = None
    for policy, auth in policies:
        scope = policy.scope.get(vacancy.id)
        if (
            not scope
            or scope["version"] != vacancy.version
            or scope["terms_hash"] != vacancy.terms_hash
            or scope["requirements_hash"] != requirements_hash(db, vacancy.id)
            or policy.scope_hash != policy_digest(policy)
            or auth.scope_hash != policy.scope_hash
            or auth.revoked_at
            or not future(policy.expires_at, now)
        ):
            continue
        try:
            author = load(db, User, auth.signatory_user_id)
            if author.status != "ACTIVE":
                continue
            signatory(db, Actor(user_id=author.id, auth_time=auth.authenticated_at), vacancy.id, recent=False)
        except AppError:
            continue
        selected = (policy, auth)
        break
    if selected is None:
        reasons.append("CURRENT_AUTHORIZATION_REQUIRED")
    consents = db.scalars(
        select(TermConsent)
        .where(TermConsent.candidate_id == candidate.id, TermConsent.vacancy_id == vacancy.id)
        .order_by(TermConsent.created_at.desc())
    ).all()
    consent = next(
        (
            c
            for c in consents
            if c.revoked_at is None
            and future(c.expires_at, now)
            and c.role_version == vacancy.version
            and c.terms_hash == vacancy.terms_hash
        ),
        None,
    )
    if consent is None:
        reasons.append("CURRENT_TERMS_CONSENT_REQUIRED")
    evidence = current_evidence(db, candidate.id, vacancy)
    requirements = db.scalars(select(Requirement).where(Requirement.vacancy_id == vacancy.id)).all()
    if any(r.kind == "AMBIGUOUS" or not r.reviewed_by for r in requirements):
        reasons.append("HUMAN_REQUIREMENT_REVIEW_REQUIRED")
    if any(
        r.kind == "ESSENTIAL" and not any(r.key in c.requirement_keys for c, _ in evidence)
        for r in requirements
    ):
        reasons.append("VERIFIED_CONSENTED_EVIDENCE_REQUIRED")
    if reasons:
        return {"ready": False, "reasons": sorted(set(reasons))}
    assert selected is not None and consent is not None
    policy, auth = selected
    expiries = [now + timedelta(minutes=5), aware(policy.expires_at), aware(consent.expires_at)]
    for claim, grant in evidence:
        assert claim.expires_at is not None
        expiries.extend([aware(claim.expires_at), aware(grant.expires_at)])
    expiry = min(expiries)
    fingerprint = digest(
        {
            "candidate": [candidate.id, candidate.version],
            "role": [vacancy.id, vacancy.version, vacancy.terms_hash, requirements_hash(db, vacancy.id)],
            "authorization": [auth.id, auth.version, auth.scope_hash],
            "consent": [consent.id, consent.version],
            "evidence": sorted((c.id, c.version, g.id, g.version) for c, g in evidence),
        }
    )
    return {
        "ready": True,
        "reasons": [],
        "authorization_id": auth.id,
        "fingerprint": fingerprint,
        "expires_at": expiry,
    }


def readiness_out(status: str, proof: ReadinessProof | None = None, reasons: list | None = None) -> dict:
    return {
        "status": status,
        "proof_id": proof.id if proof else None,
        "version": proof.version if proof else None,
        "expires_at": proof.expires_at if proof else None,
        "public_reason_codes": reasons or [],
        "notice": NOTICE,
        "certification_state": "CANNOT_CERTIFY",
    }


def check_readiness(db: Session, actor: Actor, request: schemas.CheckReadiness) -> dict:
    lock_scopes(db, f"candidate:{request.candidate_id}", f"vacancy:{request.vacancy_id}")
    candidate, vacancy = evaluator(db, actor, str(request.candidate_id), str(request.vacancy_id))
    current_terms(vacancy, request.expected_version, request.terms_hash)
    require_version(candidate, request.candidate_expected_version)
    state = readiness_state(db, candidate, vacancy)
    if not state["ready"]:
        return readiness_out("NOT_READY", reasons=state["reasons"])
    proof = ReadinessProof(
        candidate_id=candidate.id,
        vacancy_id=vacancy.id,
        role_version=vacancy.version,
        authorization_id=state["authorization_id"],
        terms_hash=vacancy.terms_hash,
        fingerprint=state["fingerprint"],
        expires_at=state["expires_at"],
    )
    db.add(proof)
    db.flush()
    emit(db, actor, "pact.readiness_issued", proof, org_id=vacancy.org_id)
    return readiness_out("READY", proof)


def require_live_readiness(db: Session, actor: Actor, proof_id: str) -> dict:
    initial = load(db, ReadinessProof, proof_id)
    lock_scopes(db, f"candidate:{initial.candidate_id}", f"vacancy:{initial.vacancy_id}")
    proof = load(db, ReadinessProof, proof_id)
    candidate, vacancy = evaluator(db, actor, proof.candidate_id, proof.vacancy_id)
    state = readiness_state(db, candidate, vacancy)
    if (
        proof.state != "READY"
        or not future(proof.expires_at)
        or not state["ready"]
        or state["fingerprint"] != proof.fingerprint
        or vacancy.terms_hash != proof.terms_hash
        or vacancy.version != proof.role_version
    ):
        return readiness_out("STALE", proof, ["CURRENT_PREREQUISITES_CHANGED"])
    return readiness_out("READY", proof)


def clarification_out(item: Clarification) -> dict:
    return {
        "id": item.id,
        "version": item.version,
        "vacancy_id": item.vacancy_id,
        "requirement_id": item.requirement_id,
        "role_version": item.role_version,
        "proposed_kind": item.proposed_kind,
        "proposed_text": item.proposed_text,
        "status": item.status,
        "expires_at": item.expires_at,
    }


def create_clarification(db: Session, actor: Actor, request: schemas.CreateClarification) -> dict:
    lock_scopes(db, f"vacancy:{request.vacancy_id}")
    vacancy = signatory(db, actor, str(request.vacancy_id))
    current_terms(vacancy, request.expected_version, request.terms_hash)
    requirement = load(db, Requirement, str(request.requirement_id), lock=True)
    if requirement.vacancy_id != vacancy.id:
        raise AppError(403, "INVALID_REQUIREMENT_SCOPE", "Requirement must belong to the exact role")
    require_version(requirement, request.requirement_expected_version)
    if requirement.kind == "ESSENTIAL" or requirement.lawful_reason:
        raise AppError(
            409,
            "ESSENTIAL_CANNOT_BE_RELAXED",
            "Essential or legally required qualifications cannot be relaxed",
        )
    ttl(request.expires_at, days=7)
    item = Clarification(
        org_id=vacancy.org_id,
        vacancy_id=vacancy.id,
        requirement_id=requirement.id,
        role_version=vacancy.version,
        requirement_version=requirement.version,
        proposed_kind=request.proposed_kind,
        proposed_text=request.proposed_text,
        reason=request.reason,
        requested_by=actor.user_id,
        expires_at=request.expires_at,
    )
    db.add(item)
    db.flush()
    emit(db, actor, "pact.clarification_requested", item, org_id=vacancy.org_id)
    return clarification_out(item)


def respond_clarification(
    db: Session, actor: Actor, clarification_id: str, request: schemas.RespondClarification
) -> dict:
    item = load(db, Clarification, clarification_id)
    lock_scopes(db, f"vacancy:{item.vacancy_id}")
    item = load(db, Clarification, clarification_id, lock=True)
    vacancy = signatory(db, actor, item.vacancy_id)
    require_version(item, request.expected_version)
    if (
        str(request.vacancy_id) != item.vacancy_id
        or str(request.requirement_id) != item.requirement_id
        or request.role_version != item.role_version
    ):
        raise AppError(403, "INVALID_CLARIFICATION_SCOPE", "Approval must enumerate the original exact scope")
    require_version(vacancy, item.role_version)
    requirement = load(db, Requirement, item.requirement_id, lock=True)
    require_version(requirement, item.requirement_version)
    if item.status != "REQUESTED" or not future(item.expires_at):
        raise AppError(409, "CLARIFICATION_UNAVAILABLE", "Clarification is resolved or expired")
    if requirement.kind == "ESSENTIAL" or requirement.lawful_reason:
        raise AppError(409, "ESSENTIAL_CANNOT_BE_RELAXED", "Essential qualifications cannot be relaxed")
    item.status = "APPROVED" if request.approved else "DENIED"
    item.responded_by, item.responded_at = actor.user_id, utcnow()
    item.version += 1
    if request.approved:
        from app.services.clearing import cancel_vacancy_pending
        from app.services.profiles import refresh_terms

        requirement.kind, requirement.description = item.proposed_kind, item.proposed_text
        requirement.reviewed_by = actor.user_id
        requirement.version += 1
        vacancy.version += 1
        refresh_terms(db, vacancy)
        cancel_vacancy_pending(db, actor, vacancy.id, "REQUIREMENT_CLARIFIED")
        invalidate_readiness(db, vacancy_id=vacancy.id, reason="REQUIREMENT_CLARIFIED")
    emit(db, actor, "pact.clarification_resolved", item, org_id=vacancy.org_id)
    return clarification_out(item)


def reservation_out(item: ExclusiveReservation) -> dict:
    return {
        "id": item.id,
        "version": item.version,
        "candidate_id": item.candidate_id,
        "vacancy_id": item.vacancy_id,
        "role_version": item.role_version,
        "status": item.status,
        "expires_at": item.expires_at,
    }


def reserve(db: Session, actor: Actor, request: schemas.Reserve) -> dict:
    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{request.vacancy_id}")
    candidate = load(db, Candidate, candidate.id)
    require_version(candidate, request.candidate_expected_version)
    vacancy = active_vacancy(db, str(request.vacancy_id))
    current_terms(vacancy, request.expected_version, request.terms_hash)
    if candidate.state != "ACTIVE":
        raise AppError(409, "CANDIDATE_UNAVAILABLE", "Candidate must be active")
    if not utcnow() < aware(request.expires_at) <= utcnow() + timedelta(hours=24):
        raise AppError(422, "INVALID_RESERVATION_EXPIRY", "Exclusive reservations may last at most 24 hours")
    for existing in db.scalars(
        select(ExclusiveReservation)
        .where(ExclusiveReservation.candidate_id == candidate.id, ExclusiveReservation.status == "ACTIVE")
        .with_for_update()
    ):
        if future(existing.expires_at):
            raise AppError(
                409, "ALREADY_EXCLUSIVELY_RESERVED", "Candidate already has a current exclusive reservation"
            )
        existing.status = "EXPIRED"
        existing.version += 1
        emit(db, actor, "candidate.reservation_expired", existing)
    db.flush()
    item = ExclusiveReservation(
        candidate_id=candidate.id,
        vacancy_id=vacancy.id,
        role_version=vacancy.version,
        terms_hash=vacancy.terms_hash,
        consent_text_hash=digest(request.consent_text),
        expires_at=request.expires_at,
    )
    db.add(item)
    db.flush()
    emit(db, actor, "candidate.reservation_consented", item, org_id=vacancy.org_id)
    return reservation_out(item)


def release_reservation(db: Session, actor: Actor, reservation_id: str, request: schemas.Revoke) -> dict:
    initial = load(db, ExclusiveReservation, reservation_id)
    lock_scopes(db, f"candidate:{initial.candidate_id}", f"vacancy:{initial.vacancy_id}")
    item = load(db, ExclusiveReservation, reservation_id, lock=True)
    candidate = require_candidate(db, actor)
    if candidate.id != item.candidate_id:
        raise AppError(403, "FORBIDDEN", "Only the candidate may release this reservation")
    require_version(item, request.expected_version)
    if item.status != "ACTIVE":
        raise AppError(409, "RESERVATION_UNAVAILABLE", "Reservation is no longer active")
    item.status = "RELEASED"
    item.version += 1
    emit(db, actor, "candidate.reservation_released", item)
    return reservation_out(item)
