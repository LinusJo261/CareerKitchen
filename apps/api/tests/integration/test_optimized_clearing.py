"""Real PostgreSQL execution checks for optimized attention plans and consent."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from math import sqrt
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.errors import AppError
from app.core.security import decrypt
from app.db.models import (
    AuditEvent,
    Candidate,
    CandidateBlock,
    CandidateSkill,
    DecisionCard,
    Exposure,
    MarketPrice,
    MutualMatch,
    OrgMember,
    OutboxEvent,
    PairCycle,
    Requirement,
    Skill,
    User,
    Vacancy,
    VacancyACL,
    WaitingItem,
)
from app.services import clearing
from app.services.common import Actor, utcnow
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres


def candidates(db, total, *, active=True):
    result = []
    for _ in range(total):
        user = User(issuer="fictional-optimized-clearing", subject=str(uuid4()))
        db.add(user)
        db.flush()
        candidate = Candidate(
            user_id=user.id,
            headline="Fictional allocation fixture",
            state="ACTIVE" if active else "DRAFT",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
            cap=1,
        )
        db.add(candidate)
        db.flush()
        result.append(candidate)
    return result


def vacancies(db, market, total):
    result = []
    for index in range(total):
        vacancy = Vacancy(
            org_id=market.org.id,
            owner_user_id=market.users[1].id,
            title=f"Fictional allocation role {index}",
            description="Fictional test fixture only.",
            role_family="ENGINEERING",
            employment_type="FULL_TIME",
            work_mode="REMOTE",
            pay_min=80000,
            pay_max=120000,
            currency="USD",
            state="ACTIVE",
            cap=1,
            reviewed_by=market.users[1].id,
        )
        db.add(vacancy)
        db.flush()
        db.add(VacancyACL(vacancy_id=vacancy.id, user_id=market.users[1].id, can_review=True))
        result.append(vacancy)
    return result


def reserve_waiting(db, vacancy, total):
    for candidate in candidates(db, total, active=False):
        cycle = PairCycle(
            candidate_id=candidate.id,
            vacancy_id=vacancy.id,
            role_version=vacancy.version,
            first_mover="CANDIDATE",
            state="WAITING_EMPLOYER_SLOT",
            candidate_interested_at=utcnow(),
        )
        db.add(cycle)
        db.flush()
        db.add(WaitingItem(pair_cycle_id=cycle.id, side="EMPLOYER", expires_at=utcnow() + timedelta(days=1)))
    db.flush()


def test_live_reconcile_improves_actual_structured_compatibility_and_audits_execution(market):
    with Session(market.engine) as db, db.begin():
        first = db.get(Candidate, market.candidate.id)
        first.cap = 1
        first.role_families = ["ENGINEERING", "DESIGN"]
        second = candidates(db, 1)[0]
        role_x = db.get(Vacancy, market.vacancy.id)
        role_y = vacancies(db, market, 1)[0]
        role_y.role_family = "DESIGN"
        skill = Skill(name="Fictional Python", aliases=[])
        db.add(skill)
        db.flush()
        db.add(CandidateSkill(candidate_id=first.id, skill_id=skill.id, confirmed=True))
        db.add_all(
            [
                Requirement(
                    vacancy_id=role_x.id, kind="PREFERENCE", key=skill.name, description="Fixture preference"
                ),
                Requirement(
                    vacancy_id=role_y.id,
                    kind="PREFERENCE",
                    key="Fictional Design",
                    description="Fixture preference",
                ),
            ]
        )
        reserve_waiting(db, role_x, 9)
        reserve_waiting(db, role_y, 9)
        issued = clearing.reconcile(db, market.actor(2), [role_x.id, role_y.id])
        assert {(row["candidate_id"], row["vacancy_id"]) for row in issued} == {
            (first.id, role_y.id),
            (second.id, role_x.id),
        }
        cycles = list(db.scalars(select(PairCycle).where(PairCycle.state == "CANDIDATE_DECISION_REQUIRED")))
        assert len(cycles) == 2
        for cycle in cycles:
            allocation = cycle.score_trace["allocation"]
            assert allocation["objective"] == pytest.approx(sqrt(0.5) * 2)
            assert allocation["baseline_objective"] == 1
            assert allocation["search_complete"]
            assert cycle.score_trace["learning_snapshot"]["employer_skills"] == 0
        assert db.scalar(select(func.count()).select_from(Exposure)) == 2
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "decision.issued")
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.kind == "decision.issued")
            )
            == 2
        )
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0
        assert clearing.reconcile(db, market.actor(2), [role_x.id, role_y.id]) == []


@pytest.mark.parametrize("direction", ["CANDIDATE", "EMPLOYER"])
def test_reconcile_reserves_receiving_queue_across_batches_and_first_card_resolution(market, direction):
    with Session(market.engine) as db, db.begin():
        if direction == "CANDIDATE":
            candidates(db, 11)
            role_ids = [market.vacancy.id]
            scope = {"vacancy_id": market.vacancy.id}
            receiving_side = "EMPLOYER"
        else:
            role_ids = [market.vacancy.id, *(row.id for row in vacancies(db, market, 11))]
            db.add(MarketPrice(cell="ENGINEERING", candidate_price=0.1))
            scope = {"candidate_id": market.candidate.id}
            receiving_side = "CANDIDATE"
        db.flush()
        issued = clearing.reconcile(db, market.actor(2), role_ids)
        assert len(issued) == 10
        assert {row["side"] for row in issued} == {direction}
        assert clearing.waiting_count(db, receiving_side, **scope) == 0
        assert clearing.receiving_count(db, receiving_side, **scope) == 10
        assert clearing.reconcile(db, market.actor(2), role_ids) == []
        card = db.get(DecisionCard, issued[0]["decision_id"])
        candidate = db.get(Candidate, card.candidate_id)
        actor = Actor(candidate.user_id, utcnow(), ()) if direction == "CANDIDATE" else market.actor(1)
        response = clearing.answer(
            db,
            actor,
            card.id,
            False,
            SimpleNamespace(expected_cycle_version=1, decision_token=decrypt(card.token_cipher).decode()),
        )
        assert response["pair_state"].endswith("_PASS")
        assert clearing.receiving_count(db, receiving_side, **scope) == 9
        assert len(clearing.reconcile(db, market.actor(2), role_ids)) == 1
        assert clearing.receiving_count(db, receiving_side, **scope) == 10


def test_transaction_guard_rejects_eleventh_promise_even_without_planner(market):
    with Session(market.engine) as db, db.begin():
        pool = candidates(db, 11)
        for candidate in pool[:10]:
            clearing.issue_first(db, market.actor(2), candidate.id, market.vacancy.id, 1, "CANDIDATE")
        with pytest.raises(AppError) as error, db.begin_nested():
            clearing.issue_first(db, market.actor(2), pool[10].id, market.vacancy.id, 1, "CANDIDATE")
        assert error.value.code == "WAITING_FULL"
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 10
        assert clearing.receiving_count(db, "EMPLOYER", vacancy_id=market.vacancy.id) == 10


def test_concurrent_first_cards_cannot_overpromise_receiving_queue(market):
    with Session(market.engine, expire_on_commit=False) as db, db.begin():
        pool = candidates(db, 16)
        ids = [candidate.id for candidate in pool]

    def issue(candidate_id):
        with Session(market.engine) as db:
            try:
                with db.begin():
                    clearing.issue_first(db, market.actor(2), candidate_id, market.vacancy.id, 1, "CANDIDATE")
                return "OK"
            except AppError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=16) as workers:
        outcomes = list(workers.map(issue, ids))
    assert outcomes.count("OK") == 10
    assert outcomes.count("WAITING_FULL") == 6
    with Session(market.engine) as db:
        assert clearing.receiving_count(db, "EMPLOYER", vacancy_id=market.vacancy.id) == 10
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 10


def test_optimized_endpoint_preserves_idempotency_consent_and_rollback(market):
    assert market.call(0, "POST", "/internal/reconcile").status_code == 403
    first = market.call(2, "POST", "/internal/reconcile", key="optimized-reconcile-once")
    assert first.status_code == 200
    repeated = market.call(2, "POST", "/internal/reconcile", key="optimized-reconcile-once")
    assert repeated.status_code == 200
    assert first.json()["data"] == repeated.json()["data"]
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 1
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0
    with pytest.raises(RuntimeError), Session(market.engine) as db, db.begin():
        candidate = candidates(db, 1)[0]
        clearing.reconcile(db, market.actor(2), [market.vacancy.id])
        assert clearing.active_count(db, candidate_id=candidate.id) == 1
        raise RuntimeError("Fictional transaction abort")
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 1
        db.get(Candidate, market.candidate.id).terms_accepted = False
        clearing.close_cycle(db, market.actor(2), db.scalar(select(PairCycle)), "CLOSED_WITHDRAWN")
        assert clearing.reconcile(db, market.actor(2), [market.vacancy.id]) == []


@pytest.mark.parametrize(
    "incompatibility",
    [
        "work_mode",
        "employment_type",
        "currency",
        "compensation_period",
        "expired_availability",
        "start_window",
        "location",
        "blocked",
        "suspended",
        "role_conflict",
        "open_pair",
        "cooldown",
    ],
)
def test_structured_ineligible_older_profile_cannot_starve_later_profile(market, incompatibility):
    with Session(market.engine) as db, db.begin():
        older = db.get(Candidate, market.candidate.id)
        older.created_at = utcnow() - timedelta(days=2)
        later = candidates(db, 1)[0]
        vacancy = db.get(Vacancy, market.vacancy.id)
        if incompatibility == "work_mode":
            older.work_modes = ["ONSITE"]
        elif incompatibility == "employment_type":
            older.employment_types = ["PART_TIME"]
        elif incompatibility == "currency":
            older.currency = "EUR"
        elif incompatibility == "compensation_period":
            older.compensation_period = "HOURLY"
        elif incompatibility == "expired_availability":
            older.available_until = utcnow() - timedelta(days=1)
        elif incompatibility == "start_window":
            vacancy.start_until = utcnow() + timedelta(days=2)
            older.available_from = utcnow() + timedelta(days=3)
        elif incompatibility == "location":
            vacancy.work_mode = "ONSITE"
            vacancy.location_region = "Seattle"
            older.work_modes = ["ONSITE"]
            later.work_modes = ["ONSITE"]
            older.locations = ["Vancouver"]
        elif incompatibility == "blocked":
            db.add(CandidateBlock(candidate_id=older.id, org_id=vacancy.org_id))
        elif incompatibility == "suspended":
            db.get(User, older.user_id).status = "SUSPENDED"
        elif incompatibility == "role_conflict":
            db.add(OrgMember(user_id=older.user_id, org_id=vacancy.org_id, role="RECRUITER"))
        elif incompatibility in {"open_pair", "cooldown"}:
            db.add(
                PairCycle(
                    candidate_id=older.id,
                    vacancy_id=vacancy.id,
                    role_version=vacancy.version,
                    first_mover="CANDIDATE",
                    state="ELIGIBLE" if incompatibility == "open_pair" else "CLOSED_CANDIDATE_PASS",
                    closed_at=None if incompatibility == "open_pair" else utcnow() - timedelta(days=1),
                )
            )
        db.flush()
        issued = clearing.reconcile(db, market.actor(2), [vacancy.id], pool_limit=1)
        assert len(issued) == 1
        assert issued[0]["candidate_id"] == later.id


def test_expired_cooldown_and_membership_do_not_exclude_valid_older_profile(market):
    with Session(market.engine) as db, db.begin():
        older = db.get(Candidate, market.candidate.id)
        older.created_at = utcnow() - timedelta(days=2)
        candidates(db, 1)
        db.add(
            OrgMember(
                user_id=older.user_id,
                org_id=market.org.id,
                role="RECRUITER",
                expires_at=utcnow() - timedelta(days=1),
            )
        )
        db.add(
            PairCycle(
                candidate_id=older.id,
                vacancy_id=market.vacancy.id,
                role_version=1,
                cycle_number=1,
                first_mover="CANDIDATE",
                state="CLOSED_CANDIDATE_PASS",
                closed_at=utcnow() - timedelta(days=31),
            )
        )
        db.flush()
        issued = clearing.reconcile(db, market.actor(2), [market.vacancy.id], pool_limit=1)
        assert len(issued) == 1
        assert issued[0]["candidate_id"] == older.id
        assert db.scalar(select(func.max(PairCycle.cycle_number))) == 2
