"""Explicit learning consent and restricted, versioned matching model registry."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StrictBool, StrictInt
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.db.models import Organization
from app.schemas.core import ErrorEnvelope, Input
from app.schemas.responses import Envelope
from app.services import matching_learning
from app.services.common import Actor, load, require_candidate, require_org_role, require_platform

ModelId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class LearningConsentInput(Input):
    enabled: StrictBool
    expected_version: StrictInt = Field(ge=1)


class LearningConsentOut(BaseModel):
    enabled: bool
    version: int
    consent_version: int


class MatchingModelInput(Input):
    artifact: dict[str, Any]
    evaluation: dict[str, Any]
    expected_active_model_id: ModelId | None


class MatchingModelRetireInput(Input):
    expected_active_model_id: ModelId
    reason: str = Field(min_length=8, max_length=500)


class MatchingModelOut(BaseModel):
    active: bool
    model_id: ModelId | None
    version: int | None


router = APIRouter(
    route_class=TransactionalRoute,
    tags=["matching-learning"],
    responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 412, 422, 429)},
)
DB = Depends(db_dep)
AUTH = Depends(actor_dep)


@router.get("/candidates/me/learning-consent", response_model=Envelope[LearningConsentOut])
def get_candidate_learning_consent(db: Session = DB, actor: Actor = AUTH):
    return {"data": matching_learning.consent_state(require_candidate(db, actor))}


@router.put("/candidates/me/learning-consent", response_model=Envelope[LearningConsentOut])
def put_candidate_learning_consent(data: LearningConsentInput, db: Session = DB, actor: Actor = AUTH):
    return {
        "data": matching_learning.set_learning_consent(
            db, actor, require_candidate(db, actor), data.enabled, data.expected_version
        )
    }


@router.get("/organizations/{org_id}/learning-consent", response_model=Envelope[LearningConsentOut])
def get_organization_learning_consent(org_id: UUID, db: Session = DB, actor: Actor = AUTH):
    require_org_role(db, actor, str(org_id), {"ORG_ADMIN"})
    return {"data": matching_learning.consent_state(load(db, Organization, str(org_id)))}


@router.put("/organizations/{org_id}/learning-consent", response_model=Envelope[LearningConsentOut])
def put_organization_learning_consent(
    org_id: UUID, data: LearningConsentInput, db: Session = DB, actor: Actor = AUTH
):
    require_org_role(db, actor, str(org_id), {"ORG_ADMIN"})
    return {
        "data": matching_learning.set_learning_consent(
            db, actor, load(db, Organization, str(org_id)), data.enabled, data.expected_version
        )
    }


@router.get("/internal/matching/model", response_model=Envelope[MatchingModelOut])
def get_matching_model(db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "RESEARCH_ADMIN", "SYSTEM_WORKER")
    return {"data": matching_learning.active_model_info(db)}


@router.post("/internal/matching/model", response_model=Envelope[MatchingModelOut])
def activate_matching_model(data: MatchingModelInput, db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "RESEARCH_ADMIN", "SYSTEM_WORKER")
    return {
        "data": matching_learning.promote_model(
            db, actor, data.artifact, data.evaluation, data.expected_active_model_id
        )
    }


@router.post("/internal/matching/model/retire", response_model=Envelope[MatchingModelOut])
def retire_matching_model(data: MatchingModelRetireInput, db: Session = DB, actor: Actor = AUTH):
    require_platform(actor, "RESEARCH_ADMIN", "SYSTEM_WORKER")
    return {
        "data": matching_learning.retire_current_model(db, actor, data.expected_active_model_id, data.reason)
    }
