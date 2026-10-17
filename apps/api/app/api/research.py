from dataclasses import asdict
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.core.errors import AppError
from app.db.models import OutboxEvent, ShadowRun
from app.matching.portfolio import MarketSnapshot, ResearchEdge, VacancyResearch
from app.matching.scenario import CandidateProbability, RiskScenario, ScenarioModel
from app.matching.shadow_adapter import run_shadow
from app.schemas.research import ReplayEnvelope, ReplayInput
from app.schemas.responses import Envelope, ShadowRunOut
from app.services.common import Actor, digest, emit, load, require_platform

router = APIRouter(route_class=TransactionalRoute, tags=["research"])


@router.post("/internal/shadow/replay", response_model=ReplayEnvelope)
def replay(data: ReplayInput, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    require_platform(actor, "RESEARCH_ADMIN")
    try:
        vacancies = tuple(
            VacancyResearch(
                job.vacancy_id,
                job.role_version,
                job.shortlist_limit,
                tuple(
                    ScenarioModel(
                        model.version,
                        tuple(
                            RiskScenario(
                                s.scenario_id,
                                s.weight,
                                tuple(CandidateProbability(p.candidate_id, p.success) for p in s.candidates),
                                s.job_wide_failure,
                                s.assumption_version,
                            )
                            for s in model.scenarios
                        ),
                        model.conditional_independence_asserted,
                    )
                    for model in job.models
                ),
            )
            for job in data.vacancies
        )
        snapshot = MarketSnapshot(
            data.state_version,
            vacancies,
            tuple(
                ResearchEdge(
                    edge.candidate_id,
                    edge.vacancy_id,
                    edge.routing_value,
                    edge.attention_cost,
                    edge.delay_cost,
                )
                for edge in data.edges
            ),
        )
    except ValueError as exc:
        raise AppError(422, "INVALID_RESEARCH_MODEL", str(exc)) from exc
    # Offline-only synthetic input: no ORM/session/notification capability reaches the planner.
    result = run_shadow(snapshot, (), enabled=True)
    event = OutboxEvent(
        aggregate_id=str(uuid4()),
        kind="shadow.offline_replay",
        payload={"input_hash": snapshot.digest, "fictional_only": True},
    )
    db.add(event)
    db.flush()
    run = ShadowRun(
        event_id=event.id,
        snapshot_hash=snapshot.digest,
        baseline_hash=result.baseline_proposal_hash,
        proposal_hash=digest(asdict(result.advanced_plan)) if result.advanced_plan else digest(None),
        diagnostics={
            "fictional_only": True,
            "reasons": list(result.reasons),
            "plan": asdict(result.advanced_plan) if result.advanced_plan else None,
            "certification_state": "CANNOT_CERTIFY",
        },
        side_effect_count=0,
    )
    db.add(run)
    emit(db, actor, "shadow.completed", run)
    return {
        "data": {
            "run_id": run.id,
            "snapshot_hash": run.snapshot_hash,
            "mode": "SHADOW",
            "certification_state": "CANNOT_CERTIFY",
            "side_effect_count": 0,
            "reasons": list(result.reasons),
        }
    }


@router.get("/internal/shadow/runs/{run_id}", response_model=Envelope[ShadowRunOut])
def get_run(run_id: UUID, db: Session = Depends(db_dep), actor: Actor = Depends(actor_dep)):
    require_platform(actor, "RESEARCH_ADMIN")
    row = load(db, ShadowRun, str(run_id))
    return {
        "data": {
            "id": row.id,
            "snapshot_hash": row.snapshot_hash,
            "baseline_hash": row.baseline_hash,
            "proposal_hash": row.proposal_hash,
            "diagnostics": row.diagnostics,
            "side_effect_count": row.side_effect_count,
        }
    }
