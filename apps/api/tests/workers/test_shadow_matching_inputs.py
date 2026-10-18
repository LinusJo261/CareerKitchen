"""PostgreSQL regressions for the authorized, read-only research input boundary.

All people, jobs, skills and market populations in this module are fictional.
"""

from datetime import timedelta
from math import sqrt
from uuid import UUID, uuid4

import pytest
from app.core.settings import get_settings
from app.db.models import (
    Candidate,
    CandidateSkill,
    CongestionPrice,
    MarketPrice,
    PairCycle,
    Requirement,
    Skill,
    User,
    Vacancy,
)
from app.db.pact_models import ExclusiveReservation
from app.services import clearing
from app.services.common import Actor, utcnow
from app.workers import runner
from sqlalchemy import select


def add_candidates(db, profiles):
    users = [
        User(id=str(uuid4()), issuer="test", subject=f"fictional-shadow-{uuid4().hex}") for _ in profiles
    ]
    db.add_all(users)
    db.flush()
    candidates = [
        Candidate(
            **{
                "id": str(uuid4()),
                "user_id": user.id,
                "headline": "Fictional shadow input test engineer",
                "state": "ACTIVE",
                "role_families": ["ENGINEERING"],
                "employment_types": ["FULL_TIME"],
                "work_modes": ["REMOTE"],
                "terms_accepted": True,
                "privacy_accepted": True,
                "confirmed_at": utcnow(),
                **profile,
            }
        )
        for user, profile in zip(users, profiles, strict=True)
    ]
    db.add_all(candidates)
    db.flush()
    return candidates


def add_jobs(db, source, identifiers):
    jobs = [
        Vacancy(
            id=identifier,
            org_id=source.org_id,
            owner_user_id=source.owner_user_id,
            title="Fictional shadow scope engineer",
            description="Fictional shadow scope responsibilities",
            role_family=source.role_family,
            employment_type=source.employment_type,
            work_mode=source.work_mode,
            pay_min=source.pay_min,
            pay_max=source.pay_max,
            currency=source.currency,
            state="ACTIVE",
            reviewed_by=source.owner_user_id,
            terms_hash=source.terms_hash,
        )
        for identifier in identifiers
    ]
    db.add_all(jobs)
    db.flush()
    return jobs


@pytest.mark.parametrize("preferences", [False, True], ids=["not-applicable", "curated-confirmed-alias"])
def test_shadow_and_live_share_confirmed_reciprocal_scoring_and_price_clamps(
    worker_market, monkeypatch, preferences
):
    m = worker_market
    monkeypatch.setattr(get_settings(), "congestion_price_max", 0.2)
    with m.factory.begin() as db:
        python = Skill(name="Python", aliases=["  Py  "])
        rust = Skill(name="Rust")
        db.add_all([python, rust])
        db.flush()
        db.add_all(
            [
                CandidateSkill(candidate_id=m.candidate_id, skill_id=python.id, confirmed=True),
                CandidateSkill(candidate_id=m.candidate_id, skill_id=rust.id, confirmed=False),
                MarketPrice(cell="ENGINEERING", candidate_price=0.05, employer_price=0.1),
                CongestionPrice(scope_id=m.candidate_id, side="CANDIDATE", price=50),
                CongestionPrice(scope_id=m.vacancy_id, side="EMPLOYER", price=50),
            ]
        )
        if preferences:
            db.add_all(
                [
                    Requirement(
                        vacancy_id=m.vacancy_id,
                        key=key,
                        description="Fictional optional skill",
                        kind="PREFERENCE",
                    )
                    for key in ("  pY ", " RUST  ")
                ]
            )
    with m.factory.begin() as db:
        snapshot = runner._shadow_snapshot(db, "fictional-scoring-parity")
        assert len(snapshot.edges) == 1
        edge = snapshot.edges[0]
        relevance = sqrt(0.75) if preferences else 1.0
        assert edge.routing_value == pytest.approx(relevance - 0.05 - 0.2)

        issued = clearing.reconcile(db, Actor(m.owner_id, utcnow()), vacancy_ids=[m.vacancy_id])
        assert len(issued) == 1
        pair = db.scalar(select(PairCycle))
        assert pair.score_trace["features"]["employer_skills"] == (0.5 if preferences else None)
        assert pair.score_trace["net_surplus"] == pytest.approx(edge.routing_value)
        assert pair.score_trace["prices"]["candidate_congestion"] == 0.2
        assert pair.score_trace["prices"]["job_congestion"] == 0.2


def test_one_snapshot_uses_one_feature_observation_time(worker_market, monkeypatch):
    m = worker_market
    with m.factory.begin() as db:
        add_candidates(db, [{}, {}])

    clock_start = utcnow()
    clock_ticks = []
    feature_times = []
    score = runner.score_reciprocal

    def advancing_clock():
        now = clock_start + timedelta(seconds=len(clock_ticks))
        clock_ticks.append(now)
        return now

    def observed_score(features, prices):
        feature_times.append(features.as_of)
        return score(features, prices)

    monkeypatch.setattr(runner, "utcnow", advancing_clock)
    monkeypatch.setattr(runner, "score_reciprocal", observed_score)
    with m.factory() as db:
        snapshot = runner._shadow_snapshot(db, "fictional-observation-time")
    assert len(snapshot.edges) == len(feature_times) == 3
    assert len(set(feature_times)) == 1


def test_unrelated_or_nonconsenting_profiles_cannot_exhaust_shadow_candidate_pool(worker_market):
    m = worker_market
    late_id = str(UUID(int=2**128 - 1))
    with m.factory.begin() as db:
        db.get(Candidate, m.candidate_id).state = "PAUSED"
        add_candidates(
            db,
            [{"id": str(UUID(int=i + 1)), "role_families": ["DESIGN"]} for i in range(110)]
            + [{"id": str(UUID(int=i + 111)), "terms_accepted": False} for i in range(110)]
            + [{"id": late_id}],
        )
    with m.factory() as db:
        snapshot = runner._shadow_snapshot(db, "fictional-role-consent-retrieval")
    assert {(edge.candidate_id, edge.vacancy_id) for edge in snapshot.edges} == {(late_id, m.vacancy_id)}


@pytest.mark.parametrize("outside_kind", ["ACTIVE_DECISION", "MUTUAL", "CONSENTED_EXCLUSIVE"])
def test_candidates_committed_outside_bounded_vacancy_scope_are_not_available(worker_market, outside_kind):
    m = worker_market
    with m.factory.begin() as db:
        original = db.get(Vacancy, m.vacancy_id)
        original.state = "PAUSED"
        selected = add_jobs(db, original, [str(UUID(int=i + 1)) for i in range(20)])
        outside = add_jobs(db, original, [str(UUID(int=2**128 - 1))])[0]
        available = add_candidates(db, [{}])[0]
        available_id = available.id
        if outside_kind == "CONSENTED_EXCLUSIVE":
            db.add(
                ExclusiveReservation(
                    candidate_id=m.candidate_id,
                    vacancy_id=outside.id,
                    role_version=outside.version,
                    terms_hash=outside.terms_hash,
                    consent_text_hash="fictional-consent",
                    expires_at=utcnow() + timedelta(days=1),
                )
            )
        else:
            mutual = outside_kind == "MUTUAL"
            db.add(
                PairCycle(
                    candidate_id=m.candidate_id,
                    vacancy_id=outside.id,
                    role_version=outside.version,
                    first_mover="CANDIDATE",
                    state="MUTUAL_MATCH" if mutual else "CANDIDATE_DECISION_REQUIRED",
                    candidate_interested_at=utcnow() if mutual else None,
                    employer_interested_at=utcnow() if mutual else None,
                )
            )
        selected_ids = {job.id for job in selected}
    with m.factory() as db:
        snapshot = runner._shadow_snapshot(db, "fictional-outside-commitment")
    assert {job.vacancy_id for job in snapshot.vacancies} == selected_ids
    assert {edge.candidate_id for edge in snapshot.edges} == {available_id}
    assert {edge.vacancy_id for edge in snapshot.edges} == selected_ids
    assert not snapshot.commitments  # Outside scopes cannot be misrepresented as selected jobs.


def test_recently_closed_pairs_stay_in_cooldown_and_open_pairs_stay_fixed(worker_market):
    m = worker_market
    with m.factory.begin() as db:
        old, active = add_candidates(db, [{}, {}])
        old_id, active_id = old.id, active.id
        db.add_all(
            [
                PairCycle(
                    candidate_id=candidate_id,
                    vacancy_id=m.vacancy_id,
                    role_version=1,
                    first_mover="CANDIDATE",
                    state="CLOSED_PASSED" if closed_at else "CANDIDATE_DECISION_REQUIRED",
                    closed_at=closed_at,
                )
                for candidate_id, closed_at in (
                    (m.candidate_id, utcnow() - timedelta(days=1)),
                    (old_id, utcnow() - timedelta(days=31)),
                    (active_id, None),
                )
            ]
        )
    with m.factory() as db:
        snapshot = runner._shadow_snapshot(db, "fictional-cooldown-fixed")
    assert old_id in {edge.candidate_id for edge in snapshot.edges}
    assert m.candidate_id not in {edge.candidate_id for edge in snapshot.edges}
    assert {(item.candidate_id, item.vacancy_id, item.kind) for item in snapshot.commitments} == {
        (active_id, m.vacancy_id, "ACTIVE_DECISION")
    }


def test_every_selected_vacancy_commitment_is_preserved_beyond_old_scan_limit(worker_market):
    m = worker_market
    with m.factory.begin() as db:
        # Profiles need not enter the eligible edge pool for existing commitments
        # to remain visible. This population exceeds the old 2,000-row truncation.
        candidates = add_candidates(db, [{"state": "PAUSED"} for _ in range(2001)])
        candidate_ids = {candidate.id for candidate in candidates}
        db.add_all(
            [
                PairCycle(
                    candidate_id=candidate.id,
                    vacancy_id=m.vacancy_id,
                    role_version=1,
                    first_mover="CANDIDATE",
                    state="CANDIDATE_DECISION_REQUIRED",
                )
                for candidate in candidates
            ]
        )
    with m.factory() as db:
        snapshot = runner._shadow_snapshot(db, "fictional-large-fixed-population")
    assert {item.candidate_id for item in snapshot.commitments} == candidate_ids
    assert len(snapshot.commitments) == 2001
