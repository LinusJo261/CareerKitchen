"""Bound the relevant, consented pool rather than the oldest global profiles."""

from datetime import timedelta

from app.db.models import Candidate, PairCycle, User
from app.services import clearing
from app.services.common import utcnow
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_irrelevant_and_unconsented_profiles_cannot_hide_eligible_candidate(market):
    with Session(market.engine) as db, db.begin():
        now = utcnow()
        candidate = db.get(Candidate, market.candidate.id)
        candidate.created_at = now
        for index, (family, consent) in enumerate(
            [
                ("UNRELATED", True),
                ("ENGINEERING", False),
            ]
        ):
            user = User(issuer="fictional-retrieval", subject=str(index))
            db.add(user)
            db.flush()
            db.add(
                Candidate(
                    user_id=user.id,
                    headline="Fictional earlier profile",
                    state="ACTIVE",
                    role_families=[family],
                    work_modes=["REMOTE"],
                    employment_types=["FULL_TIME"],
                    terms_accepted=consent,
                    privacy_accepted=consent,
                    confirmed_at=now,
                    created_at=now - timedelta(days=1),
                )
            )
        db.flush()
        issued = clearing.reconcile(db, market.actor(2), [market.vacancy.id], pool_limit=1)
        assert len(issued) == 1
        assert issued[0]["candidate_id"] == market.candidate.id
        assert db.scalar(select(func.count()).select_from(PairCycle)) == 1
        trace = db.scalar(select(PairCycle)).score_trace
        assert trace["model_version"] == "reciprocal-compatibility-v1"
        assert trace["estimate_kind"] == "NONPROBABILISTIC"
