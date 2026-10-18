"""Allocation begins after the transaction holding maintenance locks commits."""

from app.db.models import AuditEvent, DecisionCard, InboxConsumption, OutboxEvent
from app.workers import runner
from sqlalchemy import func, select


def test_maintenance_queues_one_durable_allocation_then_executes_without_maintenance(
    worker_market, monkeypatch
):
    market = worker_market
    with market.factory.begin() as db:
        source = OutboxEvent(
            aggregate_id=market.vacancy_id,
            kind="vacancy.activated",
            payload={"entity_type": "vacancies", "entity_id": market.vacancy_id},
        )
        db.add(source)
        db.flush()
        source_id = source.id

    reconcile = runner.clearing.reconcile

    def unexpected(*args, **kwargs):
        raise AssertionError("allocation must run in its own transaction")

    monkeypatch.setattr(runner.clearing, "reconcile", unexpected)
    assert runner.process_one(market.factory, shadow=False) == (True, True)
    with market.factory.begin() as db:
        queued = db.scalar(select(OutboxEvent).where(OutboxEvent.kind == runner.ALLOCATION_EVENT))
        assert queued.aggregate_id == source_id
        queued_id = queued.id
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 0
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == runner.ALLOCATION_EVENT))
        # At-least-once source delivery cannot enqueue another allocation.
        db.get(OutboxEvent, source_id).dispatched_at = None
    assert runner.process_one(market.factory, shadow=False) == (True, True)
    with market.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.kind == runner.ALLOCATION_EVENT)
            )
            == 1
        )

    monkeypatch.setattr(runner.clearing, "reconcile", reconcile)
    monkeypatch.setattr(runner.clearing, "expire_due", unexpected)
    monkeypatch.setattr(runner.clearing, "release_waiting", unexpected)
    monkeypatch.setattr(runner, "invalidate_pending", unexpected)
    assert runner.process_one(market.factory, shadow=False) == (True, True)
    with market.factory() as db:
        assert db.get(InboxConsumption, (runner.CONSUMER, queued_id)) is not None
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 1


def test_forged_allocation_source_is_retried_without_issuing_cards(worker_market):
    market = worker_market
    with market.factory.begin() as db:
        db.add(
            OutboxEvent(
                aggregate_id=market.vacancy_id,
                kind=runner.ALLOCATION_EVENT,
                payload={"entity_type": "vacancies", "entity_id": market.vacancy_id},
            )
        )
    assert runner.process_one(market.factory, shadow=False) == (True, False)
    with market.factory() as db:
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 0
