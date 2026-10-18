"""Idempotency preserves outcomes, never an authorization capability."""

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import (
    Candidate,
    DecisionCard,
    Invitation,
    Message,
    Notification,
    Offer,
    Requirement,
)
from app.db.pact_models import Clarification, EvidenceClaim, EvidenceGrant, PactPolicy, TermConsent
from app.services import clearing, pact, workflow
from app.services.common import (
    Actor,
    digest,
    load,
    require_candidate,
    require_org_role,
    require_platform,
    require_vacancy,
)


def authorize_replay(db, actor: Actor, path: str, body, *, request=None) -> None:
    parts = path.removeprefix("/v1/").split("/")
    data = body if isinstance(body, dict) else {}
    root = parts[0]
    if root == "demo":
        from app.api.demo import authorize_demo_actor, require_sample_demo

        if request is None:
            raise AppError(403, "DEMO_DISABLED", "Demo authorization must be checked for this request")
        require_sample_demo(request, db)
        authorize_demo_actor(db, actor)
    elif root == "internal":
        roles = (
            {"RESEARCH_ADMIN"}
            if parts[1] == "shadow"
            else {"RESEARCH_ADMIN", "SYSTEM_WORKER"}
            if parts[1] == "matching"
            else {"OPERATIONS", "SYSTEM_WORKER"}
        )
        require_platform(actor, *roles)
    elif root == "admin":
        require_platform(actor, "OPERATIONS" if parts[1] == "users" else "SUPPORT")
    elif root == "organizations":
        if len(parts) == 1:
            return
        if parts[1] == "invitations":
            invitation = db.scalar(
                select(Invitation).where(Invitation.token_hash == digest(data.get("token", "")))
            )
            from app.db.models import User

            if not invitation or load(db, User, actor.user_id).verified_email.casefold() != invitation.email:
                raise AppError(403, "INVALID_INVITATION", "Invitation is unavailable for this identity")
        elif parts[-1] in {"verify", "approve"}:
            require_platform(actor, "VERIFIER")
        else:
            require_org_role(db, actor, parts[1], {"ORG_ADMIN"})
    elif root == "vacancies":
        if len(parts) == 1:
            require_org_role(db, actor, str(data["org_id"]), {"ORG_ADMIN", "RECRUITER"})
        else:
            require_vacancy(db, actor, parts[1], "approve_policy" if parts[-1] == "approve" else "edit")
    elif root == "requirements":
        require_vacancy(db, actor, load(db, Requirement, parts[1]).vacancy_id, "edit")
    elif root == "decisions":
        clearing.authorize_card(db, actor, load(db, DecisionCard, parts[1]))
    elif root == "matches":
        if parts[-1] == "verify":
            pact.require_verifier(db, actor)
        else:
            _, _, _, vacancy, _ = workflow.participant(db, actor, parts[1], active=False)
            if parts[-1] == "offers":
                pact.signatory(db, actor, vacancy.id)
    elif root == "offers":
        offer = load(db, Offer, parts[1])
        from app.db.models import PairCycle

        cycle = load(db, PairCycle, offer.pair_cycle_id)
        if load(db, Candidate, cycle.candidate_id).user_id != actor.user_id:
            raise AppError(403, "FORBIDDEN", "Offer belongs to another candidate")
    elif root == "pact":
        if parts[1] == "policies":
            ids = (
                [str(item["vacancy_id"]) for item in data.get("roles", [])]
                if len(parts) == 2
                else list(load(db, PactPolicy, parts[2]).scope)
            )
            for vacancy_id in ids:
                pact.signatory(db, actor, vacancy_id, recent=parts[-1] != "revoke")
        elif parts[1] == "clarifications":
            vacancy_id = (
                str(data["vacancy_id"]) if len(parts) == 2 else load(db, Clarification, parts[2]).vacancy_id
            )
            pact.signatory(db, actor, vacancy_id)
        elif parts[1] == "readiness":
            pact.evaluator(db, actor, str(data["candidate_id"]), str(data["vacancy_id"]))
        else:
            require_candidate(db, actor)
    elif root == "evidence":
        if parts[-1] == "verify":
            pact.require_verifier(db, actor)
        elif len(parts) >= 3:
            claim = load(db, EvidenceClaim, parts[2])
            candidate = db.scalar(select(Candidate).where(Candidate.user_id == actor.user_id))
            if not candidate or candidate.id != claim.candidate_id:
                pact.require_verifier(db, actor)
        else:
            require_candidate(db, actor)
    elif root == "consents":
        candidate = require_candidate(db, actor)
        if len(parts) > 2 and parts[-1] == "revoke":
            row = db.get(EvidenceGrant, parts[1]) or db.get(TermConsent, parts[1])
            if not row or row.candidate_id != candidate.id:
                raise AppError(403, "FORBIDDEN", "Consent belongs to another candidate")
    elif root == "notifications" and len(parts) > 2:
        if load(db, Notification, parts[1]).user_id != actor.user_id:
            raise AppError(403, "FORBIDDEN", "Notification belongs to another user")
    elif root == "reports":
        kind, entity_id = data["entity_type"], str(data["entity_id"])
        if kind == "MATCH":
            workflow.participant(db, actor, entity_id, active=False)
        elif kind == "MESSAGE":
            workflow.participant(db, actor, load(db, Message, entity_id).match_id, active=False)
    # Candidate, session, privacy and preference routes are strictly actor-owned.
