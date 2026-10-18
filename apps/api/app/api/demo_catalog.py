"""Bounded browsing of explicitly fictional records in the isolated sample market."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.demo import authorize_demo_actor, require_sample_demo, sample_identity
from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.db.models import AuditEvent, Candidate, CandidateSkill, Requirement, Skill, Vacancy
from app.schemas.responses import Envelope
from app.services.common import Actor

router = APIRouter(route_class=TransactionalRoute, tags=["sample demo"])


class SampleRecord(BaseModel):
    id: str
    title: str
    summary: str
    skills: list[str]
    region: str
    state: str
    version: int


class SampleCatalog(BaseModel):
    kind: Literal["jobs", "applicants"]
    synthetic: bool = True
    total: int
    offset: int
    next_offset: int | None
    items: list[SampleRecord]


@router.get("/demo/catalog", response_model=Envelope[SampleCatalog])
def sample_catalog(
    request: Request,
    kind: Literal["jobs", "applicants"] = "jobs",
    q: str = Query(default="", max_length=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=24, ge=1, le=48),
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    require_sample_demo(request, db)
    authorize_demo_actor(db, actor)
    model: type[Vacancy] | type[Candidate] = Vacancy if kind == "jobs" else Candidate
    title = Vacancy.title if kind == "jobs" else Candidate.headline
    summary = Vacancy.description if kind == "jobs" else Candidate.summary
    region = Vacancy.location_region if kind == "jobs" else Candidate.region
    query = select(
        model.id,
        title.label("title"),
        summary.label("summary"),
        region.label("region"),
        model.state,
        model.version,
    ).where(
        title.startswith("[SYNTHETIC "),
        # Only unchanged import fixtures are public catalogue material. An
        # account cannot publish a private draft by editing its title, and later
        # profile/job edits keep their ordinary participant authorization.
        model.version == 2,
        select(AuditEvent.id)
        .where(
            AuditEvent.entity_id == model.id,
            AuditEvent.entity_type == model.__tablename__,
            AuditEvent.action == "sample.imported",
            AuditEvent.actor_id == sample_identity("importer"),
        )
        .exists(),
    )
    search = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if search:
        pattern = f"%{search}%"
        skill_match = (
            select(Requirement.id)
            .where(Requirement.vacancy_id == Vacancy.id, Requirement.key.ilike(pattern, escape="\\"))
            .exists()
            if kind == "jobs"
            else select(CandidateSkill.id)
            .join(Skill, Skill.id == CandidateSkill.skill_id)
            .where(CandidateSkill.candidate_id == Candidate.id, Skill.name.ilike(pattern, escape="\\"))
            .exists()
        )
        query = query.where(
            title.ilike(pattern, escape="\\") | summary.ilike(pattern, escape="\\") | skill_match
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(db.execute(query.order_by(model.id).offset(offset).limit(limit)).mappings())
    identifiers = [row["id"] for row in rows]
    skills: dict[str, list[str]] = {row["id"]: [] for row in rows}
    if identifiers and kind == "jobs":
        for entity_id, key in db.execute(
            select(Requirement.vacancy_id, Requirement.key)
            .where(Requirement.vacancy_id.in_(identifiers))
            .order_by(Requirement.key)
        ):
            skills[entity_id].append(key)
    elif identifiers:
        for entity_id, name in db.execute(
            select(CandidateSkill.candidate_id, Skill.name)
            .join(Skill, Skill.id == CandidateSkill.skill_id)
            .where(CandidateSkill.candidate_id.in_(identifiers))
            .order_by(Skill.name)
        ):
            skills[entity_id].append(name)
    return {
        "data": SampleCatalog(
            kind=kind,
            total=total,
            offset=offset,
            next_offset=offset + len(rows) if offset + len(rows) < total else None,
            items=[
                SampleRecord(
                    id=row["id"],
                    title=row["title"],
                    summary=row["summary"],
                    skills=skills[row["id"]],
                    region=row["region"],
                    state=row["state"],
                    version=row["version"],
                )
                for row in rows
            ],
        )
    }
