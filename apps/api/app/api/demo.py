"""Local synthetic-market demonstration through the normal transactional executor.

These routes cannot enable a market or mint identities. Preparation is an explicit
local CLI action, guarded by the separate database name and import ownership.
"""

from __future__ import annotations

import json
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.core.errors import AppError
from app.db.models import AuditEvent, Candidate, IdempotencyRecord, Organization, PairCycle, Vacancy
from app.schemas.core import ErrorEnvelope
from app.schemas.responses import Envelope
from app.services import clearing
from app.services.common import Actor, require_org_role, require_vacancy

SAMPLE_DATABASE = "career_kitchen_samples"
IMPORT_MARKER = "career-kitchen-synthetic-samples-v1"
DEMO_MARKER = "career-kitchen-synthetic-demo-v1"
DEMO_ROUTE = "sample-demo/v1"
DEMO_KEY = "fictional-eligibility"
POOL_LIMIT = 40
VACANCY_LIMIT = 4
WORKSPACE_VACANCY_LIMIT = 8


def sample_identity(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://career-kitchen.example.invalid/samples/v1/{label}"))


def require_sample_database(db: Session, settings) -> dict:
    """Fail closed before reading sample profiles or changing fictional state."""
    configured = make_url(settings.database_url)
    actual = db.get_bind().engine.url
    hosted = (
        settings.environment in {"staging", "production"}
        and settings.auth_mode == "supabase"
        and settings.sample_demo_enabled
        and not settings.allow_dev_auth
        and configured.query.get("sslmode") in {"require", "verify-ca", "verify-full"}
        and actual.query.get("sslmode") in {"require", "verify-ca", "verify-full"}
    )
    local = (
        settings.environment in {"development", "test"}
        and settings.auth_mode == "local"
        and settings.allow_dev_auth
        and configured.host in {"127.0.0.1", "localhost", "::1"}
        and actual.host in {"127.0.0.1", "localhost", "::1"}
    )
    if (
        not (hosted or local)
        or configured.host != actual.host
        or configured.port != actual.port
        or configured.database != SAMPLE_DATABASE
        or actual.database != SAMPLE_DATABASE
        or set(configured.query) - {"sslmode"}
        or set(actual.query) - {"sslmode"}
        or db.scalar(text("SELECT current_database()")) != SAMPLE_DATABASE
    ):
        raise AppError(404, "DEMO_UNAVAILABLE", "Sample demonstration is unavailable")
    if not db.scalar(text("SELECT to_regclass('ck_sample_marker')")):
        raise AppError(404, "DEMO_UNAVAILABLE", "Sample demonstration is unavailable")
    if list(db.scalars(text("SELECT marker FROM ck_sample_marker"))) != [IMPORT_MARKER]:
        raise AppError(404, "DEMO_UNAVAILABLE", "Sample demonstration is unavailable")
    imported = db.get(IdempotencyRecord, (sample_identity("importer"), "sample-import/v1", "initial-import"))
    if not imported:
        raise AppError(404, "DEMO_UNAVAILABLE", "Sample import has not completed")
    result = json.loads(imported.response_json)
    if result.get("import_version") != IMPORT_MARKER or result.get("synthetic") is not True:
        raise AppError(404, "DEMO_UNAVAILABLE", "Sample import is unrecognized")
    return result


def require_sample_demo(request: Request, db: Session, *, require_ready: bool = True) -> dict:
    if not getattr(request.app.state.settings, "sample_demo_enabled", False):
        raise AppError(404, "DEMO_UNAVAILABLE", "Sample demonstration is disabled")
    imported = require_sample_database(db, request.app.state.settings)
    receipt = db.get(IdempotencyRecord, (sample_identity("importer"), DEMO_ROUTE, DEMO_KEY))
    if not receipt:
        if require_ready:
            raise AppError(409, "DEMO_NOT_PREPARED", "Prepare the fictional sample demonstration first")
        return {**imported, "ready": False}
    prepared = json.loads(receipt.response_json)
    if prepared.get("demo_version") != DEMO_MARKER or prepared.get("synthetic") is not True:
        raise AppError(404, "DEMO_UNAVAILABLE", "Sample demonstration is unrecognized")
    return prepared


def authorize_demo_actor(db: Session, actor: Actor) -> Candidate | None:
    """Use persisted sample identities, organization membership and normal ACLs."""
    if actor.user_id == sample_identity("employer"):
        require_org_role(db, actor, sample_identity("org-000001"), {"ORG_ADMIN", "RECRUITER"})
        return None
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == actor.user_id))
    if candidate and db.scalar(
        select(AuditEvent.id)
        .where(
            AuditEvent.entity_id == candidate.id,
            AuditEvent.entity_type == Candidate.__tablename__,
            AuditEvent.actor_id == sample_identity("importer"),
            AuditEvent.action == "sample.imported",
        )
        .limit(1)
    ):
        # Immutable import provenance authorizes the fixture, not its editable
        # headline. Profile edits keep the same authenticated participant.
        return candidate
    raise AppError(403, "DEMO_ACCOUNT_REQUIRED", "Use an imported fictional sample account")


def workspace_vacancies(db: Session, prepared: dict) -> list[str]:
    """Keep more roles ready for replenishment than a single allocation batch."""
    candidate = db.get(Candidate, sample_identity("candidate-000001"))
    extra = list(
        db.scalars(
            select(Vacancy.id)
            .where(
                Vacancy.org_id == sample_identity("org-000001"),
                Vacancy.state == "ACTIVE",
                Vacancy.role_family.in_(candidate.role_families if candidate else []),
            )
            .order_by(Vacancy.id)
            .limit(WORKSPACE_VACANCY_LIMIT)
        )
    )
    return list(dict.fromkeys([*prepared.get("vacancy_ids", []), *extra]))[:WORKSPACE_VACANCY_LIMIT]


router = APIRouter(
    route_class=TransactionalRoute,
    tags=["sample demonstration"],
    responses={status: {"model": ErrorEnvelope} for status in (401, 403, 404, 409, 422)},
)


class DemoStatus(BaseModel):
    ready: bool
    synthetic: Literal[True]
    demo_version: str | None
    candidates: int
    vacancies: int
    organizations: int
    active_candidates: int
    active_vacancies: int
    organization_id: str
    candidate_user_id: str
    vacancy_ids: list[str]
    matching: str
    learning_opt_in: Literal[False]
    disclosure: str


class DemoDecision(BaseModel):
    decision_id: str
    candidate_id: str
    vacancy_id: str
    side: Literal["CANDIDATE", "EMPLOYER"]


class DemoAllocation(BaseModel):
    synthetic: Literal[True]
    issued: list[DemoDecision]
    issued_count: int
    vacancies_considered: int
    candidate_pool_limit: int
    matching: str
    double_opt_in_required: Literal[True]


@router.get("/demo/status", response_model=Envelope[DemoStatus])
def status(request: Request, db: Session = Depends(db_dep)):
    prepared = require_sample_demo(request, db, require_ready=False)
    return {
        "data": {
            "ready": prepared.get("ready", False),
            "synthetic": True,
            "demo_version": prepared.get("demo_version"),
            "candidates": db.scalar(select(func.count()).select_from(Candidate)) or 0,
            "vacancies": db.scalar(select(func.count()).select_from(Vacancy)) or 0,
            "organizations": db.scalar(select(func.count()).select_from(Organization)) or 0,
            "active_candidates": db.scalar(
                select(func.count()).select_from(Candidate).where(Candidate.state == "ACTIVE")
            )
            or 0,
            "active_vacancies": db.scalar(
                select(func.count()).select_from(Vacancy).where(Vacancy.state == "ACTIVE")
            )
            or 0,
            "organization_id": sample_identity("org-000001"),
            "candidate_user_id": sample_identity("candidate-user-000001"),
            "vacancy_ids": workspace_vacancies(db, prepared) if prepared.get("ready") else [],
            "matching": "deterministic transactional optimizer",
            "learning_opt_in": False,
            "disclosure": "Fictional sample applicants, jobs, eligibility and company verification. Decisions require both participants; no real outcomes or learning consent.",
        }
    }


class ReconcileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/demo/reconcile", response_model=Envelope[DemoAllocation])
def reconcile(
    body: ReconcileInput,
    request: Request,
    db: Session = Depends(db_dep),
    actor: Actor = Depends(actor_dep),
):
    prepared = require_sample_demo(request, db)
    candidate = authorize_demo_actor(db, actor)
    targets = workspace_vacancies(db, prepared)
    if candidate is not None:
        compatible = list(
            db.scalars(
                select(Vacancy.id)
                .where(
                    Vacancy.id.in_(targets),
                    Vacancy.state == "ACTIVE",
                    Vacancy.role_family.in_(candidate.role_families),
                    ~select(PairCycle.id)
                    .where(PairCycle.candidate_id == candidate.id, PairCycle.vacancy_id == Vacancy.id)
                    .exists(),
                )
                .order_by(Vacancy.id)
                .limit(VACANCY_LIMIT)
            )
        )
        targets = compatible
        candidate_ids = [candidate.id]
    else:
        targets = targets[:VACANCY_LIMIT]
        for vacancy_id in targets:
            require_vacancy(db, actor, vacancy_id)
        candidate_ids = None
    issued = (
        clearing.reconcile(db, actor, vacancy_ids=targets, pool_limit=POOL_LIMIT, candidate_ids=candidate_ids)
        if targets
        else []
    )
    # Candidate-side cards for other participants are never disclosed to employer.
    visible = [item for item in issued if item["side"] == ("CANDIDATE" if candidate else "EMPLOYER")]
    if candidate:
        visible = [item for item in visible if item["candidate_id"] == candidate.id]
    return {
        "data": {
            "synthetic": True,
            "issued": visible,
            "issued_count": len(issued),
            "vacancies_considered": len(targets),
            "candidate_pool_limit": POOL_LIMIT if candidate is None else 1,
            "matching": "deterministic transactional optimizer",
            "double_opt_in_required": True,
        }
    }
