from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.db.models import (
    AuditEvent,
    Candidate,
    CongestionPrice,
    DecisionCard,
    Exposure,
    InboxConsumption,
    MarketPrice,
    Notification,
    NotificationPreference,
    OrgMember,
    OutboxEvent,
    PairCycle,
    ShadowRun,
    User,
    Vacancy,
    WaitingItem,
)
from app.services import clearing
from app.services.common import Actor, utcnow
from app.workers import runner
from sqlalchemy import delete, func, select


def issue(market, side="CANDIDATE"):
    with market.factory.begin() as db:
        card = clearing.issue_first(
            db, Actor(market.owner_id, utcnow()), market.candidate_id, market.vacancy_id, 1, side
        )
        return card.id


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_durable_notification_dedup_and_payload_cannot_choose_recipient(worker_market):
    m = worker_market
    issue(m)
    with m.factory.begin() as db:
        event = db.scalar(select(OutboxEvent))
        event.payload = {**event.payload, "user_id": m.outsider_id, "recipient_ids": [m.outsider_id]}
        event_id = event.id
    assert runner.process_one(m.factory, shadow=False) == (True, True)
    with m.factory.begin() as db:
        notification = db.scalar(select(Notification))
        assert notification.user_id == m.candidate_user_id
        assert notification.email_status == "NOT_CONFIGURED"
        event = db.get(OutboxEvent, event_id)
        event.dispatched_at = None  # at-least-once replay of the same durable event
    assert runner.process_one(m.factory, shadow=False) == (True, True)
    with m.factory() as db:
        assert count(db, Notification) == 1
        assert count(db, InboxConsumption) == 1
        worker = db.scalar(select(User).where(User.issuer == runner.WORKER_ISSUER))
        assert worker.platform_roles == ["SYSTEM_WORKER"]


@pytest.mark.parametrize("reason", ["passed", "role_changed", "revoked_member", "opt_out"])
def test_notifications_suppress_stale_or_unauthorized_and_opted_out(worker_market, reason):
    m = worker_market
    card_id = issue(m, "EMPLOYER" if reason == "revoked_member" else "CANDIDATE")
    with m.factory.begin() as db:
        card = db.get(DecisionCard, card_id)
        if reason == "passed":
            card.status = "PASSED"
        elif reason == "role_changed":
            db.get(Vacancy, m.vacancy_id).version += 1
        elif reason == "revoked_member":
            db.scalar(select(OrgMember)).status = "REVOKED"
        else:
            db.add(
                NotificationPreference(user_id=m.candidate_user_id, in_app_opt_in=False, email_opt_in=False)
            )
    assert runner.process_one(m.factory, shadow=False) == (True, True)
    with m.factory() as db:
        assert count(db, Notification) == 0


def test_failure_rolls_back_side_effects_retries_with_backoff_and_dead_letters(worker_market, monkeypatch):
    m = worker_market
    issue(m)

    def broken(db, actor, event):
        runner.enqueue_notifications(db, event)
        raise ValueError("private resume content must never appear in queue logs")

    monkeypatch.setattr(runner, "handle_event", broken)
    for attempt in range(1, runner.MAX_ATTEMPTS + 1):
        assert runner.process_one(m.factory, shadow=False) == (True, False)
        with m.factory.begin() as db:
            event = db.scalar(select(OutboxEvent))
            assert event.attempts == attempt
            assert event.last_error == "ValueError"
            assert count(db, Notification) == count(db, InboxConsumption) == 0
            if attempt < runner.MAX_ATTEMPTS:
                assert event.available_at > utcnow()
                event.available_at = utcnow() - timedelta(seconds=1)
            else:
                assert event.dead_letter_at is not None
                assert event.dispatched_at is None
    assert runner.process_one(m.factory, shadow=False) == (False, False)


def test_skip_locked_queue_does_not_serialize_all_workers(worker_market):
    m = worker_market
    with m.factory.begin() as db:
        runner.worker_actor(db)
        db.add_all([OutboxEvent(aggregate_id=m.candidate_id, kind="test.noop", payload={}) for _ in range(2)])
    with m.factory.begin() as locked:
        first = locked.scalar(
            select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id).with_for_update().limit(1)
        )
        assert runner.process_one(m.factory, shadow=False) == (True, True)
        assert first.dispatched_at is None
    with m.factory() as db:
        assert count(db, InboxConsumption) == 1
    assert runner.process_one(m.factory, shadow=False) == (True, True)


@pytest.mark.concurrency
def test_parallel_consumers_consume_each_event_exactly_once(worker_market):
    m = worker_market
    with m.factory.begin() as db:
        runner.worker_actor(db)
        db.add_all(
            [OutboxEvent(aggregate_id=m.candidate_id, kind="test.noop", payload={}) for _ in range(16)]
        )
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: runner.process_one(m.factory, shadow=False), range(16)))
    assert results.count((True, True)) == 16
    with m.factory() as db:
        assert count(db, InboxConsumption) == 16
        assert all(event.attempts == 1 and event.dispatched_at for event in db.scalars(select(OutboxEvent)))


def test_decision_issued_never_recursively_reconciles(worker_market, monkeypatch):
    m = worker_market
    issue(m)

    def unexpected(*args, **kwargs):
        raise AssertionError("decision.issued must not trigger clearing")

    monkeypatch.setattr(clearing, "reconcile", unexpected)
    assert runner.process_one(m.factory, shadow=False) == (True, True)


def test_periodic_expiry_runs_without_queued_events(worker_market):
    m = worker_market
    card_id = issue(m)
    with m.factory.begin() as db:
        db.execute(delete(OutboxEvent))
        db.get(DecisionCard, card_id).expires_at = utcnow() - timedelta(seconds=1)
    expired, released, reminders = runner.maintenance(m.factory)
    assert (expired, released, reminders) == (1, 0, 0)
    with m.factory() as db:
        card = db.get(DecisionCard, card_id)
        assert card.status == "EXPIRED"
        assert db.get(PairCycle, card.pair_cycle_id).state == "CLOSED_EXPIRED"
    assert runner.maintenance(m.factory) == (0, 0, 0)


def test_reminders_bounded_to_two_and_do_not_repeat_same_window(worker_market):
    m = worker_market
    card_id = issue(m)
    with m.factory.begin() as db:
        db.get(DecisionCard, card_id).expires_at = utcnow() + timedelta(hours=23)
    assert runner.maintenance(m.factory)[2] == 1
    assert runner.maintenance(m.factory)[2] == 0
    with m.factory.begin() as db:
        db.get(DecisionCard, card_id).expires_at = utcnow() + timedelta(hours=11)
    assert runner.maintenance(m.factory)[2] == 1
    assert runner.maintenance(m.factory)[2] == 0
    with m.factory() as db:
        assert db.get(DecisionCard, card_id).reminder_count == 2
        assert len(list(db.scalars(select(OutboxEvent).where(OutboxEvent.kind == "decision.expiring")))) == 2


@pytest.mark.parametrize("missing_consent", [None, "terms_accepted", "privacy_accepted", "confirmed_at"])
def test_expired_card_releases_existing_waiting_interest_without_revoking_commitments(
    worker_market, missing_consent
):
    m = worker_market
    card_id = issue(m, "EMPLOYER")
    with m.factory.begin() as db:
        db.get(Vacancy, m.vacancy_id).cap = 1
        db.get(DecisionCard, card_id).expires_at = utcnow() - timedelta(seconds=1)
        user = User(issuer="test", subject="second-candidate")
        db.add(user)
        db.flush()
        candidate = Candidate(
            user_id=user.id,
            headline="Fictional waiting engineer",
            state="ACTIVE",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
        )
        db.add(candidate)
        db.flush()
        pair = PairCycle(
            candidate_id=candidate.id,
            vacancy_id=m.vacancy_id,
            role_version=1,
            first_mover="CANDIDATE",
            state="WAITING_EMPLOYER_SLOT",
            candidate_interested_at=utcnow(),
        )
        db.add(pair)
        db.flush()
        db.add(WaitingItem(pair_cycle_id=pair.id, side="EMPLOYER", expires_at=utcnow() + timedelta(days=1)))
        pair_id = pair.id
        if missing_consent:
            # Consent may be withdrawn after the first decision, before release.
            setattr(candidate, missing_consent, None if missing_consent == "confirmed_at" else False)
    expected_releases = 0 if missing_consent else 1
    assert runner.maintenance(m.factory)[:2] == (1, expected_releases)
    with m.factory() as db:
        pair = db.get(PairCycle, pair_id)
        assert pair.state == ("CLOSED_EXPIRED" if missing_consent else "EMPLOYER_DECISION_REQUIRED")
        assert pair.candidate_interested_at is not None
        assert clearing.active_count(db, vacancy_id=m.vacancy_id) == expected_releases
        assert db.scalar(select(WaitingItem)).state == ("CLOSED" if missing_consent else "RELEASED")
        assert count(db, DecisionCard) == 1 + expected_releases
        assert count(db, Exposure) == 1 + expected_releases
    assert runner.maintenance(m.factory) == (0, 0, 0)


def test_shadow_after_commit_persists_diagnostics_without_changing_live_state(worker_market):
    m = worker_market
    issue(m)
    with m.factory.begin() as db:
        event = db.scalar(select(OutboxEvent))
        event_id = event.id
        baseline_counts = tuple(count(db, model) for model in (DecisionCard, PairCycle, Exposure, AuditEvent))
    runner.record_shadow(m.factory, event_id, [])
    runner.record_shadow(m.factory, event_id, [])
    with m.factory() as db:
        assert (
            tuple(count(db, model) for model in (DecisionCard, PairCycle, Exposure, AuditEvent))
            == baseline_counts
        )
        assert count(db, ShadowRun) == 1
        run = db.scalar(select(ShadowRun))
        assert run.side_effect_count == 0
        assert run.diagnostics["certification_state"] == "CANNOT_CERTIFY"
        assert run.diagnostics["model_coverage"] == 0


def test_shadow_failure_never_reverts_baseline_commit(worker_market, monkeypatch):
    m = worker_market
    card_id = issue(m)
    with m.factory() as db:
        event_id = db.scalar(select(OutboxEvent.id))

    def broken(*args, **kwargs):
        raise RuntimeError("research sidecar unavailable")

    monkeypatch.setattr(runner, "run_shadow", broken)
    runner.record_shadow(m.factory, event_id, [])
    with m.factory() as db:
        assert db.get(DecisionCard, card_id).status == "ACTIVE"
        assert count(db, ShadowRun) == 0


def test_worker_once_validates_batch_bound_and_safe_empty_queue(worker_market):
    m = worker_market
    with m.factory.begin() as db:
        db.get(Vacancy, m.vacancy_id).state = "PAUSED"
        db.get(Candidate, m.candidate_id).state = "PAUSED"
    assert runner.run_once(m.factory, batch_size=1) == runner.WorkerResult()
    with pytest.raises(ValueError):
        runner.run_once(m.factory, batch_size=1000)


def test_persisted_price_controller_uses_actual_cards_and_one_version_per_window(worker_market, monkeypatch):
    from math import sqrt

    from app.core.settings import get_settings

    m = worker_market
    monkeypatch.setattr(get_settings(), "market_price_window_seconds", 60)
    card_id = issue(m)
    start = utcnow() + timedelta(seconds=1)
    with m.factory.begin() as db:
        db.get(Candidate, m.candidate_id).cap = 1
        db.flush()
        actor = runner.worker_actor(db)
        assert runner.update_market_prices(db, actor, start) == 1
        price = db.scalar(select(MarketPrice))
        assert price.candidate_price == pytest.approx(1 / sqrt(2))
        assert price.candidate_h == 1
        assert price.employer_price == 0
        version = price.version
    with m.factory.begin() as db:
        actor = runner.worker_actor(db)
        assert runner.update_market_prices(db, actor, start + timedelta(seconds=30)) == 0
        assert db.scalar(select(MarketPrice)).version == version
        card = db.get(DecisionCard, card_id)
        card.status, card.answered_at = "PASSED", start + timedelta(seconds=40)
        db.flush()
        assert runner.update_market_prices(db, actor, start + timedelta(seconds=61)) == 1
        price = db.scalar(select(MarketPrice))
        assert 0 <= price.candidate_price < 1 / sqrt(2)
        assert price.version == version + 1
        db.flush()
        events = list(db.scalars(select(OutboxEvent).where(OutboxEvent.kind == "market.price_updated")))
        assert len(events) == 2
        assert events[-1].payload["statistics"]["CANDIDATE"]["completed"] == 1


def test_persisted_congestion_controller_prices_actual_waiting_and_respects_window(
    worker_market, monkeypatch
):
    from math import sqrt

    from app.core.settings import get_settings

    m = worker_market
    monkeypatch.setattr(get_settings(), "market_price_window_seconds", 60)
    card_id = issue(m, "EMPLOYER")
    now = utcnow() + timedelta(seconds=1)
    with m.factory.begin() as db:
        db.get(Vacancy, m.vacancy_id).cap = 1
        user = User(issuer="test", subject="congestion-second-candidate")
        db.add(user)
        db.flush()
        candidate = Candidate(
            user_id=user.id,
            headline="Fictional waiting engineer",
            state="ACTIVE",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
        )
        db.add(candidate)
        db.flush()
        pair = PairCycle(
            candidate_id=candidate.id,
            vacancy_id=m.vacancy_id,
            role_version=1,
            first_mover="CANDIDATE",
            state="WAITING_EMPLOYER_SLOT",
            candidate_interested_at=utcnow(),
        )
        db.add(pair)
        db.flush()
        db.add(WaitingItem(pair_cycle_id=pair.id, side="EMPLOYER", expires_at=utcnow() + timedelta(days=1)))
        db.flush()
        actor = runner.worker_actor(db)
        assert runner.update_congestion_prices(db, actor, now) == 3
        db.flush()
        price = db.scalar(select(CongestionPrice).where(CongestionPrice.scope_id == m.vacancy_id))
        assert price.price == pytest.approx(1 / sqrt(2)) and price.gradient_h == 1
        version = price.version
    with m.factory.begin() as db:
        actor = runner.worker_actor(db)
        assert runner.update_congestion_prices(db, actor, now + timedelta(seconds=30)) == 0
        db.scalar(select(WaitingItem)).state = "CLOSED"
        card = db.get(DecisionCard, card_id)
        card.status, card.answered_at = "PASSED", now + timedelta(seconds=40)
        db.flush()
        assert runner.update_congestion_prices(db, actor, now + timedelta(seconds=61)) == 3
        price = db.scalar(select(CongestionPrice).where(CongestionPrice.scope_id == m.vacancy_id))
        assert price.price < 1 / sqrt(2) and price.gradient_h == 2 and price.version == version + 1


@pytest.mark.parametrize("shadow_enabled", [True, False])
def test_queued_shortlist_research_request_runs_after_commit_without_live_clearing(
    worker_market, monkeypatch, shadow_enabled
):
    m = worker_market
    with m.factory.begin() as db:
        event = OutboxEvent(
            aggregate_id=m.vacancy_id,
            kind="shortlist.replan_requested",
            payload={"entity_id": m.vacancy_id, "entity_type": "vacancies", "version": 1},
        )
        db.add(event)
        db.flush()
        event_id = event.id
        before = tuple(count(db, model) for model in (DecisionCard, PairCycle, Exposure, AuditEvent))

    def no_live_clearing(*args, **kwargs):
        raise AssertionError("A research-only replan cannot run live clearing")

    monkeypatch.setattr(clearing, "reconcile", no_live_clearing)
    monkeypatch.setattr(clearing, "expire_due", no_live_clearing)
    monkeypatch.setattr(clearing, "release_waiting", no_live_clearing)
    record = runner.record_shadow
    observed = []

    def after_commit(factory, committed_event_id, issued):
        with factory() as db:
            assert db.get(OutboxEvent, committed_event_id).dispatched_at is not None
            assert db.get(InboxConsumption, (runner.CONSUMER, committed_event_id)) is not None
        assert issued == []
        observed.append(committed_event_id)
        record(factory, committed_event_id, issued)

    monkeypatch.setattr(runner, "record_shadow", after_commit)
    assert runner.process_one(m.factory, shadow=shadow_enabled) == (True, True)
    with m.factory() as db:
        assert tuple(count(db, model) for model in (DecisionCard, PairCycle, Exposure, AuditEvent)) == before
        assert count(db, Notification) == 0
        assert db.get(InboxConsumption, (runner.CONSUMER, event_id)) is not None
        assert count(db, ShadowRun) == int(shadow_enabled)
        if shadow_enabled:
            run = db.scalar(select(ShadowRun))
            assert run.event_id == event_id and run.side_effect_count == 0
            assert run.diagnostics["certification_state"] == "CANNOT_CERTIFY"
            assert observed == [event_id]
        else:
            assert observed == []
