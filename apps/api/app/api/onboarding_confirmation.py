"""Commit a user's reviewed profile and skills in one existing transaction."""

from fastapi import APIRouter, Depends
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.core.errors import AppError
from app.db.models import CandidateSkill, Skill
from app.matching.reciprocal import normalize_skill
from app.schemas.onboarding_confirmation import (
    ConfirmedOnboardingSkill,
    OnboardingConfirmationIn,
    OnboardingConfirmationOut,
)
from app.schemas.responses import Envelope
from app.services import profiles
from app.services.common import Actor, emit, lock_scopes

router = APIRouter(route_class=TransactionalRoute, tags=["onboarding"])


@router.post(
    "/candidates/me/onboarding",
    response_model=Envelope[OnboardingConfirmationOut],
    summary="Confirm a reviewed onboarding profile and self-reported skills",
    description=(
        "Explicit user confirmation saves profile preferences and selected skill levels atomically. "
        "AI exercises are informal guidance, not independent verification. Existing skills not in "
        "the request are preserved. New profiles remain drafts until explicitly activated."
    ),
)
def confirm_onboarding(
    body: OnboardingConfirmationIn,
    actor: Actor = Depends(actor_dep),
    db: Session = Depends(db_dep),
):
    # save_candidate locks the actor-owned aggregate, rechecks the version and
    # invalidates pending introductions before any confirmed features change.
    candidate = profiles.save_candidate(db, actor, body.profile)
    # Only existing curated aliases establish equivalence. Gemini cannot create
    # taxonomy aliases or turn an inferred abbreviation into an asserted skill.
    lock_scopes(db, "skill-taxonomy")
    curated = list(db.scalars(select(Skill).where(cast(Skill.aliases, JSONB) != [])))
    resolved: list[tuple[ConfirmedOnboardingSkill, Skill | None, str]] = []
    seen = set()
    for item in body.skills:
        skill = db.scalar(select(Skill).where(Skill.name == item.name))
        if skill is None:
            matches = [row for row in curated if item.name in {normalize_skill(x) for x in row.aliases}]
            if len(matches) > 1:
                raise AppError(409, "SKILL_ALIAS_AMBIGUOUS", "Choose an unambiguous canonical skill name")
            skill = matches[0] if matches else None
        name = skill.name if skill is not None else item.name
        if name in seen:
            raise AppError(422, "DUPLICATE_SKILL", "Confirm each canonical skill only once")
        seen.add(name)
        resolved.append((item, skill, name))
    lock_scopes(db, *(f"skill:{name}" for _, _, name in resolved))
    for item, skill, name in resolved:
        if skill is None:
            # The canonical lock also coordinates with ordinary profile edits.
            skill = db.scalar(select(Skill).where(Skill.name == name))
            if skill is None:
                skill = Skill(name=name)
                db.add(skill)
                db.flush()
        assertion = db.scalar(
            select(CandidateSkill).where(
                CandidateSkill.candidate_id == candidate.id,
                CandidateSkill.skill_id == skill.id,
            )
        )
        if assertion is None:
            assertion = CandidateSkill(
                candidate_id=candidate.id, skill_id=skill.id, level=item.level, confirmed=True
            )
            db.add(assertion)
            action = "candidate.skill_added"
        elif assertion.level != item.level or not assertion.confirmed:
            assertion.level = item.level
            assertion.confirmed = True
            assertion.version += 1
            action = "candidate.skill_updated"
        else:
            continue
        emit(
            db,
            actor,
            action,
            assertion,
            payload={"candidate_id": candidate.id, "candidate_version": candidate.version},
        )
    emit(
        db,
        actor,
        "candidate.onboarding_confirmed",
        candidate,
        payload={
            "contract_version": 1,
            "reviewed_skill_count": len(body.skills),
            "skills_confirmed": True,
            "skill_source": "SELF_REPORTED",
        },
    )
    skills = [
        {
            "id": assertion.id,
            "skill_id": taxonomy.id,
            "name": taxonomy.name,
            "level": assertion.level,
            "version": assertion.version,
            "verification_status": "SELF_REPORTED",
        }
        for assertion, taxonomy in db.execute(
            select(CandidateSkill, Skill)
            .join(Skill, CandidateSkill.skill_id == Skill.id)
            .where(CandidateSkill.candidate_id == candidate.id)
            .order_by(Skill.name)
        )
    ]
    return {
        "data": {
            "candidate": profiles.candidate_out(candidate),
            "skills": skills,
            "version": candidate.version,
        }
    }
