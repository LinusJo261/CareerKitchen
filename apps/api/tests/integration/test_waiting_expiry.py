"""Waiting queues must be revalidated after acquiring authoritative locks."""

from datetime import timedelta

from app.db.models import Candidate, DecisionCard, PairCycle, Vacancy, WaitingItem
from app.services import clearing
from app.services.common import utcnow
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def waiting_cycle(market, *, expired):
    with Session(market.engine) as db:
        cycle = PairCycle(
            candidate_id=market.candidate.id,
            vacancy_id=market.vacancy.id,
            role_version=market.vacancy.version,
            first_mover="CANDIDATE",
            state="WAITING_EMPLOYER_SLOT",
            candidate_interested_at=utcnow(),
        )
        db.add(cycle)
        db.flush()
        item = WaitingItem(
            pair_cycle_id=cycle.id,
            side="EMPLOYER",
            expires_at=utcnow() + timedelta(hours=-1 if expired else 1),
        )
        db.add(item)
        db.flush()
        cycle_id, item_id = cycle.id, item.id
        db.commit()
    return cycle_id, item_id


def test_queue_expiring_while_acquiring_lock_cannot_issue_a_card(market, monkeypatch):
    cycle_id, item_id = waiting_cycle(market, expired=False)
    original_lock = clearing.lock_scopes

    def expire_then_lock(db, *keys):
        with Session(market.engine) as other:
            other.get(WaitingItem, item_id).expires_at = utcnow() - timedelta(seconds=1)
            other.commit()
        original_lock(db, *keys)

    monkeypatch.setattr(clearing, "lock_scopes", expire_then_lock)
    with Session(market.engine) as db:
        assert clearing.release_waiting(db, market.actor(2)) == 0
        db.commit()
        assert db.get(PairCycle, cycle_id).state == "CLOSED_EXPIRED"
        assert db.get(WaitingItem, item_id).state == "CLOSED"
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 0


def test_expiry_scan_does_not_close_a_queue_released_before_its_lock(market, monkeypatch):
    cycle_id, item_id = waiting_cycle(market, expired=True)
    original_lock = clearing.lock_scopes

    def release_then_lock(db, *keys):
        with Session(market.engine) as other:
            original_lock(other, *keys)
            cycle = other.get(PairCycle, cycle_id)
            cycle.version += 1
            clearing._issue(
                other,
                market.actor(2),
                cycle,
                other.get(Candidate, market.candidate.id),
                other.get(Vacancy, market.vacancy.id),
                "EMPLOYER",
            )
            other.get(WaitingItem, item_id).state = "RELEASED"
            other.commit()
        original_lock(db, *keys)

    monkeypatch.setattr(clearing, "lock_scopes", release_then_lock)
    with Session(market.engine) as db:
        assert clearing.expire_due(db, market.actor(2)) == 0
        db.commit()
        cycle = db.get(PairCycle, cycle_id)
        assert cycle.state == "EMPLOYER_DECISION_REQUIRED" and cycle.closed_at is None
        assert db.get(WaitingItem, item_id).state == "RELEASED"
        assert db.scalar(select(DecisionCard.status)) == "ACTIVE"
