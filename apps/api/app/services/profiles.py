from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.db.models import (
    Candidate,
    CandidateBlock,
    CandidateSkill,
    Invitation,
    Organization,
    OrgMember,
    Requirement,
    Skill,
    User,
    Vacancy,
    VacancyACL,
)
from app.schemas.core import CandidateInput, VacancyInput
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


def candidate_out(candidate: Candidate) -> dict:
    fields = (
        "id",
        "version",
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
        "available_from",
        "available_until",
        "compensation_period",
        "experiences",
        "education",
        "terms_accepted",
        "privacy_accepted",
        "confirmed_at",
    )
    return {
        **{key: getattr(candidate, key) for key in fields},
        "compensation_floor": decrypt(candidate.compensation_floor_cipher).decode()
        if candidate.compensation_floor_cipher
        else None,
    }


def organization_out(org: Organization) -> dict:
    return {
        key: getattr(org, key)
        for key in (
            "id",
            "version",
            "legal_name",
            "display_name",
            "domain",
            "verification_state",
            "active_role_capacity",
        )
    }


def vacancy_out(db: Session, vacancy: Vacancy) -> dict:
    fields = (
        "id",
        "version",
        "org_id",
        "owner_user_id",
        "title",
        "description",
        "role_family",
        "employment_type",
        "work_mode",
        "location_region",
        "pay_min",
        "pay_max",
        "currency",
        "compensation_period",
        "openings_total",
        "openings_remaining",
        "cap",
        "state",
        "deadline_at",
        "start_from",
        "start_until",
        "terms_hash",
    )
    result = {key: getattr(vacancy, key) for key in fields}
    result["organization_name"] = load(db, Organization, vacancy.org_id).display_name
    result["requirements"] = [
        {key: getattr(r, key) for key in ("id", "version", "key", "description", "kind", "lawful_reason")}
        for r in db.scalars(
            select(Requirement).where(Requirement.vacancy_id == vacancy.id).order_by(Requirement.id)
        )
    ]
    return result


def refresh_terms(db: Session, vacancy: Vacancy) -> None:
    db.flush()
    vacancy.terms_hash = digest(
        {
            "version": vacancy.version,
            "title": vacancy.title,
            "description": vacancy.description,
            "pay_min": str(vacancy.pay_min),
            "pay_max": str(vacancy.pay_max),
            "currency": vacancy.currency,
            "compensation_period": vacancy.compensation_period,
            "work_mode": vacancy.work_mode,
            "location": vacancy.location_region,
            "employment_type": vacancy.employment_type,
            "start_from": vacancy.start_from,
            "start_until": vacancy.start_until,
            "requirements": [
                (r.key, r.kind, r.description, r.version)
                for r in db.scalars(
                    select(Requirement).where(Requirement.vacancy_id == vacancy.id).order_by(Requirement.id)
                )
            ],
        }
    )


def save_candidate(db: Session, actor: Actor, data: CandidateInput) -> Candidate:
    from app.services.clearing import cancel_candidate_pending

    lock_scopes(db, f"candidate-user:{actor.user_id}")
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == actor.user_id))
    if candidate:
        lock_scopes(db, f"candidate:{candidate.id}")
        candidate = load(db, Candidate, candidate.id)
        require_version(candidate, data.expected_version)
        cancel_candidate_pending(db, actor, candidate.id, "PROFILE_CHANGED")
        candidate.version += 1
        invalidate(db, actor=actor, candidate_id=candidate.id)
    else:
        if data.expected_version != 0:
            raise AppError(412, "VERSION_CONFLICT", "Use version zero for a new profile")
        candidate = Candidate(user_id=actor.user_id)
        db.add(candidate)
    values = data.model_dump(exclude={"expected_version", "compensation_floor", "profile_confirmed"})
    for key, value in values.items():
        setattr(candidate, key, value)
    candidate.compensation_floor_cipher = (
        encrypt(str(data.compensation_floor)) if data.compensation_floor is not None else None
    )
    candidate.confirmed_at = utcnow()
    emit(db, actor, "candidate.profile_updated", candidate)
    return candidate


def save_preferences(db: Session, actor: Actor, data) -> Candidate:
    from app.services.clearing import cancel_candidate_pending

    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    candidate = load(db, Candidate, candidate.id)
    require_version(candidate, data.expected_version)
    cancel_candidate_pending(db, actor, candidate.id, "PREFERENCES_CHANGED")
    for key, value in data.model_dump(exclude={"expected_version", "compensation_floor"}).items():
        setattr(candidate, key, value)
    candidate.compensation_floor_cipher = (
        encrypt(str(data.compensation_floor)) if data.compensation_floor is not None else None
    )
    candidate.version += 1
    invalidate(db, actor=actor, candidate_id=candidate.id)
    emit(db, actor, "candidate.preferences_changed", candidate)
    return candidate


def candidate_state(db: Session, actor: Actor, expected: int, state: str) -> Candidate:
    from app.services.clearing import cancel_candidate_pending

    candidate = require_candidate(db, actor)
    lock_scopes(db, f"candidate:{candidate.id}")
    candidate = load(db, Candidate, candidate.id)
    require_version(candidate, expected)
    if state == "ACTIVE" and (
        not candidate.confirmed_at
        or not candidate.terms_accepted
        or not candidate.privacy_accepted
        or not candidate.role_families
        or not candidate.employment_types
        or not candidate.work_modes
    ):
        raise AppError(409, "PROFILE_INCOMPLETE", "Confirm profile, terms, privacy and preferences first")
    if state == "ACTIVE" and candidate.available_until and candidate.available_until <= utcnow():
        raise AppError(409, "AVAILABILITY_EXPIRED", "Update your availability before activating")
    if state == "PAUSED":
        cancel_candidate_pending(db, actor, candidate.id, "CANDIDATE_PAUSED")
    candidate.state = state
    candidate.version += 1
    invalidate(db, actor=actor, candidate_id=candidate.id)
    emit(db, actor, "candidate.activated" if state == "ACTIVE" else "candidate.paused", candidate)
    return candidate


def add_skill(db: Session, actor: Actor, data) -> dict:
    candidate = require_candidate(db, actor)
    name = data.name.casefold()
    lock_scopes(db, f"candidate:{candidate.id}", f"skill:{name}")
    candidate = load(db, Candidate, candidate.id)
    skill = db.scalar(select(Skill).where(Skill.name == name))
    if not skill:
        skill = Skill(name=name)
        db.add(skill)
        db.flush()
    if db.scalar(
        select(CandidateSkill).where(
            CandidateSkill.candidate_id == candidate.id, CandidateSkill.skill_id == skill.id
        )
    ):
        raise AppError(409, "SKILL_EXISTS", "This skill is already on the profile")
    assertion = CandidateSkill(candidate_id=candidate.id, skill_id=skill.id, level=data.level, confirmed=True)
    db.add(assertion)
    candidate.version += 1
    emit(
        db,
        actor,
        "candidate.skill_added",
        assertion,
        payload={"candidate_id": candidate.id, "candidate_version": candidate.version},
    )
    return {
        "id": assertion.id,
        "skill_id": skill.id,
        "name": name,
        "level": data.level,
        "verification_status": "SELF_REPORTED",
    }


def create_org(db: Session, actor: Actor, data) -> Organization:
    lock_scopes(db, f"org-domain:{data.domain}")
    if db.scalar(select(Organization).where(Organization.domain == data.domain)):
        raise AppError(
            409,
            "ORGANIZATION_REVIEW_REQUIRED",
            "An organization with this domain already exists; request membership review",
        )
    org = Organization(**data.model_dump(), created_by=actor.user_id)
    db.add(org)
    db.flush()
    db.add(OrgMember(org_id=org.id, user_id=actor.user_id, role="ORG_ADMIN", status="PENDING"))
    emit(db, actor, "organization.created", org, org_id=org.id)
    return org


def verify_org(db: Session, actor: Actor, org_id: str, data) -> Organization:
    require_platform(actor, "VERIFIER")
    lock_scopes(db, f"organization:{org_id}")
    org = load(db, Organization, org_id)
    require_version(org, data.expected_version)
    if org.created_by == actor.user_id:
        raise AppError(403, "SELF_VERIFICATION", "Independent organization verification is required")
    org.verification_state = "VERIFIED"
    org.verification_source_hash = digest(data.source_reference)
    org.verified_by = actor.user_id
    org.version += 1
    for member in db.scalars(
        select(OrgMember).where(
            OrgMember.org_id == org.id, OrgMember.role == "ORG_ADMIN", OrgMember.status == "PENDING"
        )
    ):
        member.status = "ACTIVE"
        member.approved_by = actor.user_id
    emit(db, actor, "organization.verified", org, org_id=org.id)
    return org


def grant_member(db: Session, actor: Actor, org_id: str, data) -> OrgMember:
    require_platform(actor, "VERIFIER")
    if str(data.user_id) == actor.user_id:
        raise AppError(403, "SELF_VERIFICATION", "You cannot approve your own authority")
    org = load(db, Organization, org_id)
    if org.verification_state != "VERIFIED":
        raise AppError(409, "UNVERIFIED_ORGANIZATION", "Verify the organization first")
    load(db, User, str(data.user_id))
    lock_scopes(db, f"membership:{org_id}:{data.user_id}")
    member = db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == str(data.user_id), OrgMember.role == data.role
        )
    )
    if member is None:
        member = OrgMember(org_id=org_id, user_id=str(data.user_id), role=data.role)
        db.add(member)
    else:
        member.version += 1
    if data.expires_at and data.expires_at <= utcnow():
        raise AppError(422, "INVALID_EXPIRY", "Membership must expire in the future")
    member.status, member.approved_by = "ACTIVE", actor.user_id
    member.source_hash, member.expires_at = digest(data.source_reference), data.expires_at
    emit(db, actor, "organization.member_added", member, org_id=org_id)
    return member


def invite(db: Session, actor: Actor, org_id: str, data) -> dict:
    require_org_role(db, actor, org_id, {"ORG_ADMIN"})
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        org_id=org_id,
        email=data.email.casefold(),
        role=data.role,
        token_hash=digest(token),
        expires_at=utcnow() + timedelta(days=7),
    )
    db.add(invitation)
    emit(db, actor, "organization.invitation_created", invitation, org_id=org_id)
    return {
        "id": invitation.id,
        "token": token,
        "expires_at": invitation.expires_at,
        "delivery_status": "MANUAL_DELIVERY_REQUIRED",
    }


def accept_invite(db: Session, actor: Actor, token: str) -> OrgMember:
    lock_scopes(db, f"invite:{digest(token)}")
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == digest(token)))
    user = load(db, User, actor.user_id)
    if (
        not invitation
        or invitation.expires_at <= utcnow()
        or invitation.accepted_at
        or user.verified_email.casefold() != invitation.email
    ):
        raise AppError(403, "INVALID_INVITATION", "Invitation is unavailable for this account")
    invitation.accepted_at = utcnow()
    member = OrgMember(org_id=invitation.org_id, user_id=actor.user_id, role=invitation.role)
    db.add(member)
    emit(db, actor, "organization.member_added", member, org_id=invitation.org_id)
    return member


def create_vacancy(db: Session, actor: Actor, data: VacancyInput) -> Vacancy:
    org_id = str(data.org_id)
    require_org_role(db, actor, org_id, {"ORG_ADMIN", "RECRUITER"})
    lock_scopes(db, f"vacancy-create:{org_id}:{data.title}:{data.location_region}")
    values = data.model_dump(exclude={"org_id"})
    duplicate = db.scalar(
        select(Vacancy).where(
            Vacancy.org_id == org_id,
            Vacancy.title == data.title,
            Vacancy.location_region == data.location_region,
            Vacancy.state.in_(["DRAFT", "ACTIVE", "PAUSED"]),
        )
    )
    if duplicate:
        raise AppError(409, "DUPLICATE_VACANCY", "Review the existing vacancy before creating a duplicate")
    vacancy = Vacancy(
        **values, org_id=org_id, owner_user_id=actor.user_id, openings_remaining=data.openings_total
    )
    db.add(vacancy)
    db.flush()
    db.add(VacancyACL(vacancy_id=vacancy.id, user_id=actor.user_id, can_review=True, can_edit=True))
    refresh_terms(db, vacancy)
    emit(db, actor, "vacancy.created", vacancy, org_id=org_id)
    return vacancy


def edit_vacancy(db: Session, actor: Actor, vacancy_id: str, data) -> Vacancy:
    from app.services.clearing import cancel_vacancy_pending

    vacancy = require_vacancy(db, actor, vacancy_id, "edit")
    lock_scopes(db, f"vacancy:{vacancy.id}")
    vacancy = load(db, Vacancy, vacancy.id)
    require_version(vacancy, data.expected_version)
    if (
        vacancy.org_id != str(data.org_id)
        or data.openings_total < vacancy.openings_total - vacancy.openings_remaining
    ):
        raise AppError(
            409, "INVALID_VACANCY_CHANGE", "Organization and already filled openings cannot be changed"
        )
    filled = vacancy.openings_total - vacancy.openings_remaining
    for key, value in data.model_dump(exclude={"expected_version", "org_id"}).items():
        setattr(vacancy, key, value)
    vacancy.openings_remaining = vacancy.openings_total - filled
    vacancy.version += 1
    vacancy.reviewed_by = None
    vacancy.state = "PAUSED" if vacancy.state == "ACTIVE" else vacancy.state
    cancel_vacancy_pending(db, actor, vacancy.id, "ROLE_CHANGED")
    refresh_terms(db, vacancy)
    invalidate(db, actor=actor, vacancy_id=vacancy.id, reason="ROLE_CHANGED")
    emit(db, actor, "vacancy.updated", vacancy, org_id=vacancy.org_id)
    return vacancy


def set_vacancy_state(db: Session, actor: Actor, vacancy_id: str, expected: int, state: str) -> Vacancy:
    from app.services.clearing import cancel_vacancy_pending

    vacancy = require_vacancy(db, actor, vacancy_id, "edit")
    lock_scopes(db, f"organization:{vacancy.org_id}", f"vacancy:{vacancy.id}")
    vacancy = load(db, Vacancy, vacancy.id)
    require_version(vacancy, expected)
    if vacancy.state in {"CLOSED", "FILLED"}:
        raise AppError(409, "VACANCY_TERMINAL", "Closed vacancies cannot be reopened")
    if state == "ACTIVE":
        org = load(db, Organization, vacancy.org_id)
        if org.verification_state != "VERIFIED" or vacancy.openings_remaining < 1:
            raise AppError(
                409, "ACTIVATION_BLOCKED", "Verified employer and an available opening are required"
            )
        if vacancy.deadline_at and vacancy.deadline_at <= utcnow():
            raise AppError(409, "ROLE_EXPIRED", "Vacancy deadline has passed")
        count = db.scalar(
            select(func.count())
            .select_from(Vacancy)
            .where(Vacancy.org_id == org.id, Vacancy.state == "ACTIVE", Vacancy.id != vacancy.id)
        )
        if (count or 0) >= org.active_role_capacity:
            raise AppError(409, "ROLE_CAPACITY_FULL", "Organization active vacancy capacity is full")
        if any(
            r.reviewed_by is None
            for r in db.scalars(select(Requirement).where(Requirement.vacancy_id == vacancy.id))
        ):
            raise AppError(409, "HUMAN_REVIEW_REQUIRED", "Review every requirement before activation")
        vacancy.reviewed_by = actor.user_id
    else:
        cancel_vacancy_pending(db, actor, vacancy.id, "JOB_CLOSED" if state == "CLOSED" else "ROLE_PAUSED")
    vacancy.state = state
    vacancy.version += 1
    refresh_terms(db, vacancy)
    invalidate(db, actor=actor, vacancy_id=vacancy.id)
    emit(
        db,
        actor,
        f"vacancy.{dict(ACTIVE='activated', PAUSED='paused', CLOSED='closed')[state]}",
        vacancy,
        org_id=vacancy.org_id,
    )
    return vacancy


def set_requirement(
    db: Session, actor: Actor, vacancy_id: str, data, requirement_id: str | None = None
) -> Requirement:
    from app.services.clearing import cancel_vacancy_pending

    vacancy = require_vacancy(db, actor, vacancy_id, "edit")
    lock_scopes(db, f"vacancy:{vacancy.id}")
    vacancy = load(db, Vacancy, vacancy.id)
    requirement = load(db, Requirement, requirement_id) if requirement_id else None
    require_version(requirement or vacancy, data.expected_version)
    if requirement and requirement.vacancy_id != vacancy.id:
        raise AppError(403, "FORBIDDEN", "Requirement is outside this vacancy")
    if (
        requirement
        and requirement.kind == "ESSENTIAL"
        and (data.kind != "ESSENTIAL" or data.key != requirement.key)
    ):
        raise AppError(
            409, "ESSENTIAL_CANNOT_BE_RELAXED", "An essential requirement cannot be waived or relabeled"
        )
    if requirement is None:
        requirement = Requirement(vacancy_id=vacancy.id)
        db.add(requirement)
    else:
        requirement.version += 1
    for key, value in data.model_dump(exclude={"expected_version", "human_reviewed"}).items():
        setattr(requirement, key, value)
    requirement.reviewed_by = actor.user_id
    vacancy.version += 1
    cancel_vacancy_pending(db, actor, vacancy.id, "REQUIREMENTS_CHANGED")
    refresh_terms(db, vacancy)
    invalidate(db, actor=actor, vacancy_id=vacancy.id)
    emit(db, actor, "vacancy.requirements_updated", requirement, org_id=vacancy.org_id)
    return requirement


def block_org(db: Session, actor: Actor, org_id: str) -> None:
    from app.db.models import PairCycle
    from app.services.clearing import close_cycle

    candidate = require_candidate(db, actor)
    load(db, Organization, org_id)
    lock_scopes(db, f"candidate:{candidate.id}")
    block = db.scalar(
        select(CandidateBlock).where(
            CandidateBlock.candidate_id == candidate.id, CandidateBlock.org_id == org_id
        )
    )
    if block:
        return
    block = CandidateBlock(candidate_id=candidate.id, org_id=org_id)
    db.add(block)
    for cycle in db.scalars(
        select(PairCycle)
        .join(Vacancy, PairCycle.vacancy_id == Vacancy.id)
        .where(
            PairCycle.candidate_id == candidate.id, Vacancy.org_id == org_id, PairCycle.closed_at.is_(None)
        )
    ):
        close_cycle(db, actor, cycle, "CLOSED_WITHDRAWN")
    invalidate(db, actor=actor, candidate_id=candidate.id, reason="ORG_BLOCKED")
    emit(db, actor, "candidate.org_blocked", block)
