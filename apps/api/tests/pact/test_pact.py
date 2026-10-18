from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, get_ident

import pytest
from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.models import PairCycle, User, VacancyACL
from app.db.pact_models import EvidenceClaim, EvidenceGrant, ExclusiveReservation, PactPolicy, ReadinessProof
from app.schemas import pact as schema
from app.services import pact
from app.services.common import Actor, digest, utcnow
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def role_payload(m, vacancy=None):
    role = vacancy or m.vacancy
    return {"vacancy_id": role.id, "expected_version": role.version, "terms_hash": role.terms_hash}


def authorize(m, vacancy=None):
    payload = schema.CreatePolicy(
        roles=[schema.RoleTerms(**role_payload(m, vacancy))],
        policy_text="Explicit human screening authorization for this exact fictional role.",
        stage="SCREENING",
        expires_at=utcnow() + timedelta(days=3),
    )
    policy = pact.create_policy(m.db, m.signatory_actor, payload)
    return pact.authorize_policy(
        m.db,
        m.signatory_actor,
        policy["id"],
        schema.AuthorizePolicy(
            expected_version=policy["version"], scope_hash=policy["scope_hash"], affirm_human_authority=True
        ),
    )


def verified(m):
    claim = pact.create_claim(
        m.db,
        m.candidate_actor,
        schema.CreateClaim(
            expected_version=m.candidate.version,
            claim_type="LICENSE",
            requirement_keys=[m.essential.key],
            statement="Fictional engineering license attestation.",
            job_related_purpose="Fictional licensed engineering work.",
        ),
    )
    return pact.verify_claim(
        m.db,
        m.verifier_actor,
        claim["id"],
        schema.VerifyClaim(
            expected_version=claim["version"],
            decision="VERIFIED",
            method="ISSUER_CONTACT",
            issuer="Fictional licensing authority",
            source_reference="Fictional independent source checked by the verifier",
            expires_at=utcnow() + timedelta(days=5),
            affirm_independent_check=True,
        ),
    )


def evidence_grant(m, claim):
    return pact.consent_evidence(
        m.db,
        m.candidate_actor,
        schema.ConsentEvidence(
            **role_payload(m),
            claim_id=claim["id"],
            claim_expected_version=claim["version"],
            org_id=m.vacancy.org_id,
            kind="DISCLOSE_SUMMARY",
            consent_text="I authorize this exact employer and role summary.",
            expires_at=utcnow() + timedelta(days=2),
            checkbox_confirmed=True,
        ),
    )


def terms(m):
    return pact.consent_terms(
        m.db,
        m.candidate_actor,
        schema.ConsentTerms(
            **role_payload(m),
            candidate_expected_version=m.candidate.version,
            scope="PRELIMINARY_INTEREST",
            expires_at=utcnow() + timedelta(days=2),
            checkbox_confirmed=True,
        ),
    )


def ready(m):
    authorize(m)
    grant = evidence_grant(m, verified(m))
    terms(m)
    result = pact.check_readiness(
        m.db,
        m.candidate_actor,
        schema.CheckReadiness(
            **role_payload(m), candidate_id=m.candidate.id, candidate_expected_version=m.candidate.version
        ),
    )
    assert result["status"] == "READY", result
    return result, grant


def error(code, operation):
    with pytest.raises(AppError) as raised:
        operation()
    assert raised.value.code == code


def test_pact_ready_is_fresh_and_never_a_hire(pact_market):
    m = pact_market
    proof, _ = ready(m)
    assert pact.require_live_readiness(m.db, m.candidate_actor, proof["proof_id"])["status"] == "READY"
    assert proof["certification_state"] == "CANNOT_CERTIFY"
    assert m.db.scalar(select(func.count()).select_from(PairCycle)) == 0
    assert "offer" in proof["notice"]


def test_pact_evidence_reuse_is_not_employer_disclosure(pact_market):
    m = pact_market
    claim = verified(m)
    assert not pact.has_current_evidence(m.db, m.candidate.id, m.vacancy, m.essential.key)
    error(
        "DISCLOSURE_NOT_CONSENTED",
        lambda: pact.disclosed_claim(m.db, m.signatory_actor, claim["id"], m.vacancy.id),
    )
    evidence_grant(m, claim)
    assert pact.has_current_evidence(m.db, m.candidate.id, m.vacancy, m.essential.key)
    error(
        "DISCLOSURE_NOT_CONSENTED",
        lambda: pact.disclosed_claim(m.db, m.signatory_actor, claim["id"], m.other_vacancy.id),
    )
    view = pact.disclosed_claim(m.db, m.signatory_actor, claim["id"], m.vacancy.id)
    assert "private_object_ref" not in view and "source_reference" not in view and "statement" not in view


def test_pact_revoke_grant_invalidates_proof_and_access(pact_market):
    m = pact_market
    proof, grant = ready(m)
    pact.revoke_consent(m.db, m.candidate_actor, grant["id"], schema.Revoke(expected_version=1))
    assert m.db.get(ReadinessProof, proof["proof_id"]).state == "INVALIDATED"
    assert pact.require_live_readiness(m.db, m.candidate_actor, proof["proof_id"])["status"] == "STALE"
    assert not pact.has_current_evidence(m.db, m.candidate.id, m.vacancy, m.essential.key)


@pytest.mark.parametrize("revoked", ["grant", "claim"])
def test_pact_evidence_access_rechecks_cached_objects_after_revocation(pact_market, pact_engine, revoked):
    m = pact_market
    claim = verified(m)
    grant = evidence_grant(m, claim)
    m.db.commit()
    with Session(pact_engine, expire_on_commit=False) as reader:
        cached_claim = reader.get(EvidenceClaim, claim["id"])
        cached_grant = reader.get(EvidenceGrant, grant["id"])
        assert pact.has_current_evidence(reader, m.candidate.id, m.vacancy, m.essential.key)
        assert cached_claim.status == "VERIFIED" and cached_grant.revoked_at is None

        if revoked == "grant":
            pact.revoke_consent(m.db, m.candidate_actor, grant["id"], schema.Revoke(expected_version=1))
        else:
            pact.revoke_claim(
                m.db, m.candidate_actor, claim["id"], schema.Revoke(expected_version=claim["version"])
            )
        m.db.commit()

        assert not pact.has_current_evidence(reader, m.candidate.id, m.vacancy, m.essential.key)
        error(
            "DISCLOSURE_NOT_CONSENTED",
            lambda: pact.disclosed_claim(reader, m.signatory_actor, claim["id"], m.vacancy.id),
        )


@pytest.mark.concurrency
def test_pact_revocation_wins_while_authorization_waits_for_role_lock(pact_market, pact_engine, monkeypatch):
    m = pact_market
    policy = pact.create_policy(
        m.db,
        m.signatory_actor,
        schema.CreatePolicy(
            roles=[schema.RoleTerms(**role_payload(m))],
            policy_text="Explicit human screening authorization for this fictional role.",
            stage="SCREENING",
            expires_at=utcnow() + timedelta(days=1),
        ),
    )
    m.db.commit()
    lock_requested, main_thread = Event(), get_ident()
    original_lock = pact.lock_scopes

    def observed_lock(db, *keys):
        if get_ident() != main_thread:
            lock_requested.set()
        original_lock(db, *keys)

    monkeypatch.setattr(pact, "lock_scopes", observed_lock)

    def authorize_waiting():
        with Session(pact_engine) as db:
            try:
                pact.authorize_policy(
                    db,
                    m.signatory_actor,
                    policy["id"],
                    schema.AuthorizePolicy(
                        expected_version=1, scope_hash=policy["scope_hash"], affirm_human_authority=True
                    ),
                )
                db.commit()
                return "AUTHORIZED"
            except AppError as exc:
                db.rollback()
                return exc.code

    with Session(pact_engine) as revoker, ThreadPoolExecutor(max_workers=1) as pool:
        revoker.execute(text("SET LOCAL lock_timeout = '3s'"))
        original_lock(revoker, f"vacancy:{m.vacancy.id}")
        future = pool.submit(authorize_waiting)
        try:
            assert lock_requested.wait(5), "Authorization did not reach the role lock"
            result = pact.revoke_policy(
                revoker, m.signatory_actor, policy["id"], schema.Revoke(expected_version=1)
            )
            revoker.commit()
            assert result["state"] == "REVOKED"
        finally:
            revoker.rollback()
        assert future.result(timeout=10) == "VERSION_CONFLICT"


@pytest.mark.parametrize(
    "changed",
    [
        "terms",
        "candidate",
        "evidence_expiry",
        "grant_expiry",
        "authority",
        "proof_hash",
        "requirements",
        "policy_stage",
    ],
)
def test_pact_stale_dependencies_are_rejected(pact_market, changed):
    m = pact_market
    proof, grant = ready(m)
    if changed == "terms":
        m.vacancy.terms_hash = digest("Changed salary terms")
        m.vacancy.version += 1
    elif changed == "candidate":
        m.candidate.version += 1
    elif changed == "evidence_expiry":
        m.db.scalar(select(EvidenceClaim)).expires_at = utcnow() - timedelta(seconds=1)
    elif changed == "grant_expiry":
        m.db.get(EvidenceGrant, grant["id"]).expires_at = utcnow() - timedelta(seconds=1)
    elif changed == "authority":
        m.member.status = "REVOKED"
    elif changed == "proof_hash":
        m.db.get(ReadinessProof, proof["proof_id"]).fingerprint = "0" * 64
    elif changed == "requirements":
        m.essential.version += 1
    elif changed == "policy_stage":
        m.db.scalar(select(PactPolicy)).stage = "CONDITIONAL_OFFER"
    m.db.flush()
    assert pact.require_live_readiness(m.db, m.candidate_actor, proof["proof_id"])["status"] == "STALE"


def test_pact_signatory_requires_db_membership_acl_and_recent_auth(pact_market):
    m = pact_market
    forged = Actor(m.outsider_actor.user_id, utcnow(), ("AUTHORIZED_SIGNATORY",))
    payload = schema.CreatePolicy(
        roles=[schema.RoleTerms(**role_payload(m))],
        policy_text="Fictional policy details.",
        stage="INTERVIEW",
        expires_at=utcnow() + timedelta(days=1),
    )
    error("FORBIDDEN", lambda: pact.create_policy(m.db, forged, payload))
    old = Actor(m.signatory_actor.user_id, utcnow() - timedelta(hours=1))
    error("REAUTH_REQUIRED", lambda: pact.create_policy(m.db, old, payload))
    m.db.scalar(select(VacancyACL).where(VacancyACL.vacancy_id == m.vacancy.id)).can_approve_policy = False
    m.db.flush()
    error("VACANCY_FORBIDDEN", lambda: pact.create_policy(m.db, m.signatory_actor, payload))


def test_pact_policy_exact_scope_and_version(pact_market):
    m = pact_market
    payload = schema.CreatePolicy(
        roles=[schema.RoleTerms(**role_payload(m))],
        policy_text="Fictional policy details.",
        stage="INTERVIEW",
        expires_at=utcnow() + timedelta(days=1),
    )
    policy = pact.create_policy(m.db, m.signatory_actor, payload)
    error(
        "STALE_POLICY_SCOPE",
        lambda: pact.authorize_policy(
            m.db,
            m.signatory_actor,
            policy["id"],
            schema.AuthorizePolicy(expected_version=1, scope_hash="0" * 64, affirm_human_authority=True),
        ),
    )
    m.vacancy.version += 1
    m.db.flush()
    error(
        "VERSION_CONFLICT",
        lambda: pact.authorize_policy(
            m.db,
            m.signatory_actor,
            policy["id"],
            schema.AuthorizePolicy(
                expected_version=1, scope_hash=policy["scope_hash"], affirm_human_authority=True
            ),
        ),
    )
    assert m.db.get(PactPolicy, policy["id"]).state == "DRAFT"


def test_pact_policy_only_signatory_can_read_policy_without_candidate_review(pact_market):
    m = pact_market
    policy = authorize(m)
    acl = m.db.scalar(select(VacancyACL).where(VacancyACL.vacancy_id == m.vacancy.id))
    acl.can_review = False
    m.db.flush()
    assert pact.read_policy(m.db, m.signatory_actor, policy["id"])["id"] == policy["id"]
    error("FORBIDDEN", lambda: pact.read_policy(m.db, m.outsider_actor, policy["id"]))


def test_pact_verifier_independence_and_role_revocation(pact_market):
    m = pact_market
    claim = pact.create_claim(
        m.db,
        m.candidate_actor,
        schema.CreateClaim(
            expected_version=1,
            claim_type="LICENSE",
            requirement_keys=[m.essential.key],
            statement="Fictional license statement.",
            job_related_purpose="Fictional licensed work purpose.",
        ),
    )
    request = schema.VerifyClaim(
        expected_version=1,
        decision="VERIFIED",
        method="ISSUER_CONTACT",
        issuer="Fictional issuer",
        source_reference="Fictional source checked independently.",
        expires_at=utcnow() + timedelta(days=2),
        affirm_independent_check=True,
    )
    forged = Actor(m.candidate_actor.user_id, utcnow(), ("VERIFIER",))
    error("VERIFIER_REQUIRED", lambda: pact.verify_claim(m.db, forged, claim["id"], request))
    m.db.get(User, m.candidate_actor.user_id).platform_roles = ["VERIFIER"]
    m.db.flush()
    error("SELF_VERIFICATION_FORBIDDEN", lambda: pact.verify_claim(m.db, forged, claim["id"], request))
    m.db.get(User, m.verifier_actor.user_id).platform_roles = []
    m.db.flush()
    error("VERIFIER_REQUIRED", lambda: pact.verify_claim(m.db, m.verifier_actor, claim["id"], request))
    assert m.db.get(EvidenceClaim, claim["id"]).status == "PENDING"


def test_pact_no_arbitrary_document_or_false_checkbox(pact_market):
    m = pact_market
    claim = verified(m)
    payload = {
        **role_payload(m),
        "claim_id": claim["id"],
        "claim_expected_version": claim["version"],
        "org_id": m.vacancy.org_id,
        "kind": "DISCLOSE_DOCUMENT",
        "consent_text": "Specific disclosure consent.",
        "expires_at": utcnow() + timedelta(days=1),
        "checkbox_confirmed": True,
    }
    error(
        "DOCUMENT_UNAVAILABLE",
        lambda: pact.consent_evidence(m.db, m.candidate_actor, schema.ConsentEvidence(**payload)),
    )
    with pytest.raises(ValidationError):
        schema.ConsentEvidence(**{**payload, "checkbox_confirmed": False})
    with pytest.raises(ValidationError):
        schema.CreateClaim(
            expected_version=1,
            claim_type="LICENSE",
            requirement_keys=["license"],
            statement="Fictional statement",
            job_related_purpose="Fictional work purpose",
            private_object_ref="someone-elses-file",
        )


def test_pact_document_proxy_checks_current_specific_grant(pact_market, monkeypatch, tmp_path):
    m = pact_market
    monkeypatch.setattr(get_settings(), "local_storage_dir", tmp_path)
    claim = pact.create_claim(
        m.db,
        m.candidate_actor,
        schema.CreateClaim(
            expected_version=1,
            claim_type="LICENSE",
            requirement_keys=[m.essential.key],
            statement="Fictional license statement.",
            job_related_purpose="Fictional licensed work purpose.",
        ),
    )
    content = b"Fictional evidence document. Untrusted text is never executed."
    attached = pact.attach_document(m.db, m.candidate_actor, claim["id"], 1, content, "text/plain")
    assert attached["version"] == 2 and attached["status"] == "PENDING"
    assert pact.document_content(m.db, m.candidate_actor, claim["id"], None) == content
    pact.verify_claim(
        m.db,
        m.verifier_actor,
        claim["id"],
        schema.VerifyClaim(
            expected_version=2,
            decision="VERIFIED",
            method="ISSUER_CONTACT",
            issuer="Fictional issuer",
            source_reference="Independent fictional issuer source.",
            expires_at=utcnow() + timedelta(days=5),
            affirm_independent_check=True,
        ),
    )
    summary = evidence_grant(m, {**attached, "version": 3})
    error(
        "DISCLOSURE_NOT_CONSENTED",
        lambda: pact.document_content(m.db, m.signatory_actor, claim["id"], m.vacancy.id),
    )
    document = pact.consent_evidence(
        m.db,
        m.candidate_actor,
        schema.ConsentEvidence(
            **role_payload(m),
            claim_id=claim["id"],
            claim_expected_version=3,
            org_id=m.vacancy.org_id,
            kind="DISCLOSE_DOCUMENT",
            consent_text="I authorize this exact document disclosure.",
            expires_at=utcnow() + timedelta(days=2),
            checkbox_confirmed=True,
        ),
    )
    assert pact.document_content(m.db, m.signatory_actor, claim["id"], m.vacancy.id) == content
    pact.revoke_consent(m.db, m.candidate_actor, document["id"], schema.Revoke(expected_version=1))
    error(
        "DISCLOSURE_NOT_CONSENTED",
        lambda: pact.document_content(m.db, m.signatory_actor, claim["id"], m.vacancy.id),
    )
    assert pact.disclosed_claim(m.db, m.signatory_actor, claim["id"], m.vacancy.id)["id"] == claim["id"]
    assert summary["kind"] == "DISCLOSE_SUMMARY"


def test_pact_policy_claim_and_terms_revocations_invalidate(pact_market):
    m = pact_market
    proof, _ = ready(m)
    policy = m.db.scalar(select(PactPolicy))
    pact.revoke_policy(m.db, m.signatory_actor, policy.id, schema.Revoke(expected_version=policy.version))
    assert pact.require_live_readiness(m.db, m.candidate_actor, proof["proof_id"])["status"] == "STALE"
    claim = m.db.scalar(select(EvidenceClaim))
    pact.revoke_claim(m.db, m.candidate_actor, claim.id, schema.Revoke(expected_version=claim.version))
    assert not pact.valid_claim(claim)
    consent = pact.consent_ledger(m.db, m.candidate_actor)["terms"][0]
    pact.revoke_consent(
        m.db, m.candidate_actor, consent["id"], schema.Revoke(expected_version=consent["version"])
    )
    assert pact.consent_ledger(m.db, m.candidate_actor)["terms"][0]["revoked_at"] is not None


def test_pact_essential_requirement_cannot_be_waived(pact_market):
    m = pact_market
    error(
        "ESSENTIAL_CANNOT_BE_RELAXED",
        lambda: pact.create_clarification(
            m.db,
            m.signatory_actor,
            schema.CreateClarification(
                **role_payload(m),
                requirement_id=m.essential.id,
                requirement_expected_version=1,
                proposed_text="License would become an optional preference.",
                reason="Synthetic test should reject this waiver.",
                expires_at=utcnow() + timedelta(days=1),
            ),
        ),
    )


@pytest.mark.parametrize("approved", [True, False])
def test_pact_clarification_scoped_approve_and_deny(pact_market, approved):
    m = pact_market
    item = pact.create_clarification(
        m.db,
        m.signatory_actor,
        schema.CreateClarification(
            **role_payload(m, m.other_vacancy),
            requirement_id=m.ambiguous.id,
            requirement_expected_version=1,
            proposed_text="Optional academic preference only.",
            reason="Clarify this ambiguous qualification.",
            expires_at=utcnow() + timedelta(days=1),
        ),
    )
    answer = schema.RespondClarification(
        expected_version=1,
        vacancy_id=m.other_vacancy.id,
        role_version=1,
        requirement_id=m.ambiguous.id,
        approved=approved,
        affirm_human_authority=True,
    )
    result = pact.respond_clarification(m.db, m.signatory_actor, item["id"], answer)
    assert result["status"] == ("APPROVED" if approved else "DENIED")
    assert m.ambiguous.kind == ("PREFERENCE" if approved else "AMBIGUOUS")
    assert m.other_vacancy.version == (2 if approved else 1)
    error("VERSION_CONFLICT", lambda: pact.respond_clarification(m.db, m.signatory_actor, item["id"], answer))


def test_pact_authority_revocation_while_question_pending(pact_market):
    m = pact_market
    item = pact.create_clarification(
        m.db,
        m.signatory_actor,
        schema.CreateClarification(
            **role_payload(m, m.other_vacancy),
            requirement_id=m.ambiguous.id,
            requirement_expected_version=1,
            proposed_text="Optional academic preference only.",
            reason="Clarify this ambiguous qualification.",
            expires_at=utcnow() + timedelta(days=1),
        ),
    )
    m.member.status = "REVOKED"
    m.db.flush()
    error(
        "FORBIDDEN",
        lambda: pact.respond_clarification(
            m.db,
            m.signatory_actor,
            item["id"],
            schema.RespondClarification(
                expected_version=1,
                vacancy_id=m.other_vacancy.id,
                role_version=1,
                requirement_id=m.ambiguous.id,
                approved=True,
                affirm_human_authority=True,
            ),
        ),
    )
    assert m.ambiguous.kind == "AMBIGUOUS"


def test_pact_idor_proof_and_foreign_consent(pact_market):
    m = pact_market
    proof, grant = ready(m)
    error("FORBIDDEN", lambda: pact.require_live_readiness(m.db, m.outsider_actor, proof["proof_id"]))
    error(
        "PROFILE_REQUIRED",
        lambda: pact.revoke_consent(m.db, m.outsider_actor, grant["id"], schema.Revoke(expected_version=1)),
    )


def test_pact_reservations_candidate_only_exclusive_and_releasable(pact_market):
    m = pact_market
    payload = schema.Reserve(
        **role_payload(m),
        candidate_expected_version=1,
        expires_at=utcnow() + timedelta(hours=2),
        consent_text="I consent to an exclusive hold for this exact role.",
        checkbox_confirmed=True,
    )
    item = pact.reserve(m.db, m.candidate_actor, payload)
    error("ALREADY_EXCLUSIVELY_RESERVED", lambda: pact.reserve(m.db, m.candidate_actor, payload))
    pact.release_reservation(m.db, m.candidate_actor, item["id"], schema.Revoke(expected_version=1))
    assert pact.reserve(m.db, m.candidate_actor, payload)["status"] == "ACTIVE"


@pytest.mark.concurrency
def test_pact_concurrent_reservations_exactly_one(pact_market, pact_engine):
    m = pact_market
    m.db.commit()
    payload = schema.Reserve(
        **role_payload(m),
        candidate_expected_version=1,
        expires_at=utcnow() + timedelta(hours=2),
        consent_text="I consent to an exclusive hold for this exact role.",
        checkbox_confirmed=True,
    )

    def attempt(_):
        with Session(pact_engine) as db:
            try:
                pact.reserve(db, m.candidate_actor, payload)
                db.commit()
                return "created"
            except AppError as exc:
                db.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(attempt, range(16)))
    assert outcomes.count("created") == 1
    assert outcomes.count("ALREADY_EXCLUSIVELY_RESERVED") == 15
    assert (
        m.db.scalar(
            select(func.count())
            .select_from(ExclusiveReservation)
            .where(ExclusiveReservation.status == "ACTIVE")
        )
        == 1
    )


def test_pact_db_guard_prevents_double_active_reservation(pact_market):
    m = pact_market
    first = ExclusiveReservation(
        candidate_id=m.candidate.id,
        vacancy_id=m.vacancy.id,
        role_version=1,
        terms_hash=m.vacancy.terms_hash,
        consent_text_hash=digest("Specific consent"),
        expires_at=utcnow() + timedelta(hours=1),
    )
    m.db.add(first)
    m.db.flush()
    with m.db.begin_nested():
        m.db.add(
            ExclusiveReservation(
                candidate_id=m.candidate.id,
                vacancy_id=m.other_vacancy.id,
                role_version=1,
                terms_hash=m.other_vacancy.terms_hash,
                consent_text_hash=digest("Other consent"),
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError):
            m.db.flush()
        m.db.rollback()
