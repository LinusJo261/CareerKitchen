from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.core.settings import get_settings
from app.db.models import (
    AbuseReport,
    Candidate,
    CandidateBlock,
    DecisionCard,
    EmploymentStart,
    Exposure,
    Message,
    MutualMatch,
    Notification,
    NotificationPreference,
    Offer,
    Organization,
    OrgMember,
    PairCycle,
    PrivacyRequest,
    Requirement,
    RevokedSession,
    ShadowRun,
    User,
    Vacancy,
    VacancyACL,
)
from app.schemas import core as s
from app.schemas import responses as r
from app.services import clearing, matching_learning, profiles, workflow
from app.services.common import (
    Actor,
    digest,
    emit,
    invalidate,
    load,
    lock_scopes,
    require_candidate,
    require_org_role,
    require_platform,
    require_vacancy,
    require_version,
    utcnow,
)

router = APIRouter(
    route_class=TransactionalRoute,
    responses={
        401: {"model": s.ErrorEnvelope},
        403: {"model": s.ErrorEnvelope},
        404: {"model": s.ErrorEnvelope},
        409: {"model": s.ErrorEnvelope},
        412: {"model": s.ErrorEnvelope},
        422: {"model": s.ErrorEnvelope},
        429: {"model": s.ErrorEnvelope},
    },
)
DB = Depends(db_dep)
AUTH = Depends(actor_dep)


def _page(rows, actor: Actor, scope: str, cursor: str | None, limit: int):
    """Actor/scoped opaque cursor, signed to prevent cross-tenant reuse/tampering."""
    offset = 0
    if cursor:
        try:
            payload, signature = cursor.split(".")
            expected = hmac.new(
                get_settings().audit_hmac_key.get_secret_value().encode(), payload.encode(), hashlib.sha256
            ).hexdigest()
            decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if (
                not hmac.compare_digest(signature, expected)
                or decoded[:2] != [actor.user_id, scope]
                or decoded[3] < utcnow().timestamp()
            ):
                raise ValueError()
            offset = decoded[2]
            if not isinstance(offset, int) or not 0 <= offset <= 100000:
                raise ValueError()
        except (ValueError, TypeError, KeyError, IndexError):
            raise AppError(422, "INVALID_CURSOR", "Pagination cursor is invalid or expired") from None
    more = len(rows) > offset + limit
    next_cursor = None
    if more:
        payload = (
            base64.urlsafe_b64encode(
                json.dumps(
                    [actor.user_id, scope, offset + limit, (utcnow() + timedelta(hours=1)).timestamp()],
                    separators=(",", ":"),
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        next_cursor = (
            payload
            + "."
            + hmac.new(
                get_settings().audit_hmac_key.get_secret_value().encode(), payload.encode(), hashlib.sha256
            ).hexdigest()
        )
    return {"data": rows[offset : offset + limit], "page": {"has_more": more, "next_cursor": next_cursor}}


@router.get("/sessions/me", tags=["sessions"], response_model=r.RESPONSE_MODELS["me"])
def me(db: Session = DB, actor: Actor = AUTH):
    user = load(db, User, actor.user_id)
    return {
        "data": {
            "id": actor.user_id,
            "email": user.verified_email,
            "platform_roles": list(actor.platform_roles),
            "memberships": [
                {"id": m.id, "org_id": m.org_id, "role": m.role, "status": m.status, "version": m.version}
                for m in db.scalars(select(OrgMember).where(OrgMember.user_id == actor.user_id))
            ],
        }
    }


@router.post("/sessions/logout", tags=["sessions"], response_model=r.RESPONSE_MODELS["logout"])
def logout(db: Session = DB, actor: Actor = AUTH):
    db.add(
        RevokedSession(id=actor.session_id, user_id=actor.user_id, expires_at=utcnow() + timedelta(days=1))
    )
    emit(db, actor, "auth.session_revoked", load(db, User, actor.user_id))
    return {
        "data": {
            "status": "REVOKED",
            "notice": "Also sign out through Supabase to revoke refresh credentials",
        }
    }


@router.get("/candidates/me", tags=["candidates"], response_model=r.RESPONSE_MODELS["get_candidate"])
def get_candidate(db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.candidate_out(require_candidate(db, actor))}


@router.put("/candidates/me", tags=["candidates"], response_model=r.RESPONSE_MODELS["put_candidate"])
def put_candidate(data: s.CandidateInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.candidate_out(profiles.save_candidate(db, actor, data))}


@router.put(
    "/candidates/me/preferences", tags=["candidates"], response_model=r.RESPONSE_MODELS["put_preferences"]
)
def put_preferences(data: s.PreferencesInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.candidate_out(profiles.save_preferences(db, actor, data))}


@router.post(
    "/candidates/me/activate", tags=["candidates"], response_model=r.RESPONSE_MODELS["activate_candidate"]
)
def activate_candidate(data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    return {
        "data": profiles.candidate_out(profiles.candidate_state(db, actor, data.expected_version, "ACTIVE"))
    }


@router.post("/candidates/me/pause", tags=["candidates"], response_model=r.RESPONSE_MODELS["pause_candidate"])
def pause_candidate(data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    return {
        "data": profiles.candidate_out(profiles.candidate_state(db, actor, data.expected_version, "PAUSED"))
    }


@router.post("/candidates/me/skills", tags=["candidates"], response_model=r.RESPONSE_MODELS["add_skill"])
def add_skill(data: s.SkillInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.add_skill(db, actor, data)}


@router.get("/candidates/me/skills", tags=["candidates"], response_model=r.RESPONSE_MODELS["list_skills"])
def list_skills(db: Session = DB, actor: Actor = AUTH):
    from app.db.models import CandidateSkill, Skill

    candidate = require_candidate(db, actor)
    return {
        "data": [
            {
                "id": row.id,
                "version": row.version,
                "name": skill.name,
                "level": row.level,
                "verification_status": "SELF_REPORTED",
            }
            for row, skill in db.execute(
                select(CandidateSkill, Skill)
                .join(Skill, Skill.id == CandidateSkill.skill_id)
                .where(CandidateSkill.candidate_id == candidate.id)
            )
        ]
    }


@router.patch("/candidates/me/skills/{skill_id}", tags=["candidates"], response_model=r.Envelope[r.SkillOut])
def edit_skill(skill_id: UUID, data: s.SkillEditInput, db: Session = DB, actor: Actor = AUTH):
    from app.db.models import CandidateSkill, Skill

    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    row = load(db, CandidateSkill, str(skill_id))
    if row.candidate_id != candidate.id:
        raise AppError(403, "FORBIDDEN", "Skill belongs to another candidate")
    require_version(row, data.expected_version)
    row.level, row.version = data.level, row.version + 1
    emit(db, actor, "candidate.skill_added", row)
    return {
        "data": {
            "id": row.id,
            "skill_id": row.skill_id,
            "name": load(db, Skill, row.skill_id).name,
            "level": row.level,
            "verification_status": "SELF_REPORTED",
            "version": row.version,
        }
    }


@router.delete(
    "/candidates/me/skills/{skill_id}", tags=["candidates"], response_model=r.Envelope[r.StatusOut]
)
def delete_skill(skill_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    from app.db.models import CandidateSkill

    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    candidate = load(db, Candidate, candidate.id)
    row = load(db, CandidateSkill, str(skill_id))
    if row.candidate_id != candidate.id:
        raise AppError(403, "FORBIDDEN", "Skill belongs to another candidate")
    require_version(row, data.expected_version)
    if row.confirmed:
        candidate.version += 1
    emit(
        db,
        actor,
        "candidate.skill_removed",
        row,
        payload={"candidate_id": candidate.id, "candidate_version": candidate.version},
    )
    db.delete(row)
    return {"data": {"status": "REMOVED"}}


@router.put("/candidates/me/availability", tags=["candidates"], response_model=r.Envelope[s.CandidateOut])
def availability(data: s.AvailabilityInput, db: Session = DB, actor: Actor = AUTH):
    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    candidate = load(db, Candidate, candidate.id)
    require_version(candidate, data.expected_version)
    candidate.available_from, candidate.available_until = data.available_from, data.available_until
    candidate.version += 1
    clearing.cancel_candidate_pending(db, actor, candidate.id, "AVAILABILITY_CHANGED")
    invalidate(db, actor=actor, candidate_id=candidate.id, reason="AVAILABILITY_CHANGED")
    emit(db, actor, "candidate.profile_updated", candidate)
    return {"data": profiles.candidate_out(candidate)}


@router.post("/candidates/me/resume", tags=["candidates"], response_model=r.RESPONSE_MODELS["upload_resume"])
async def upload_resume(file: UploadFile = File(), db: Session = DB, actor: Actor = AUTH):
    from app.integrations.storage import store_resume

    candidate = require_candidate(db, actor)
    content = await file.read(get_settings().max_resume_bytes + 1)
    result = store_resume(content, file.content_type or "application/octet-stream", UUID(actor.user_id))
    candidate.resume_object_ref = result.object_key
    candidate.version += 1
    emit(db, actor, "candidate.resume_uploaded", candidate)
    # Parsing is a proposed draft. Nothing here changes authoritative skills.
    return {
        "data": {
            "object_id": candidate.id,
            "size": result.size,
            "sha256": result.sha256,
            "parse_status": "DRAFT_REQUIRES_CONFIRMATION" if result.text else "MANUAL_ENTRY_REQUIRED",
            "suggested_summary": (result.text or "")[:3000],
            "candidate_version": candidate.version,
        }
    }


@router.get(
    "/candidates/me/resume",
    tags=["candidates"],
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def get_resume(db: Session = DB, actor: Actor = AUTH):
    from app.integrations.storage import read_private

    candidate = require_candidate(db, actor)
    if not candidate.resume_object_ref:
        raise AppError(404, "NO_RESUME", "No resume was uploaded")
    emit(db, actor, "candidate.resume_accessed", candidate)
    return Response(
        read_private(candidate.resume_object_ref),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="resume"', "Cache-Control": "no-store"},
    )


@router.post("/candidates/me/blocks", tags=["privacy"], response_model=r.RESPONSE_MODELS["block"])
def block(data: s.BlockInput, db: Session = DB, actor: Actor = AUTH):
    profiles.block_org(db, actor, str(data.org_id))
    return {"data": {"status": "BLOCKED"}}


@router.delete(
    "/candidates/me/blocks/{org_id}", tags=["privacy"], response_model=r.RESPONSE_MODELS["unblock"]
)
def unblock(org_id: UUID, db: Session = DB, actor: Actor = AUTH):
    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    row = db.scalar(
        select(CandidateBlock).where(
            CandidateBlock.candidate_id == candidate.id, CandidateBlock.org_id == str(org_id)
        )
    )
    if row:
        emit(db, actor, "candidate.org_unblocked", row)
        db.delete(row)
    return {"data": {"status": "UNBLOCKED"}}


@router.get(
    "/candidates/me/decisions", tags=["decisions"], response_model=r.RESPONSE_MODELS["candidate_decisions"]
)
def candidate_decisions(db: Session = DB, actor: Actor = AUTH):
    candidate = require_candidate(db, actor)
    cards = list(
        db.scalars(
            select(DecisionCard)
            .where(
                DecisionCard.candidate_id == candidate.id,
                DecisionCard.side == "CANDIDATE",
                DecisionCard.status == "ACTIVE",
            )
            .order_by(DecisionCard.created_at, DecisionCard.id)
        )
    )
    return {
        "data": [clearing.card_out(db, actor, card) for card in cards],
        "capacity": {"used": len(cards), "maximum": candidate.cap},
    }


@router.get(
    "/candidates/me/waiting", tags=["decisions"], response_model=r.RESPONSE_MODELS["candidate_waiting"]
)
def candidate_waiting(db: Session = DB, actor: Actor = AUTH):
    candidate = require_candidate(db, actor)
    rows = db.scalars(
        select(PairCycle).where(
            PairCycle.candidate_id == candidate.id,
            PairCycle.closed_at.is_(None),
            PairCycle.candidate_interested_at.is_not(None),
            PairCycle.employer_interested_at.is_(None),
        )
    )
    return {
        "data": [
            {
                "pair_cycle_id": row.id,
                "state": row.state,
                "vacancy_id": row.vacancy_id,
                "version": row.version,
            }
            for row in rows
        ]
    }


@router.get("/candidates/me/matches", tags=["matches"], response_model=r.RESPONSE_MODELS["candidate_matches"])
def candidate_matches(db: Session = DB, actor: Actor = AUTH):
    candidate = require_candidate(db, actor)
    return {
        "data": [
            workflow.match_out(db, actor, match.id)
            for match in db.scalars(
                select(MutualMatch)
                .join(PairCycle, PairCycle.id == MutualMatch.pair_cycle_id)
                .where(PairCycle.candidate_id == candidate.id)
            )
        ]
    }


@router.get(
    "/candidates/me/history", tags=["candidates"], response_model=r.RESPONSE_MODELS["candidate_history"]
)
def candidate_history(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = DB,
    actor: Actor = AUTH,
):
    candidate = require_candidate(db, actor)
    rows = [
        {
            "id": row.id,
            "state": row.state,
            "vacancy_id": row.vacancy_id,
            "version": row.version,
            "closed_at": row.closed_at,
        }
        for row in db.scalars(
            select(PairCycle)
            .where(PairCycle.candidate_id == candidate.id)
            .order_by(PairCycle.created_at.desc(), PairCycle.id)
        )
    ]
    return _page(rows, actor, "candidate-history", cursor, limit)


@router.post("/organizations", tags=["organizations"], response_model=r.RESPONSE_MODELS["create_org"])
def create_org(data: s.OrganizationInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.organization_out(profiles.create_org(db, actor, data))}


@router.get("/organizations", tags=["organizations"], response_model=r.RESPONSE_MODELS["list_orgs"])
def list_orgs(db: Session = DB, actor: Actor = AUTH):
    return {
        "data": [
            profiles.organization_out(org)
            for org in db.scalars(
                select(Organization)
                .join(OrgMember, OrgMember.org_id == Organization.id)
                .where(
                    OrgMember.user_id == actor.user_id,
                    (OrgMember.expires_at.is_(None) | (OrgMember.expires_at > utcnow())),
                    (
                        (OrgMember.status == "ACTIVE")
                        | ((OrgMember.status == "PENDING") & (Organization.created_by == actor.user_id))
                    ),
                )
                .distinct()
            )
        ]
    }


@router.get("/organizations/{org_id}", tags=["organizations"], response_model=r.RESPONSE_MODELS["get_org"])
def get_org(org_id: UUID, db: Session = DB, actor: Actor = AUTH):
    org = load(db, Organization, str(org_id))
    if org.created_by != actor.user_id:
        require_org_role(
            db, actor, org.id, {"ORG_ADMIN", "RECRUITER", "HIRING_MANAGER", "AUTHORIZED_SIGNATORY"}
        )
    return {"data": profiles.organization_out(org)}


@router.post(
    "/organizations/{org_id}/verify", tags=["verification"], response_model=r.RESPONSE_MODELS["verify_org"]
)
def verify_org(org_id: UUID, data: s.VerificationInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.organization_out(profiles.verify_org(db, actor, str(org_id), data))}


@router.patch("/organizations/{org_id}", tags=["organizations"], response_model=r.Envelope[r.OrganizationOut])
def edit_organization(org_id: UUID, data: s.OrganizationEditInput, db: Session = DB, actor: Actor = AUTH):
    lock_scopes(db, f"organization:{org_id}")
    require_org_role(db, actor, str(org_id), {"ORG_ADMIN"})
    org = load(db, Organization, str(org_id))
    require_version(org, data.expected_version)
    org.display_name, org.version = data.display_name, org.version + 1
    emit(db, actor, "organization.profile_updated", org, org_id=org.id)
    return {"data": profiles.organization_out(org)}


@router.post(
    "/organizations/{org_id}/members/approve",
    tags=["verification"],
    response_model=r.RESPONSE_MODELS["approve_member"],
)
def approve_member(org_id: UUID, data: s.MemberGrantInput, db: Session = DB, actor: Actor = AUTH):
    row = profiles.grant_member(db, actor, str(org_id), data)
    return {"data": {"id": row.id, "version": row.version, "role": row.role, "status": row.status}}


@router.get(
    "/organizations/{org_id}/members",
    tags=["organizations"],
    response_model=r.RESPONSE_MODELS["list_members"],
)
def list_members(org_id: UUID, db: Session = DB, actor: Actor = AUTH):
    require_org_role(db, actor, str(org_id), {"ORG_ADMIN"})
    return {
        "data": [
            {
                "id": m.id,
                "version": m.version,
                "org_id": m.org_id,
                "user_id": m.user_id,
                "role": m.role,
                "status": m.status,
            }
            for m in db.scalars(select(OrgMember).where(OrgMember.org_id == str(org_id)))
        ]
    }


@router.post(
    "/organizations/{org_id}/members/invite",
    tags=["organizations"],
    response_model=r.RESPONSE_MODELS["invite"],
)
def invite(org_id: UUID, data: s.InviteInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.invite(db, actor, str(org_id), data)}


@router.post(
    "/organizations/invitations/accept",
    tags=["organizations"],
    response_model=r.RESPONSE_MODELS["accept_invitation"],
)
def accept_invitation(data: s.InviteAcceptInput, db: Session = DB, actor: Actor = AUTH):
    row = profiles.accept_invite(db, actor, data.token)
    return {"data": {"id": row.id, "role": row.role, "org_id": row.org_id}}


@router.delete(
    "/organizations/{org_id}/members/{member_id}",
    tags=["organizations"],
    response_model=r.RESPONSE_MODELS["revoke_member"],
)
def revoke_member(org_id: UUID, member_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    require_org_role(db, actor, str(org_id), {"ORG_ADMIN"})
    row = load(db, OrgMember, str(member_id))
    if row.org_id != str(org_id) or row.user_id == actor.user_id:
        raise AppError(403, "FORBIDDEN", "Cannot remove this member")
    vacancies = list(db.scalars(select(Vacancy).where(Vacancy.org_id == str(org_id))))
    lock_scopes(db, f"membership:{org_id}:{row.user_id}", *(f"vacancy:{vacancy.id}" for vacancy in vacancies))
    row = load(db, OrgMember, row.id)
    require_version(row, data.expected_version)
    row.status, row.version = "REVOKED", row.version + 1
    for vacancy in db.scalars(select(Vacancy).where(Vacancy.org_id == str(org_id))):
        invalidate(db, actor=actor, vacancy_id=vacancy.id, reason="AUTHORITY_REVOKED")
    emit(db, actor, "organization.member_revoked", row, org_id=str(org_id))
    return {"data": {"status": "REVOKED", "version": row.version}}


@router.patch(
    "/organizations/{org_id}/members/{member_id}",
    tags=["organizations"],
    response_model=r.Envelope[r.MemberOut],
)
def update_member(
    org_id: UUID, member_id: UUID, data: s.MemberUpdateInput, db: Session = DB, actor: Actor = AUTH
):
    require_org_role(db, actor, str(org_id), {"ORG_ADMIN"})
    row = load(db, OrgMember, str(member_id))
    if (
        row.org_id != str(org_id)
        or row.user_id == actor.user_id
        or row.role in {"ORG_ADMIN", "AUTHORIZED_SIGNATORY"}
    ):
        raise AppError(
            403,
            "INDEPENDENT_APPROVAL_REQUIRED",
            "Privileged memberships require independent authority review",
        )
    lock_scopes(db, f"membership:{org_id}:{row.user_id}")
    row = load(db, OrgMember, row.id)
    require_version(row, data.expected_version)
    row.role, row.version = data.role, row.version + 1
    emit(db, actor, "organization.member_updated", row, org_id=str(org_id))
    return {
        "data": {
            "id": row.id,
            "version": row.version,
            "role": row.role,
            "status": row.status,
            "org_id": row.org_id,
            "user_id": row.user_id,
        }
    }


@router.post("/vacancies", tags=["vacancies"], response_model=r.RESPONSE_MODELS["create_vacancy"])
def create_vacancy(data: s.VacancyInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.vacancy_out(db, profiles.create_vacancy(db, actor, data))}


@router.get(
    "/organizations/{org_id}/vacancies",
    tags=["vacancies"],
    response_model=r.RESPONSE_MODELS["list_vacancies"],
)
def list_vacancies(org_id: UUID, db: Session = DB, actor: Actor = AUTH):
    require_org_role(
        db, actor, str(org_id), {"ORG_ADMIN", "RECRUITER", "HIRING_MANAGER", "AUTHORIZED_SIGNATORY"}
    )
    assigned = select(VacancyACL.vacancy_id).where(VacancyACL.user_id == actor.user_id)
    return {
        "data": [
            profiles.vacancy_out(db, row)
            for row in db.scalars(
                select(Vacancy).where(Vacancy.org_id == str(org_id), Vacancy.id.in_(assigned))
            )
        ]
    }


@router.get("/vacancies/{vacancy_id}", tags=["vacancies"], response_model=r.RESPONSE_MODELS["get_vacancy"])
def get_vacancy(vacancy_id: UUID, db: Session = DB, actor: Actor = AUTH):
    vacancy = load(db, Vacancy, str(vacancy_id))
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == actor.user_id))
    if not candidate or vacancy.state != "ACTIVE":
        require_vacancy(db, actor, vacancy.id)
    return {"data": profiles.vacancy_out(db, vacancy)}


@router.patch("/vacancies/{vacancy_id}", tags=["vacancies"], response_model=r.RESPONSE_MODELS["edit_vacancy"])
def edit_vacancy(vacancy_id: UUID, data: s.VacancyEditInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": profiles.vacancy_out(db, profiles.edit_vacancy(db, actor, str(vacancy_id), data))}


@router.post(
    "/vacancies/{vacancy_id}/activate",
    tags=["vacancies"],
    response_model=r.RESPONSE_MODELS["activate_vacancy"],
)
def activate_vacancy(vacancy_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    return {
        "data": profiles.vacancy_out(
            db, profiles.set_vacancy_state(db, actor, str(vacancy_id), data.expected_version, "ACTIVE")
        )
    }


@router.post(
    "/vacancies/{vacancy_id}/pause", tags=["vacancies"], response_model=r.RESPONSE_MODELS["pause_vacancy"]
)
def pause_vacancy(vacancy_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    return {
        "data": profiles.vacancy_out(
            db, profiles.set_vacancy_state(db, actor, str(vacancy_id), data.expected_version, "PAUSED")
        )
    }


@router.post(
    "/vacancies/{vacancy_id}/close", tags=["vacancies"], response_model=r.RESPONSE_MODELS["close_vacancy"]
)
def close_vacancy(vacancy_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    return {
        "data": profiles.vacancy_out(
            db, profiles.set_vacancy_state(db, actor, str(vacancy_id), data.expected_version, "CLOSED")
        )
    }


@router.put(
    "/vacancies/{vacancy_id}/acl", tags=["organizations"], response_model=r.RESPONSE_MODELS["set_acl"]
)
def set_acl(vacancy_id: UUID, data: s.ACLInput, db: Session = DB, actor: Actor = AUTH):
    vacancy = require_vacancy(db, actor, str(vacancy_id), "edit")
    require_org_role(db, actor, vacancy.org_id, {"ORG_ADMIN"})
    lock_scopes(db, f"vacancy:{vacancy.id}")
    require_version(load(db, Vacancy, vacancy.id), data.expected_version)
    require_org_role(
        db,
        Actor(str(data.user_id), utcnow()),
        vacancy.org_id,
        {"RECRUITER", "HIRING_MANAGER", "ORG_ADMIN", "AUTHORIZED_SIGNATORY"},
    )
    if data.can_approve_policy:
        require_org_role(db, Actor(str(data.user_id), utcnow()), vacancy.org_id, {"AUTHORIZED_SIGNATORY"})
    acl = db.scalar(
        select(VacancyACL).where(VacancyACL.vacancy_id == vacancy.id, VacancyACL.user_id == str(data.user_id))
    )
    if not acl:
        acl = VacancyACL(vacancy_id=vacancy.id, user_id=str(data.user_id))
        db.add(acl)
    acl.can_review, acl.can_edit, acl.can_approve_policy = (
        data.can_review,
        data.can_edit,
        data.can_approve_policy,
    )
    acl.version = (acl.version or 0) + 1
    vacancy.version += 1
    clearing.cancel_vacancy_pending(db, actor, vacancy.id, "ACCESS_SCOPE_CHANGED")
    profiles.refresh_terms(db, vacancy)
    invalidate(db, actor=actor, vacancy_id=vacancy.id, reason="ACCESS_SCOPE_CHANGED")
    emit(db, actor, "vacancy.acl_updated", acl, org_id=vacancy.org_id)
    return {"data": {"id": acl.id, "vacancy_version": vacancy.version}}


@router.post(
    "/vacancies/{vacancy_id}/requirements",
    tags=["requirements"],
    response_model=r.RESPONSE_MODELS["add_requirement"],
)
def add_requirement(vacancy_id: UUID, data: s.RequirementInput, db: Session = DB, actor: Actor = AUTH):
    row = profiles.set_requirement(db, actor, str(vacancy_id), data)
    return {
        "data": {
            "id": row.id,
            "version": row.version,
            "vacancy_version": load(db, Vacancy, row.vacancy_id).version,
        }
    }


@router.patch(
    "/requirements/{requirement_id}",
    tags=["requirements"],
    response_model=r.RESPONSE_MODELS["edit_requirement"],
)
def edit_requirement(requirement_id: UUID, data: s.RequirementInput, db: Session = DB, actor: Actor = AUTH):
    row = load(db, Requirement, str(requirement_id))
    row = profiles.set_requirement(db, actor, row.vacancy_id, data, row.id)
    return {
        "data": {
            "id": row.id,
            "version": row.version,
            "vacancy_version": load(db, Vacancy, row.vacancy_id).version,
        }
    }


@router.get(
    "/vacancies/{vacancy_id}/decisions",
    tags=["decisions"],
    response_model=r.RESPONSE_MODELS["vacancy_decisions"],
)
def vacancy_decisions(vacancy_id: UUID, db: Session = DB, actor: Actor = AUTH):
    vacancy = require_vacancy(db, actor, str(vacancy_id))
    rows = list(
        db.scalars(
            select(DecisionCard)
            .where(
                DecisionCard.vacancy_id == vacancy.id,
                DecisionCard.side == "EMPLOYER",
                DecisionCard.status == "ACTIVE",
            )
            .order_by(DecisionCard.created_at, DecisionCard.id)
        )
    )
    return {
        "data": [clearing.card_out(db, actor, row) for row in rows],
        "capacity": {"used": len(rows), "maximum": vacancy.cap},
    }


@router.get(
    "/vacancies/{vacancy_id}/waiting", tags=["decisions"], response_model=r.RESPONSE_MODELS["vacancy_waiting"]
)
def vacancy_waiting(vacancy_id: UUID, db: Session = DB, actor: Actor = AUTH):
    vacancy = require_vacancy(db, actor, str(vacancy_id))
    # No candidate details are revealed while waiting for a first employer exposure.
    rows = db.scalars(
        select(PairCycle).where(
            PairCycle.vacancy_id == vacancy.id,
            PairCycle.closed_at.is_(None),
            PairCycle.employer_interested_at.is_not(None),
            PairCycle.candidate_interested_at.is_(None),
        )
    )
    return {"data": [{"pair_cycle_id": row.id, "state": row.state, "version": row.version} for row in rows]}


@router.get(
    "/vacancies/{vacancy_id}/pipeline", tags=["matches"], response_model=r.RESPONSE_MODELS["pipeline"]
)
def pipeline(vacancy_id: UUID, db: Session = DB, actor: Actor = AUTH):
    vacancy = require_vacancy(db, actor, str(vacancy_id))
    return {
        "data": [
            workflow.match_out(db, actor, row.id)
            for row in db.scalars(
                select(MutualMatch)
                .join(PairCycle, PairCycle.id == MutualMatch.pair_cycle_id)
                .where(PairCycle.vacancy_id == vacancy.id)
            )
        ]
    }


@router.get(
    "/vacancies/{vacancy_id}/metrics", tags=["analytics"], response_model=r.RESPONSE_MODELS["metrics"]
)
def metrics(vacancy_id: UUID, db: Session = DB, actor: Actor = AUTH):
    vacancy = require_vacancy(db, actor, str(vacancy_id))
    delivered = db.scalar(
        select(func.count(func.distinct(Exposure.candidate_id))).where(
            Exposure.vacancy_id == vacancy.id, Exposure.recipient_side == "EMPLOYER"
        )
    )
    states = dict(
        db.execute(
            select(PairCycle.state, func.count())
            .where(PairCycle.vacancy_id == vacancy.id)
            .group_by(PairCycle.state)
        ).all()
    )
    return {
        "data": {
            "vacancy_id": vacancy.id,
            "n_delivered": delivered,
            "candidate_attempts": db.scalar(
                select(func.count())
                .select_from(Exposure)
                .where(Exposure.vacancy_id == vacancy.id, Exposure.recipient_side == "CANDIDATE")
            ),
            "active_employer_decisions": clearing.active_count(db, vacancy_id=vacancy.id),
            "states": states,
            "filled_openings": vacancy.openings_total - vacancy.openings_remaining,
            "certification_state": "CANNOT_CERTIFY",
        }
    }


@router.post("/internal/decisions/issue", tags=["operations"], response_model=r.RESPONSE_MODELS["issue_card"])
def issue_card(data: s.IssueCardInput, db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "OPERATIONS", "SYSTEM_WORKER")
    card = clearing.issue_first(
        db,
        actor,
        str(data.candidate_id),
        str(data.vacancy_id),
        data.role_version,
        data.first_mover,
        {"model_version": "manual-reviewed-v1", "review_reason_hash": digest(data.human_review_reason)},
    )
    return {"data": {"decision_id": card.id, "pair_cycle_id": card.pair_cycle_id}}


@router.post("/internal/reconcile", tags=["operations"], response_model=r.RESPONSE_MODELS["reconcile"])
def reconcile(db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "OPERATIONS", "SYSTEM_WORKER")
    clearing.expire_due(db, actor)
    clearing.release_waiting(db, actor)
    return {"data": {"issued": clearing.reconcile(db, actor)}}


@router.get("/decisions/{decision_id}", tags=["decisions"], response_model=r.RESPONSE_MODELS["decision"])
def decision(decision_id: UUID, db: Session = DB, actor: Actor = AUTH):
    return {"data": clearing.card_out(db, actor, load(db, DecisionCard, str(decision_id)))}


@router.post(
    "/decisions/{decision_id}/interested", tags=["decisions"], response_model=r.RESPONSE_MODELS["interested"]
)
def interested(decision_id: UUID, data: s.DecisionAnswerInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": clearing.answer(db, actor, str(decision_id), True, data)}


@router.post(
    "/decisions/{decision_id}/pass", tags=["decisions"], response_model=r.RESPONSE_MODELS["pass_decision"]
)
def pass_decision(decision_id: UUID, data: s.DecisionAnswerInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": clearing.answer(db, actor, str(decision_id), False, data)}


@router.get("/matches/{match_id}", tags=["matches"], response_model=r.RESPONSE_MODELS["match"])
def match(match_id: UUID, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.match_out(db, actor, str(match_id))}


@router.get("/matches/{match_id}/messages", tags=["messages"], response_model=r.RESPONSE_MODELS["messages"])
def messages(
    match_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = DB,
    actor: Actor = AUTH,
):
    workflow.participant(db, actor, str(match_id))
    rows = [
        {
            "id": row.id,
            "sender_user_id": row.sender_user_id,
            "body": row.body,
            "created_at": row.created_at,
            "attachment_id": row.attachment_id,
        }
        for row in db.scalars(
            select(Message).where(Message.match_id == str(match_id)).order_by(Message.created_at, Message.id)
        )
    ]
    return _page(rows, actor, f"messages:{match_id}", cursor, limit)


@router.post(
    "/matches/{match_id}/messages", tags=["messages"], response_model=r.RESPONSE_MODELS["send_message"]
)
def send_message(match_id: UUID, data: s.MessageInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.send_message(db, actor, str(match_id), data)}


@router.post("/matches/{match_id}/attachments", tags=["messages"], response_model=r.Envelope[r.AttachmentOut])
async def upload_attachment(match_id: UUID, file: UploadFile = File(), db: Session = DB, actor: Actor = AUTH):
    from app.db.models import Attachment
    from app.integrations.storage import store_resume

    _, _, candidate, vacancy, _ = workflow.participant(db, actor, str(match_id))
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    workflow.participant(db, actor, str(match_id))
    content = await file.read(get_settings().max_resume_bytes + 1)
    stored = store_resume(content, file.content_type or "application/octet-stream", UUID(actor.user_id))
    row = Attachment(
        match_id=str(match_id),
        uploaded_by=actor.user_id,
        object_ref=stored.object_key,
        sha256=stored.sha256,
        size=stored.size,
    )
    db.add(row)
    emit(db, actor, "message.attachment_uploaded", row, org_id=vacancy.org_id)
    return {"data": {"id": row.id, "size": row.size, "sha256": row.sha256}}


@router.get(
    "/matches/{match_id}/attachments/{attachment_id}",
    tags=["messages"],
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def download_attachment(match_id: UUID, attachment_id: UUID, db: Session = DB, actor: Actor = AUTH):
    from app.db.models import Attachment
    from app.integrations.storage import read_private

    workflow.participant(db, actor, str(match_id))
    attachment = load(db, Attachment, str(attachment_id))
    if attachment.match_id != str(match_id):
        raise AppError(403, "FORBIDDEN", "Attachment is outside this conversation")
    emit(db, actor, "message.attachment_accessed", attachment)
    return Response(
        read_private(attachment.object_ref),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="attachment"', "Cache-Control": "no-store"},
    )


@router.post(
    "/matches/{match_id}/interviews/proposals",
    tags=["interviews"],
    response_model=r.RESPONSE_MODELS["propose_interview"],
)
def propose_interview(match_id: UUID, data: s.InterviewInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.propose_interview(db, actor, str(match_id), data)}


@router.get(
    "/matches/{match_id}/interviews/proposals",
    tags=["interviews"],
    response_model=r.RESPONSE_MODELS["interview_proposals"],
)
def interview_proposals(match_id: UUID, db: Session = DB, actor: Actor = AUTH):
    from app.db.models import InterviewProposal

    _, _, candidate, _, is_candidate = workflow.participant(db, actor, str(match_id))
    return {
        "data": [
            {
                "id": row.id,
                "version": row.version,
                "slots": row.slots,
                "timezone_label": row.timezone_label,
                "status": row.status,
                "initiator_id": row.initiator_id,
                "can_confirm": row.status == "PROPOSED"
                and (row.initiator_id == candidate.user_id) != is_candidate,
            }
            for row in db.scalars(
                select(InterviewProposal).where(InterviewProposal.match_id == str(match_id))
            )
        ]
    }


@router.post(
    "/matches/{match_id}/interviews/{proposal_id}/confirm",
    tags=["interviews"],
    response_model=r.RESPONSE_MODELS["confirm_interview"],
)
def confirm_interview(
    match_id: UUID, proposal_id: UUID, data: s.InterviewConfirmInput, db: Session = DB, actor: Actor = AUTH
):
    return {"data": workflow.confirm_interview(db, actor, str(match_id), str(proposal_id), data)}


@router.post("/matches/{match_id}/stages", tags=["matches"], response_model=r.RESPONSE_MODELS["stage"])
def stage(match_id: UUID, data: s.StageInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.stage(db, actor, str(match_id), data)}


@router.post("/matches/{match_id}/withdraw", tags=["matches"], response_model=r.RESPONSE_MODELS["withdraw"])
def withdraw(match_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    _, cycle, candidate, vacancy, _ = workflow.participant(db, actor, str(match_id))
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    cycle = load(db, PairCycle, cycle.id)
    require_version(cycle, data.expected_version)
    clearing.close_cycle(db, actor, cycle, "CLOSED_WITHDRAWN")
    return {"data": {"state": cycle.state, "cycle_version": cycle.version}}


@router.post("/matches/{match_id}/offers", tags=["offers"], response_model=r.RESPONSE_MODELS["offer"])
def offer(match_id: UUID, data: s.OfferInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.issue_offer(db, actor, str(match_id), data)}


@router.get("/offers/{offer_id}", tags=["offers"], response_model=r.RESPONSE_MODELS["get_offer"])
def get_offer(offer_id: UUID, db: Session = DB, actor: Actor = AUTH):
    offer = load(db, Offer, str(offer_id))
    match_id = db.scalar(select(MutualMatch.id).where(MutualMatch.pair_cycle_id == offer.pair_cycle_id))
    if not match_id:
        raise AppError(404, "NOT_FOUND", "Offer match was not found")
    workflow.participant(db, actor, match_id, active=False)
    return {
        "data": {
            "id": offer.id,
            "version": offer.version,
            "status": offer.status,
            "terms": decrypt(offer.terms_cipher).decode(),
            "start_at": offer.start_at,
            "expires_at": offer.expires_at,
        }
    }


@router.post("/offers/{offer_id}/accept", tags=["offers"], response_model=r.RESPONSE_MODELS["accept_offer"])
def accept_offer(offer_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.answer_offer(db, actor, str(offer_id), data.expected_version, True)}


@router.post("/offers/{offer_id}/decline", tags=["offers"], response_model=r.RESPONSE_MODELS["decline_offer"])
def decline_offer(offer_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.answer_offer(db, actor, str(offer_id), data.expected_version, False)}


@router.post(
    "/matches/{match_id}/starts/report", tags=["starts"], response_model=r.RESPONSE_MODELS["report_start"]
)
def report_start(match_id: UUID, data: s.StartInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.report_start(db, actor, str(match_id), data)}


@router.post(
    "/matches/{match_id}/starts/verify", tags=["starts"], response_model=r.RESPONSE_MODELS["verify_start"]
)
def verify_start(match_id: UUID, data: s.StartVerifyInput, db: Session = DB, actor: Actor = AUTH):
    return {"data": workflow.verify_start(db, actor, str(match_id), data)}


@router.post(
    "/matches/{match_id}/starts/dispute", tags=["starts"], response_model=r.RESPONSE_MODELS["dispute_start"]
)
def dispute_start(match_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    _, cycle, candidate, vacancy, _ = workflow.participant(db, actor, str(match_id), active=False)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    workflow.participant(db, actor, str(match_id), active=False)
    record = db.scalar(select(EmploymentStart).where(EmploymentStart.pair_cycle_id == cycle.id))
    if not record:
        raise AppError(404, "NOT_FOUND", "No employment start is recorded")
    require_version(record, data.expected_version)
    record.disputed_at, record.verification_state, record.version = utcnow(), "DISPUTED", record.version + 1
    emit(db, actor, "employment_start.disputed", record, org_id=vacancy.org_id)
    return {"data": {"status": "DISPUTED", "version": record.version}}


@router.get("/notifications", tags=["notifications"], response_model=r.RESPONSE_MODELS["notifications"])
def notifications(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1000),
    db: Session = DB,
    actor: Actor = AUTH,
):
    rows = [
        {
            "id": row.id,
            "version": row.version,
            "kind": row.kind,
            "entity_id": row.entity_id,
            "created_at": row.created_at,
            "read_at": row.read_at,
        }
        for row in db.scalars(
            select(Notification)
            .where(Notification.user_id == actor.user_id)
            .order_by(Notification.created_at.desc(), Notification.id)
        )
    ]
    return _page(rows, actor, "notifications", cursor, limit)


@router.post(
    "/notifications/{notification_id}/read",
    tags=["notifications"],
    response_model=r.RESPONSE_MODELS["read_notification"],
)
def read_notification(notification_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    row = load(db, Notification, str(notification_id))
    if row.user_id != actor.user_id:
        raise AppError(403, "FORBIDDEN", "Notification belongs to another user")
    require_version(row, data.expected_version)
    row.read_at, row.version = utcnow(), row.version + 1
    emit(db, actor, "notification.read", row)
    return {"data": {"id": row.id, "version": row.version, "read_at": row.read_at}}


@router.put(
    "/notifications/preferences",
    tags=["notifications"],
    response_model=r.RESPONSE_MODELS["notification_preferences"],
)
def notification_preferences(data: s.NotificationInput, db: Session = DB, actor: Actor = AUTH):
    lock_scopes(db, f"notification-preferences:{actor.user_id}")
    pref = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == actor.user_id))
    if pref:
        require_version(pref, data.expected_version)
        pref.version += 1
    else:
        if data.expected_version != 1:
            raise AppError(412, "VERSION_CONFLICT", "Use version one for initial notification preferences")
        pref = NotificationPreference(user_id=actor.user_id)
        db.add(pref)
    pref.email_opt_in, pref.in_app_opt_in, pref.quiet_hours = (
        data.email_opt_in,
        data.in_app_opt_in,
        data.quiet_hours,
    )
    emit(db, actor, "notification.preferences_updated", pref)
    return {
        "data": {
            "version": pref.version,
            "email_opt_in": pref.email_opt_in,
            "in_app_opt_in": pref.in_app_opt_in,
            "quiet_hours": pref.quiet_hours,
        }
    }


@router.post(
    "/privacy/export", status_code=202, tags=["privacy"], response_model=r.RESPONSE_MODELS["request_export"]
)
def request_export(db: Session = DB, actor: Actor = AUTH):
    row = PrivacyRequest(user_id=actor.user_id, kind="EXPORT")
    db.add(row)
    emit(db, actor, "privacy.export_requested", row)
    return {"data": {"operation_id": row.id, "status": row.status}}


@router.get(
    "/notifications/preferences",
    tags=["notifications"],
    response_model=r.Envelope[r.NotificationPreferencesOut],
)
def get_notification_preferences(db: Session = DB, actor: Actor = AUTH):
    pref = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == actor.user_id))
    return {
        "data": {
            "version": pref.version if pref else 1,
            "email_opt_in": pref.email_opt_in if pref else False,
            "in_app_opt_in": pref.in_app_opt_in if pref else True,
            "quiet_hours": pref.quiet_hours if pref else {},
        }
    }


@router.get("/privacy/export", tags=["privacy"], response_model=r.RESPONSE_MODELS["get_export"])
def get_export(db: Session = DB, actor: Actor = AUTH):
    row = db.scalar(
        select(PrivacyRequest)
        .where(PrivacyRequest.user_id == actor.user_id, PrivacyRequest.kind == "EXPORT")
        .order_by(PrivacyRequest.created_at.desc())
        .limit(1)
    )
    if not row:
        raise AppError(404, "EXPORT_REQUIRED", "Request an export first")
    return {
        "data": {
            "operation_id": row.id,
            "status": row.status,
            "export": json.loads(decrypt(row.result_cipher)) if row.result_cipher else None,
        }
    }


@router.post(
    "/privacy/delete", status_code=202, tags=["privacy"], response_model=r.RESPONSE_MODELS["request_deletion"]
)
def request_deletion(db: Session = DB, actor: Actor = AUTH):
    if actor.auth_time < utcnow() - timedelta(minutes=10):
        raise AppError(403, "REAUTH_REQUIRED", "Reauthenticate before requesting deletion")
    user = load(db, User, actor.user_id, lock=True)
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == actor.user_id))
    if candidate:
        lock_scopes(db, f"candidate:{candidate.id}")
        candidate = load(db, Candidate, candidate.id, lock=True)
        matching_learning.set_learning_consent(db, actor, candidate, False, candidate.version)
        candidate.state, candidate.version = "DEACTIVATED", candidate.version + 1
        for cycle in db.scalars(
            select(PairCycle).where(PairCycle.candidate_id == candidate.id, PairCycle.closed_at.is_(None))
        ):
            clearing.close_cycle(db, actor, cycle, "CLOSED_WITHDRAWN")
        invalidate(db, actor=actor, candidate_id=candidate.id, reason="ACCOUNT_DELETED")
        from app.db.pact_models import EvidenceGrant, TermConsent

        for model in (EvidenceGrant, TermConsent):
            for consent in db.scalars(
                select(model).where(model.candidate_id == candidate.id, model.revoked_at.is_(None))
            ):
                assert isinstance(consent, (EvidenceGrant, TermConsent))
                consent.revoked_at, consent.version = utcnow(), consent.version + 1
                emit(db, actor, "candidate.consent_revoked", consent)
        emit(db, actor, "candidate.deactivated", candidate)
    user.status, user.version = "DEACTIVATED", user.version + 1
    emit(db, actor, "account.deactivated", user)
    row = PrivacyRequest(user_id=actor.user_id, kind="DELETE")
    db.add(row)
    emit(db, actor, "privacy.delete_requested", row)
    return {
        "data": {
            "operation_id": row.id,
            "status": row.status,
            "notice": "Matching deactivated immediately; retained audit records and provider deletion reviewed separately",
        }
    }


@router.post("/reports", tags=["moderation"], response_model=r.RESPONSE_MODELS["report"])
def report(data: s.ReportInput, db: Session = DB, actor: Actor = AUTH):
    entity_id = str(data.entity_id)
    if data.entity_type == "VACANCY":
        vacancy = load(db, Vacancy, entity_id)
        if vacancy.state != "ACTIVE":
            require_vacancy(db, actor, vacancy.id)
    elif data.entity_type == "MATCH":
        workflow.participant(db, actor, entity_id, active=False)
    elif data.entity_type == "MESSAGE":
        workflow.participant(db, actor, load(db, Message, entity_id).match_id, active=False)
    else:
        offer = load(db, Offer, entity_id)
        match_id = db.scalar(select(MutualMatch.id).where(MutualMatch.pair_cycle_id == offer.pair_cycle_id))
        if not match_id:
            raise AppError(404, "NOT_FOUND", "Offer match was not found")
        workflow.participant(db, actor, match_id, active=False)
    row = AbuseReport(
        reporter_user_id=actor.user_id,
        entity_type=data.entity_type,
        entity_id=entity_id,
        reason=data.reason,
        description_cipher=encrypt(data.description),
    )
    db.add(row)
    emit(db, actor, "report.abuse_submitted", row)
    return {"data": {"id": row.id, "status": row.status}}


@router.get("/admin/reports", tags=["moderation"], response_model=r.RESPONSE_MODELS["reports"])
def reports(db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "SUPPORT")
    return {
        "data": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "reason": row.reason,
                "description": decrypt(row.description_cipher).decode(),
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
            }
            for row in db.scalars(select(AbuseReport).order_by(AbuseReport.created_at).limit(100))
        ]
    }


@router.post("/admin/users/{user_id}/status", tags=["moderation"], response_model=r.Envelope[r.StatusOut])
def account_status(user_id: UUID, data: s.AccountStatusInput, db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "OPERATIONS")
    if actor.auth_time < utcnow() - timedelta(minutes=10) or str(user_id) == actor.user_id:
        raise AppError(403, "REAUTH_REQUIRED", "Recent independent operator authentication is required")
    user = load(db, User, str(user_id), lock=True)
    require_version(user, data.expected_version)
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if candidate and data.status == "SUSPENDED":
        lock_scopes(db, f"candidate:{candidate.id}")
        candidate = load(db, Candidate, candidate.id, lock=True)
        candidate.state, candidate.version = "PAUSED", candidate.version + 1
        clearing.cancel_candidate_pending(db, actor, candidate.id, "ACCOUNT_SUSPENDED")
        invalidate(db, actor=actor, candidate_id=candidate.id, reason="ACCOUNT_SUSPENDED")
        emit(db, actor, "candidate.paused", candidate)
    user.status, user.version = data.status, user.version + 1
    emit(db, actor, "account.status_changed", user, payload={"reason_hash": digest(data.reason)})
    return {"data": {"status": user.status, "version": user.version}}


@router.post(
    "/admin/reports/{report_id}/resolve",
    tags=["moderation"],
    response_model=r.RESPONSE_MODELS["resolve_report"],
)
def resolve_report(report_id: UUID, data: s.ModerationInput, db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "SUPPORT")
    row = load(db, AbuseReport, str(report_id), lock=True)
    require_version(row, data.expected_version)
    row.status, row.resolution, row.version = data.status, data.resolution, row.version + 1
    emit(db, actor, "report.resolved", row)
    return {"data": {"id": row.id, "version": row.version, "status": row.status}}


@router.get("/internal/shadow/runs", tags=["research"], response_model=r.RESPONSE_MODELS["shadow_runs"])
def shadow_runs(db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "RESEARCH_ADMIN")
    return {
        "data": [
            {
                "id": row.id,
                "snapshot_hash": row.snapshot_hash,
                "baseline_hash": row.baseline_hash,
                "proposal_hash": row.proposal_hash,
                "diagnostics": row.diagnostics,
                "side_effect_count": row.side_effect_count,
            }
            for row in db.scalars(select(ShadowRun).order_by(ShadowRun.created_at.desc()).limit(100))
        ]
    }


@router.get(
    "/vacancies/{vacancy_id}/shortlist/status",
    tags=["research"],
    response_model=r.RESPONSE_MODELS["shortlist_status"],
)
def shortlist_status(vacancy_id: UUID, db: Session = DB, actor: Actor = AUTH):
    vacancy = require_vacancy(db, actor, str(vacancy_id))
    return {
        "data": {
            "vacancy_id": vacancy.id,
            "mode": get_settings().feature_mode,
            "delivered_candidate_ids": list(
                db.scalars(
                    select(Exposure.candidate_id)
                    .where(Exposure.vacancy_id == vacancy.id, Exposure.recipient_side == "EMPLOYER")
                    .distinct()
                )
            ),
            "certification_state": "CANNOT_CERTIFY",
            "reason": "NO_APPROVED_PROSPECTIVE_VALIDATION",
        }
    }


@router.post(
    "/vacancies/{vacancy_id}/shortlist/replan",
    status_code=202,
    tags=["research"],
    response_model=r.RESPONSE_MODELS["replan"],
)
def replan(vacancy_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    vacancy = require_vacancy(db, actor, str(vacancy_id), "edit")
    require_version(vacancy, data.expected_version)
    if get_settings().feature_mode != "SHADOW":
        raise AppError(409, "SHADOW_DISABLED", "Enable read-only shadow analysis before requesting a replan")
    event = emit(db, actor, "shortlist.replan_requested", vacancy, org_id=vacancy.org_id)
    db.flush()
    return {
        "data": {
            "operation_id": event.id,
            "status": "QUEUED",
            "mode": "SHADOW",
            "notice": "Analysis cannot issue advanced live introductions",
        }
    }


@router.post("/vacancies/{vacancy_id}/shortlist/approve", tags=["research"])
def approve_shortlist(vacancy_id: UUID, data: s.VersionInput, db: Session = DB, actor: Actor = AUTH):
    require_vacancy(db, actor, str(vacancy_id), "approve_policy")
    raise AppError(
        409, "PILOT_DISABLED", "Advanced execution requires an independently approved prospective pilot"
    )


@router.get("/organizations/{org_id}/billing", tags=["billing"], response_model=r.RESPONSE_MODELS["billing"])
def billing(org_id: UUID, db: Session = DB, actor: Actor = AUTH):
    require_org_role(db, actor, str(org_id), {"ORG_ADMIN"})
    org = load(db, Organization, str(org_id))
    return {
        "data": {
            "active_role_capacity": org.active_role_capacity,
            "payment_provider_status": "NOT_CONFIGURED",
            "ranking_influence": "NONE",
        }
    }
