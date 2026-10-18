"""Authenticated PACT, consent, evidence and voluntary reservation contracts."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.models import MutualMatch, PairCycle, User, Vacancy
from app.db.pact_models import Clarification, PactAuthorization, PactPolicy
from app.schemas import pact as schema
from app.schemas import responses as r
from app.services import pact
from app.services.clearing import POST_MATCH
from app.services.common import Actor, require_candidate, require_org_role, require_vacancy, utcnow

router = APIRouter(route_class=TransactionalRoute, tags=["PACT and consent"])


@router.get("/organizations/{org_id}/pact/policies", response_model=r.Envelope[list[r.PolicyOut]])
def list_policies(org_id: UUID, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    require_org_role(
        db, actor, str(org_id), {"ORG_ADMIN", "RECRUITER", "HIRING_MANAGER", "AUTHORIZED_SIGNATORY"}
    )
    rows = []
    for policy in db.scalars(
        select(PactPolicy)
        .where(PactPolicy.org_id == str(org_id))
        .order_by(PactPolicy.created_at.desc())
        .limit(200)
    ):
        try:
            rows.append(pact.read_policy(db, actor, policy.id))
        except AppError as exc:
            if exc.status != 403:
                raise
    return {"data": rows}


@router.get("/candidates/me/pact/policies", response_model=r.Envelope[list[r.PolicyOut]])
def candidate_policies(db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    candidate = require_candidate(db, actor)
    vacancies = {
        v.id: v
        for v in db.scalars(
            select(Vacancy)
            .join(PairCycle, PairCycle.vacancy_id == Vacancy.id)
            .join(MutualMatch, MutualMatch.pair_cycle_id == PairCycle.id)
            .where(
                PairCycle.candidate_id == candidate.id,
                PairCycle.closed_at.is_(None),
                PairCycle.state.in_(POST_MATCH),
                PairCycle.candidate_interested_at.is_not(None),
                PairCycle.employer_interested_at.is_not(None),
                MutualMatch.status == "ACTIVE",
            )
        )
    }
    result = []
    if vacancies:
        for policy in db.scalars(
            select(PactPolicy)
            .where(
                PactPolicy.org_id.in_({v.org_id for v in vacancies.values()}),
                PactPolicy.state == "AUTHORIZED",
                PactPolicy.expires_at > utcnow(),
            )
            .order_by(PactPolicy.created_at.desc())
            .limit(200)
        ):
            auth = db.scalar(select(PactAuthorization).where(PactAuthorization.policy_id == policy.id))
            if (
                auth is None
                or auth.revoked_at
                or auth.scope_hash != policy.scope_hash
                or pact.policy_digest(policy) != policy.scope_hash
            ):
                continue
            author = db.get(User, auth.signatory_user_id)
            if author is None or author.status != "ACTIVE":
                continue
            scope = {
                key: value
                for key, value in policy.scope.items()
                if key in vacancies
                and value["version"] == vacancies[key].version
                and value["terms_hash"] == vacancies[key].terms_hash
                and value["requirements_hash"] == pact.requirements_hash(db, key)
            }
            for vacancy_id in tuple(scope):
                try:
                    pact.signatory(db, Actor(author.id, auth.authenticated_at), vacancy_id, recent=False)
                except AppError:
                    del scope[vacancy_id]
            if scope:
                result.append({**pact.policy_out(policy), "scope": scope})
    return {"data": result}


@router.get(
    "/vacancies/{vacancy_id}/pact/clarifications", response_model=r.Envelope[list[r.ClarificationOut]]
)
def list_clarifications(vacancy_id: UUID, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    require_vacancy(db, actor, str(vacancy_id))
    return {
        "data": [
            pact.clarification_out(row)
            for row in db.scalars(
                select(Clarification)
                .where(Clarification.vacancy_id == str(vacancy_id))
                .order_by(Clarification.created_at.desc())
                .limit(200)
            )
        ]
    }


@router.post("/pact/policies", status_code=201, response_model=r.RESPONSE_MODELS["create_policy"])
def create_policy(
    request: schema.CreatePolicy, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.create_policy(db, actor, request)}


@router.get("/pact/policies/{policy_id}", response_model=r.RESPONSE_MODELS["read_policy"])
def read_policy(policy_id: UUID, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    return {"data": pact.read_policy(db, actor, str(policy_id))}


@router.post("/pact/policies/{policy_id}/authorize", response_model=r.RESPONSE_MODELS["authorize_policy"])
def authorize_policy(
    policy_id: UUID,
    request: schema.AuthorizePolicy,
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    return {"data": pact.authorize_policy(db, actor, str(policy_id), request)}


@router.post("/pact/policies/{policy_id}/revoke", response_model=r.RESPONSE_MODELS["revoke_policy"])
def revoke_policy(
    policy_id: UUID, request: schema.Revoke, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.revoke_policy(db, actor, str(policy_id), request)}


@router.post(
    "/pact/clarifications", status_code=201, response_model=r.RESPONSE_MODELS["create_clarification"]
)
def create_clarification(
    request: schema.CreateClarification, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.create_clarification(db, actor, request)}


@router.post(
    "/pact/clarifications/{clarification_id}/respond",
    response_model=r.RESPONSE_MODELS["respond_clarification"],
)
def respond_clarification(
    clarification_id: UUID,
    request: schema.RespondClarification,
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    return {"data": pact.respond_clarification(db, actor, str(clarification_id), request)}


@router.post("/evidence/claims", status_code=201, response_model=r.RESPONSE_MODELS["create_claim"])
def create_claim(
    request: schema.CreateClaim, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.create_claim(db, actor, request)}


@router.get("/evidence/claims/me", response_model=r.RESPONSE_MODELS["list_claims"])
def list_claims(db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    return {"data": pact.list_claims(db, actor)}


@router.get("/evidence/claims/{claim_id}", response_model=r.RESPONSE_MODELS["disclosed_claim"])
def disclosed_claim(
    claim_id: UUID,
    vacancy_id: UUID = Query(),
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    return {"data": pact.disclosed_claim(db, actor, str(claim_id), str(vacancy_id))}


@router.post(
    "/evidence/claims/{claim_id}/document",
    status_code=201,
    response_model=r.RESPONSE_MODELS["attach_document"],
)
def attach_document(
    claim_id: UUID,
    expected_version: int = Form(ge=1),
    file: UploadFile = File(),
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    content = file.file.read(get_settings().max_resume_bytes + 1)
    return {
        "data": pact.attach_document(
            db,
            actor,
            str(claim_id),
            expected_version,
            content,
            file.content_type or "application/octet-stream",
        )
    }


@router.get(
    "/evidence/claims/{claim_id}/document",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def evidence_document(
    claim_id: UUID,
    vacancy_id: UUID | None = Query(default=None),
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    content = pact.document_content(db, actor, str(claim_id), str(vacancy_id) if vacancy_id else None)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="evidence-document"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/evidence/claims/{claim_id}/verify", response_model=r.RESPONSE_MODELS["verify_claim"])
def verify_claim(
    claim_id: UUID,
    request: schema.VerifyClaim,
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    return {"data": pact.verify_claim(db, actor, str(claim_id), request)}


@router.post("/evidence/claims/{claim_id}/revoke", response_model=r.RESPONSE_MODELS["revoke_claim"])
def revoke_claim(
    claim_id: UUID, request: schema.Revoke, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.revoke_claim(db, actor, str(claim_id), request)}


@router.post("/consents/terms", status_code=201, response_model=r.RESPONSE_MODELS["consent_terms"])
def consent_terms(
    request: schema.ConsentTerms, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.consent_terms(db, actor, request)}


@router.post("/consents/evidence", status_code=201, response_model=r.RESPONSE_MODELS["consent_evidence"])
def consent_evidence(
    request: schema.ConsentEvidence, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.consent_evidence(db, actor, request)}


@router.get("/consents/me", response_model=r.RESPONSE_MODELS["consent_ledger"])
def consent_ledger(db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    return {"data": pact.consent_ledger(db, actor)}


@router.post("/consents/{consent_id}/revoke", response_model=r.RESPONSE_MODELS["revoke_consent"])
def revoke_consent(
    consent_id: UUID, request: schema.Revoke, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.revoke_consent(db, actor, str(consent_id), request)}


@router.post("/pact/readiness/check", response_model=r.RESPONSE_MODELS["check_readiness"])
def check_readiness(
    request: schema.CheckReadiness, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)
):
    return {"data": pact.check_readiness(db, actor, request)}


@router.get("/pact/readiness/{proof_id}", response_model=r.RESPONSE_MODELS["live_readiness"])
def live_readiness(proof_id: UUID, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    return {"data": pact.require_live_readiness(db, actor, str(proof_id))}


@router.post("/pact/reservations", status_code=201, response_model=r.RESPONSE_MODELS["reserve"])
def reserve(request: schema.Reserve, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    return {"data": pact.reserve(db, actor, request)}


@router.post(
    "/pact/reservations/{reservation_id}/release", response_model=r.RESPONSE_MODELS["release_reservation"]
)
def release_reservation(
    reservation_id: UUID,
    request: schema.Revoke,
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    return {"data": pact.release_reservation(db, actor, str(reservation_id), request)}
