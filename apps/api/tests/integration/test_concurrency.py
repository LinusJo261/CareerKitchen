"""Real PostgreSQL races. Each competitor owns a separate connection/transaction."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.errors import AppError
from app.core.security import decrypt
from app.db.models import Candidate, DecisionCard, MutualMatch, PairCycle, Requirement, User, Vacancy
from app.schemas.core import CandidateInput
from app.schemas.pact import ConsentEvidence, CreateClaim, Reserve, Revoke, VerifyClaim
from app.services import clearing, pact, profiles
from app.services.common import digest, utcnow
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]


def transaction(engine, callback):
    with Session(engine, expire_on_commit=False) as db:
        try:
            result = callback(db)
            db.commit()
            return "OK", result
        except AppError as exc:
            db.rollback()
            return exc.code, None


def race(engine, callbacks, workers=16):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda fn: transaction(engine, fn), callbacks))


def extra_vacancies(db, market, total):
    rows = [
        Vacancy(
            org_id=market.org.id,
            owner_user_id=market.users[1].id,
            title=f"Fictional concurrent role {i}",
            description="Fictional concurrency engineering role for tests only.",
            role_family="ENGINEERING",
            employment_type="FULL_TIME",
            work_mode="REMOTE",
            pay_min=80000,
            pay_max=120000,
            currency="USD",
            state="ACTIVE",
            cap=2,
            reviewed_by=market.users[1].id,
            terms_hash=digest(["concurrent-role", i]),
        )
        for i in range(total)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def extra_candidates(db, market, total):
    users = [
        User(
            issuer="fictional-concurrency",
            subject=str(uuid4()),
            verified_email=f"person-{uuid4()}@example.invalid",
        )
        for _ in range(total)
    ]
    db.add_all(users)
    db.flush()
    rows = [
        Candidate(
            user_id=user.id,
            headline="Fictional concurrent engineer",
            state="ACTIVE",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
        )
        for user in users
    ]
    db.add_all(rows)
    db.flush()
    return rows


def create_card(market, side="CANDIDATE"):
    def issue(db):
        card = clearing.issue_first(db, market.actor(2), market.candidate.id, market.vacancy.id, 1, side)
        return {"id": card.id, "token": decrypt(card.token_cipher).decode(), "cycle_id": card.pair_cycle_id}

    status, result = transaction(market.engine, issue)
    assert status == "OK"
    return result


def test_fifty_workers_race_for_last_candidate_slot(market, engine):
    with Session(engine, expire_on_commit=False) as db:
        db.get(Candidate, market.candidate.id).cap = 1
        roles = extra_vacancies(db, market, 50)
        db.commit()
    outcomes = race(
        engine,
        [
            lambda db, role=role: clearing.issue_first(
                db, market.actor(2), market.candidate.id, role.id, 1, "CANDIDATE"
            )
            for role in roles
        ],
        workers=50,
    )
    assert [state for state, _ in outcomes].count("OK") == 1
    assert [state for state, _ in outcomes].count("CAP_FULL") == 49
    with Session(engine) as db:
        assert clearing.active_count(db, candidate_id=market.candidate.id) == 1


def test_twenty_workers_respect_two_employer_slots(market, engine):
    with Session(engine, expire_on_commit=False) as db:
        candidates = extra_candidates(db, market, 20)
        db.commit()
    outcomes = race(
        engine,
        [
            lambda db, candidate=candidate: clearing.issue_first(
                db, market.actor(2), candidate.id, market.vacancy.id, 1, "EMPLOYER"
            )
            for candidate in candidates
        ],
        workers=20,
    )
    assert [state for state, _ in outcomes].count("OK") == 2
    assert [state for state, _ in outcomes].count("CAP_FULL") == 18
    with Session(engine) as db:
        assert clearing.active_count(db, vacancy_id=market.vacancy.id) == 2


def test_same_pair_concurrent_proposals_create_one_cycle(market, engine):
    outcomes = race(
        engine,
        [
            lambda db: clearing.issue_first(
                db, market.actor(2), market.candidate.id, market.vacancy.id, 1, "CANDIDATE"
            )
            for _ in range(32)
        ],
    )
    assert [state for state, _ in outcomes].count("OK") == 1
    assert [state for state, _ in outcomes].count("PAIR_EXISTS_OR_COOLDOWN") == 31
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(PairCycle)) == 1
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 1


def test_interested_pass_race_consumes_exactly_one_decision(market, engine):
    card = create_card(market)
    answer = SimpleNamespace(expected_cycle_version=1, decision_token=card["token"])
    outcomes = race(
        engine,
        [
            lambda db, interested=i % 2 == 0: clearing.answer(
                db, market.actor(0), card["id"], interested, answer
            )
            for i in range(32)
        ],
    )
    assert [state for state, _ in outcomes].count("OK") == 1
    assert all(state in {"OK", "VERSION_CONFLICT", "DECISION_RESOLVED"} for state, _ in outcomes)
    with Session(engine) as db:
        resolved = db.get(DecisionCard, card["id"])
        assert resolved.status in {"INTERESTED", "PASSED"}
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0
        assert (
            db.scalar(
                select(func.count()).select_from(DecisionCard).where(DecisionCard.status == "INTERESTED")
            )
            <= 1
        )


def test_concurrent_second_interests_create_one_mutual(market, engine):
    first = create_card(market)
    status, first_answer = transaction(
        engine,
        lambda db: clearing.answer(
            db,
            market.actor(0),
            first["id"],
            True,
            SimpleNamespace(expected_cycle_version=1, decision_token=first["token"]),
        ),
    )
    assert status == "OK"
    with Session(engine) as db:
        second = db.scalar(
            select(DecisionCard).where(
                DecisionCard.pair_cycle_id == first["cycle_id"], DecisionCard.side == "EMPLOYER"
            )
        )
        second_id, token = second.id, decrypt(second.token_cipher).decode()
    payload = SimpleNamespace(expected_cycle_version=first_answer["cycle_version"], decision_token=token)
    outcomes = race(
        engine, [lambda db: clearing.answer(db, market.actor(1), second_id, True, payload) for _ in range(32)]
    )
    assert [state for state, _ in outcomes].count("OK") == 1
    with Session(engine) as db:
        assert db.get(PairCycle, first["cycle_id"]).state == "MUTUAL_MATCH"
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(DecisionCard).where(DecisionCard.status == "INTERESTED")
            )
            == 2
        )


def test_expiration_racing_late_answer_never_creates_mutual(market, engine):
    card = create_card(market)
    with Session(engine) as db:
        db.get(DecisionCard, card["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    answer = SimpleNamespace(expected_cycle_version=1, decision_token=card["token"])
    callbacks = [
        (lambda db: clearing.answer(db, market.actor(0), card["id"], True, answer))
        if i % 2
        else (lambda db: clearing.expire_due(db, market.actor(2)))
        for i in range(16)
    ]
    outcomes = race(engine, callbacks)
    assert sum(value for state, value in outcomes if state == "OK") == 1
    with Session(engine) as db:
        assert db.get(DecisionCard, card["id"]).status == "EXPIRED"
        assert db.get(PairCycle, card["cycle_id"]).state == "CLOSED_EXPIRED"
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0
        assert clearing.active_count(db, candidate_id=market.candidate.id) == 0


def test_close_racing_second_interest_has_consistent_winner(market, engine):
    first = create_card(market)
    status, first_answer = transaction(
        engine,
        lambda db: clearing.answer(
            db,
            market.actor(0),
            first["id"],
            True,
            SimpleNamespace(expected_cycle_version=1, decision_token=first["token"]),
        ),
    )
    assert status == "OK"
    with Session(engine) as db:
        second = db.scalar(
            select(DecisionCard).where(
                DecisionCard.pair_cycle_id == first["cycle_id"], DecisionCard.side == "EMPLOYER"
            )
        )
        second_id, token = second.id, decrypt(second.token_cipher).decode()
    callbacks = [
        lambda db: profiles.set_vacancy_state(db, market.actor(1), market.vacancy.id, 1, "CLOSED"),
        lambda db: clearing.answer(
            db,
            market.actor(1),
            second_id,
            True,
            SimpleNamespace(expected_cycle_version=first_answer["cycle_version"], decision_token=token),
        ),
    ]
    outcomes = race(engine, callbacks, workers=2)
    assert outcomes[0][0] == "OK"
    with Session(engine) as db:
        assert db.get(Vacancy, market.vacancy.id).state == "CLOSED"
        assert clearing.active_count(db, vacancy_id=market.vacancy.id) == 0
        cycle = db.get(PairCycle, first["cycle_id"])
        mutual_count = db.scalar(select(func.count()).select_from(MutualMatch))
        if outcomes[1][0] == "OK":
            assert cycle.state == "MUTUAL_MATCH" and mutual_count == 1
            assert (
                db.scalar(
                    select(func.count()).select_from(DecisionCard).where(DecisionCard.status == "INTERESTED")
                )
                == 2
            )
        else:
            assert cycle.state == "CLOSED_JOB_CLOSED" and mutual_count == 0


def test_current_exclusive_reservation_blocks_other_role(market, engine):
    with Session(engine, expire_on_commit=False) as db:
        roles = extra_vacancies(db, market, 1)
        request = Reserve(
            vacancy_id=market.vacancy.id,
            expected_version=1,
            terms_hash=market.vacancy.terms_hash,
            candidate_expected_version=1,
            consent_text="I consent to this exact temporary exclusive reservation.",
            checkbox_confirmed=True,
            expires_at=utcnow() + timedelta(hours=1),
        )
        pact.reserve(db, market.actor(0), request)
        db.commit()
    result = transaction(
        engine,
        lambda db: clearing.issue_first(
            db, market.actor(2), market.candidate.id, roles[0].id, 1, "CANDIDATE"
        ),
    )
    assert result[0] == "PAIR_INELIGIBLE"
    current = transaction(
        engine,
        lambda db: clearing.issue_first(
            db, market.actor(2), market.candidate.id, market.vacancy.id, 1, "CANDIDATE"
        ),
    )
    assert current[0] == "OK"


def test_employer_card_never_exposes_private_floor_or_other_tenant(market):
    card = create_card(market, side="EMPLOYER")
    entitled = market.call(1, "GET", f"/decisions/{card['id']}")
    assert entitled.status_code == 200, entitled.text
    candidate = entitled.json()["data"]["candidate"]
    assert candidate["compensation_aligned"] is True
    assert not {
        "compensation_floor",
        "compensation_floor_cipher",
        "resume_object_ref",
        "verified_email",
        "private_object_ref",
    }.intersection(candidate)
    denied = market.call(3, "GET", f"/decisions/{card['id']}")
    assert denied.status_code == 403
    assert "70000" not in denied.text and market.candidate.headline not in denied.text


def test_evidence_revocation_prevents_second_side_disclosure(market, engine):
    with Session(engine, expire_on_commit=False) as db:
        vacancy = db.get(Vacancy, market.vacancy.id)
        db.add(
            Requirement(
                vacancy_id=vacancy.id,
                key="engineering_license",
                description="Engineering license",
                kind="ESSENTIAL",
                lawful_reason="Licensed practice requires this qualification",
                reviewed_by=market.users[1].id,
            )
        )
        profiles.refresh_terms(db, vacancy)
        claim = pact.create_claim(
            db,
            market.actor(0),
            CreateClaim(
                expected_version=1,
                claim_type="LICENSE",
                requirement_keys=["engineering_license"],
                statement="Fictional license issued to the candidate.",
                job_related_purpose="Fictional licensed engineering work.",
            ),
        )
        claim = pact.verify_claim(
            db,
            market.actor(2),
            claim["id"],
            VerifyClaim(
                expected_version=1,
                decision="VERIFIED",
                method="ISSUER_CONTACT",
                issuer="Fictional issuer",
                source_reference="Fictional independent issuer confirmation.",
                expires_at=utcnow() + timedelta(days=5),
                affirm_independent_check=True,
            ),
        )
        grant = pact.consent_evidence(
            db,
            market.actor(0),
            ConsentEvidence(
                vacancy_id=vacancy.id,
                expected_version=1,
                terms_hash=vacancy.terms_hash,
                claim_id=claim["id"],
                claim_expected_version=claim["version"],
                org_id=vacancy.org_id,
                kind="DISCLOSE_SUMMARY",
                consent_text="I consent to this exact role evidence summary.",
                expires_at=utcnow() + timedelta(days=2),
                checkbox_confirmed=True,
            ),
        )
        db.commit()
    card = create_card(market)
    result = transaction(
        engine, lambda db: pact.revoke_consent(db, market.actor(0), grant["id"], Revoke(expected_version=1))
    )
    assert result[0] == "OK"
    result = transaction(
        engine,
        lambda db: clearing.answer(
            db,
            market.actor(0),
            card["id"],
            True,
            SimpleNamespace(expected_cycle_version=1, decision_token=card["token"]),
        ),
    )
    assert result[0] == "PAIR_INELIGIBLE"
    with Session(engine) as db:
        assert (
            db.scalar(select(func.count()).select_from(DecisionCard).where(DecisionCard.side == "EMPLOYER"))
            == 0
        )
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0


def test_profile_save_rechecks_version_after_independent_commit(market, engine):
    with Session(engine) as stale:
        cached = stale.get(Candidate, market.candidate.id)
        assert cached.version == 1
        paused = transaction(engine, lambda db: profiles.candidate_state(db, market.actor(0), 1, "PAUSED"))
        assert paused[0] == "OK"
        payload = CandidateInput(
            expected_version=1,
            headline="Fictional updated engineer",
            region="Seattle",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            currency="USD",
            terms_accepted=True,
            privacy_accepted=True,
            profile_confirmed=True,
        )
        with pytest.raises(AppError) as failure:
            profiles.save_candidate(stale, market.actor(0), payload)
        assert failure.value.code == "VERSION_CONFLICT"
