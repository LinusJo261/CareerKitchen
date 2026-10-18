"""The only live decision-card executor. Optimizers cannot bypass this module."""

from __future__ import annotations

import secrets
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from hmac import compare_digest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.core.settings import get_settings
from app.db.models import (
    Candidate,
    CandidateBlock,
    CandidateSkill,
    CongestionPrice,
    DecisionCard,
    Exposure,
    MarketPrice,
    MutualMatch,
    Organization,
    OrgMember,
    PairCycle,
    Requirement,
    Skill,
    User,
    Vacancy,
    WaitingItem,
)
from app.matching.attention import MarketPrices
from app.matching.baseline import HeuristicPairScorer
from app.matching.types import SanitizedPairFeatures
from app.services.common import (
    Actor,
    digest,
    emit,
    load,
    lock_scopes,
    require_vacancy,
    require_version,
    utcnow,
)

POST_MATCH = {"MUTUAL_MATCH", "INTERVIEWING", "OFFERED", "OFFER_ACCEPTED", "START_CONFIRMED"}


def feasible(db: Session, candidate: Candidate, vacancy: Vacancy) -> tuple[bool, list[str]]:
    from app.db.pact_models import ExclusiveReservation
    from app.services.pact import has_current_evidence

    reasons = []
    now = utcnow()
    if candidate.user_id == vacancy.owner_user_id or db.scalar(
        select(OrgMember.id).where(
            OrgMember.org_id == vacancy.org_id,
            OrgMember.user_id == candidate.user_id,
            OrgMember.status == "ACTIVE",
            (OrgMember.expires_at.is_(None) | (OrgMember.expires_at > now)),
        )
    ):
        reasons.append("PARTICIPANT_ROLE_CONFLICT")
    if db.scalar(
        select(ExclusiveReservation.id).where(
            ExclusiveReservation.candidate_id == candidate.id,
            ExclusiveReservation.vacancy_id != vacancy.id,
            ExclusiveReservation.status == "ACTIVE",
            ExclusiveReservation.expires_at > now,
        )
    ):
        reasons.append("EXCLUSIVELY_RESERVED_ELSEWHERE")
    if candidate.state != "ACTIVE" or vacancy.state != "ACTIVE":
        reasons.append("INACTIVE")
    if (
        load(db, User, candidate.user_id).status != "ACTIVE"
        or load(db, User, vacancy.owner_user_id).status != "ACTIVE"
        or load(db, Organization, vacancy.org_id).verification_state != "VERIFIED"
    ):
        reasons.append("UNVERIFIED_OR_RESTRICTED")
    if vacancy.openings_remaining <= 0 or (vacancy.deadline_at and vacancy.deadline_at <= now):
        reasons.append("VACANCY_UNAVAILABLE")
    if candidate.available_until and candidate.available_until <= now:
        reasons.append("CANDIDATE_UNAVAILABLE")
    if candidate.available_from and vacancy.start_until and candidate.available_from > vacancy.start_until:
        reasons.append("START_WINDOW")
    if candidate.available_until and vacancy.start_from and candidate.available_until < vacancy.start_from:
        reasons.append("START_WINDOW")
    if vacancy.currency != candidate.currency:
        reasons.append("CURRENCY_REQUIRES_REVIEW")
    if vacancy.compensation_period != candidate.compensation_period:
        reasons.append("COMPENSATION_PERIOD_REQUIRES_REVIEW")
    if (
        candidate.compensation_floor_cipher
        and Decimal(decrypt(candidate.compensation_floor_cipher).decode()) > vacancy.pay_max
    ):
        reasons.append("COMPENSATION")
    if vacancy.employment_type not in candidate.employment_types:
        reasons.append("EMPLOYMENT_TYPE")
    if vacancy.work_mode not in candidate.work_modes:
        reasons.append("WORK_MODE")
    if (
        vacancy.work_mode != "REMOTE"
        and candidate.locations
        and vacancy.location_region not in candidate.locations
    ):
        reasons.append("LOCATION")
    if vacancy.role_family not in candidate.role_families:
        reasons.append("ROLE_FAMILY")
    if db.scalar(
        select(CandidateBlock.id).where(
            CandidateBlock.candidate_id == candidate.id, CandidateBlock.org_id == vacancy.org_id
        )
    ):
        reasons.append("BLOCKED")
    for requirement in db.scalars(select(Requirement).where(Requirement.vacancy_id == vacancy.id)):
        if requirement.kind == "AMBIGUOUS":
            reasons.append("NEEDS_HUMAN_CLARIFICATION")
        if requirement.kind == "ESSENTIAL" and (
            not requirement.reviewed_by
            or not has_current_evidence(db, candidate.id, vacancy, requirement.key)
        ):
            reasons.append("ESSENTIAL_EVIDENCE_REQUIRED")
    return not reasons, sorted(set(reasons))


def active_count(db: Session, candidate_id: str | None = None, vacancy_id: str | None = None) -> int:
    query = select(func.count()).select_from(DecisionCard).where(DecisionCard.status == "ACTIVE")
    query = (
        query.where(DecisionCard.candidate_id == candidate_id, DecisionCard.side == "CANDIDATE")
        if candidate_id
        else query.where(DecisionCard.vacancy_id == vacancy_id, DecisionCard.side == "EMPLOYER")
    )
    return db.scalar(query) or 0


def waiting_count(
    db: Session, side: str, candidate_id: str | None = None, vacancy_id: str | None = None
) -> int:
    query = (
        select(func.count())
        .select_from(WaitingItem)
        .join(PairCycle, PairCycle.id == WaitingItem.pair_cycle_id)
        .where(WaitingItem.state == "WAITING", WaitingItem.side == side)
    )
    query = (
        query.where(PairCycle.candidate_id == candidate_id)
        if candidate_id
        else query.where(PairCycle.vacancy_id == vacancy_id)
    )
    return db.scalar(query) or 0


def _has_capacity(db: Session, candidate: Candidate, vacancy: Vacancy, side: str) -> bool:
    return (
        active_count(db, candidate_id=candidate.id) < min(10, candidate.cap)
        if side == "CANDIDATE"
        else active_count(db, vacancy_id=vacancy.id) < min(10, vacancy.cap)
    )


def _issue(
    db: Session, actor: Actor, cycle: PairCycle, candidate: Candidate, vacancy: Vacancy, side: str
) -> DecisionCard:
    if not _has_capacity(db, candidate, vacancy, side):
        raise AppError(409, "CAP_FULL", "Decision capacity is full")
    token = secrets.token_urlsafe(32)
    card = DecisionCard(
        pair_cycle_id=cycle.id,
        candidate_id=candidate.id,
        vacancy_id=vacancy.id,
        side=side,
        recipient_user_id=candidate.user_id if side == "CANDIDATE" else vacancy.owner_user_id,
        token_hash=digest(token),
        token_cipher=encrypt(token),
        expires_at=utcnow() + timedelta(hours=get_settings().decision_ttl_hours),
    )
    db.add(card)
    db.flush()
    cycle.state = f"{side}_DECISION_REQUIRED"
    db.add(
        Exposure(
            decision_card_id=card.id,
            pair_cycle_id=cycle.id,
            candidate_id=candidate.id,
            vacancy_id=vacancy.id,
            recipient_side=side,
            snapshot_hash=digest(
                [candidate.id, candidate.version, vacancy.id, vacancy.version, cycle.score_trace]
            ),
            model_version=cycle.model_version,
            score_trace=cycle.score_trace,
        )
    )
    emit(db, actor, "decision.issued", card, org_id=vacancy.org_id)
    return card


def issue_first(
    db: Session,
    actor: Actor,
    candidate_id: str,
    vacancy_id: str,
    role_version: int,
    first_mover: str,
    score_trace: dict | None = None,
) -> DecisionCard:
    lock_scopes(db, f"candidate:{candidate_id}", f"vacancy:{vacancy_id}")
    candidate = load(db, Candidate, candidate_id)
    vacancy = load(db, Vacancy, vacancy_id)
    require_version(vacancy, role_version)
    valid, reasons = feasible(db, candidate, vacancy)
    if not valid:
        raise AppError(409, "PAIR_INELIGIBLE", "Pair is not currently eligible: " + ",".join(reasons))
    old = db.scalar(
        select(PairCycle)
        .where(PairCycle.candidate_id == candidate.id, PairCycle.vacancy_id == vacancy.id)
        .order_by(PairCycle.cycle_number.desc())
        .limit(1)
    )
    if old and (old.closed_at is None or old.closed_at > utcnow() - timedelta(days=30)):
        raise AppError(
            409, "PAIR_EXISTS_OR_COOLDOWN", "This pair already has a cycle or is in its cooldown period"
        )
    if first_mover not in {"CANDIDATE", "EMPLOYER"}:
        raise AppError(422, "INVALID_SIDE", "Invalid decision side")
    # Bound the receiving waiting queue before creating additional first-side work.
    other = "EMPLOYER" if first_mover == "CANDIDATE" else "CANDIDATE"
    if (
        waiting_count(
            db,
            other,
            **({"candidate_id": candidate.id} if other == "CANDIDATE" else {"vacancy_id": vacancy.id}),
        )
        >= 10
    ):
        raise AppError(409, "WAITING_FULL", "The receiving attention queue is full")
    if not _has_capacity(db, candidate, vacancy, first_mover):
        raise AppError(409, "CAP_FULL", "Decision capacity is full")
    cycle = PairCycle(
        candidate_id=candidate.id,
        vacancy_id=vacancy.id,
        role_version=vacancy.version,
        cycle_number=old.cycle_number + 1 if old else 1,
        first_mover=first_mover,
        state="ELIGIBLE",
        model_version=(score_trace or {}).get("model_version", "manual-reviewed-v1"),
        score_trace=score_trace or {},
    )
    db.add(cycle)
    db.flush()
    return _issue(db, actor, cycle, candidate, vacancy, first_mover)


def authorize_card(db: Session, actor: Actor, card: DecisionCard) -> PairCycle:
    cycle = load(db, PairCycle, card.pair_cycle_id)
    if card.side == "CANDIDATE":
        if load(db, Candidate, cycle.candidate_id).user_id != actor.user_id:
            raise AppError(403, "FORBIDDEN", "This decision belongs to another participant")
    else:
        require_vacancy(db, actor, cycle.vacancy_id)
    return cycle


def card_out(db: Session, actor: Actor, card: DecisionCard) -> dict:
    from app.services.profiles import vacancy_out

    cycle = authorize_card(db, actor, card)
    vacancy = load(db, Vacancy, cycle.vacancy_id)
    result = {
        "id": card.id,
        "version": card.version,
        "pair_cycle_id": cycle.id,
        "cycle_version": cycle.version,
        "pair_state": cycle.state,
        "side": card.side,
        "status": card.status,
        "expires_at": card.expires_at,
        "decision_token": decrypt(card.token_cipher).decode() if card.status == "ACTIVE" else None,
        "vacancy": vacancy_out(db, vacancy),
        "reason_codes": cycle.score_trace.get("reason_codes", []),
        "other_side_interested": bool(
            cycle.employer_interested_at if card.side == "CANDIDATE" else cycle.candidate_interested_at
        ),
    }
    if card.side == "EMPLOYER":
        candidate = load(db, Candidate, cycle.candidate_id)
        # Only selected profile fields, never resume, private compensation or contact.
        result["candidate"] = {
            "id": candidate.id,
            "headline": candidate.headline,
            "summary": candidate.summary,
            "region": candidate.region,
            "compensation_aligned": feasible(db, candidate, vacancy)[0],
            "skills": [
                name
                for name in db.scalars(
                    select(Skill.name)
                    .join(CandidateSkill, CandidateSkill.skill_id == Skill.id)
                    .where(CandidateSkill.candidate_id == candidate.id)
                )
            ],
            "experiences": [
                {
                    key: value
                    for key, value in experience.items()
                    if key != "organization_label" or experience.get("disclose_organization")
                }
                for experience in candidate.experiences
            ],
        }
    return result


def close_cycle(db: Session, actor: Actor, cycle: PairCycle, state: str) -> None:
    if cycle.closed_at:
        return
    cycle.state, cycle.closed_at = state, utcnow()
    cycle.version += 1
    db.flush()
    for card in db.scalars(
        select(DecisionCard).where(DecisionCard.pair_cycle_id == cycle.id, DecisionCard.status == "ACTIVE")
    ):
        card.status, card.version = "CANCELLED", card.version + 1
    item = db.scalar(select(WaitingItem).where(WaitingItem.pair_cycle_id == cycle.id))
    if item:
        item.state = "CLOSED"
    match = db.scalar(select(MutualMatch).where(MutualMatch.pair_cycle_id == cycle.id))
    if match:
        match.status, match.version = "CLOSED", match.version + 1
    emit(db, actor, "pair.closed", cycle)


def cancel_candidate_pending(db: Session, actor: Actor, candidate_id: str, reason: str) -> None:
    for cycle in db.scalars(
        select(PairCycle).where(
            PairCycle.candidate_id == candidate_id,
            PairCycle.closed_at.is_(None),
            PairCycle.state.not_in(POST_MATCH),
        )
    ):
        close_cycle(db, actor, cycle, "CLOSED_WITHDRAWN")


def cancel_vacancy_pending(db: Session, actor: Actor, vacancy_id: str, reason: str) -> None:
    for cycle in db.scalars(
        select(PairCycle).where(
            PairCycle.vacancy_id == vacancy_id,
            PairCycle.closed_at.is_(None),
            PairCycle.state.not_in(POST_MATCH),
        )
    ):
        close_cycle(db, actor, cycle, "CLOSED_JOB_CLOSED")


def answer(db: Session, actor: Actor, decision_id: str, interested: bool, data) -> dict:
    card = load(db, DecisionCard, decision_id)
    cycle = authorize_card(db, actor, card)
    lock_scopes(db, f"candidate:{cycle.candidate_id}", f"vacancy:{cycle.vacancy_id}")
    card, cycle = load(db, DecisionCard, card.id), load(db, PairCycle, cycle.id)
    authorize_card(db, actor, card)
    require_version(cycle, data.expected_cycle_version)
    if card.status != "ACTIVE" or cycle.closed_at:
        raise AppError(409, "DECISION_RESOLVED", "This decision has already been resolved")
    if card.expires_at <= utcnow():
        raise AppError(409, "EXPIRED_DECISION", "This decision has expired")
    if not compare_digest(card.token_hash, digest(data.decision_token)):
        raise AppError(403, "INVALID_DECISION_TOKEN", "Invalid decision token")
    candidate, vacancy = load(db, Candidate, cycle.candidate_id), load(db, Vacancy, cycle.vacancy_id)
    if vacancy.version != cycle.role_version:
        raise AppError(409, "STALE_ROLE", "Role terms changed; a new introduction is required")
    if not feasible(db, candidate, vacancy)[0]:
        raise AppError(409, "PAIR_INELIGIBLE", "Pair is no longer eligible")
    card.status, card.answered_at, card.version = (
        "INTERESTED" if interested else "PASSED",
        utcnow(),
        card.version + 1,
    )
    match_id = None
    if not interested:
        close_cycle(db, actor, cycle, f"CLOSED_{card.side}_PASS")
    else:
        setattr(
            cycle,
            "candidate_interested_at" if card.side == "CANDIDATE" else "employer_interested_at",
            utcnow(),
        )
        cycle.version += 1
        if cycle.candidate_interested_at and cycle.employer_interested_at:
            # Both timestamps must also have actual persisted Interested cards.
            db.flush()
            count = db.scalar(
                select(func.count())
                .select_from(DecisionCard)
                .where(DecisionCard.pair_cycle_id == cycle.id, DecisionCard.status == "INTERESTED")
            )
            if count != 2:
                raise AppError(409, "DOUBLE_OPT_IN_REQUIRED", "Two independent interests are required")
            cycle.state = "MUTUAL_MATCH"
            match = MutualMatch(pair_cycle_id=cycle.id)
            db.add(match)
            emit(db, actor, "pair.mutual", match, org_id=vacancy.org_id)
            match_id = match.id
        else:
            other = "EMPLOYER" if card.side == "CANDIDATE" else "CANDIDATE"
            db.flush()  # First card must stop counting before checking the second cap.
            if _has_capacity(db, candidate, vacancy, other):
                _issue(db, actor, cycle, candidate, vacancy, other)
            else:
                if (
                    waiting_count(
                        db,
                        other,
                        **(
                            {"candidate_id": candidate.id}
                            if other == "CANDIDATE"
                            else {"vacancy_id": vacancy.id}
                        ),
                    )
                    >= 10
                ):
                    raise AppError(
                        409, "WAITING_FULL", "Receiving queue is full; retry once capacity is available"
                    )
                cycle.state = f"WAITING_{other}_SLOT"
                db.add(
                    WaitingItem(
                        pair_cycle_id=cycle.id,
                        side=other,
                        expires_at=utcnow() + timedelta(hours=get_settings().decision_ttl_hours),
                    )
                )
                emit(db, actor, "pair.waiting", cycle)
    emit(db, actor, "decision.interested" if interested else "decision.passed", card, org_id=vacancy.org_id)
    return {
        "pair_cycle_id": cycle.id,
        "pair_state": cycle.state,
        "card_status": card.status,
        "cycle_version": cycle.version,
        "match_id": match_id,
        "next_action": "OPEN_MATCH" if match_id else "WAITING" if interested else "NONE",
    }


def expire_due(db: Session, actor: Actor) -> int:
    count = 0
    ids = list(
        db.scalars(
            select(DecisionCard.id)
            .where(DecisionCard.status == "ACTIVE", DecisionCard.expires_at <= utcnow())
            .limit(200)
        )
    )
    for card_id in ids:
        card = load(db, DecisionCard, card_id)
        lock_scopes(db, f"candidate:{card.candidate_id}", f"vacancy:{card.vacancy_id}")
        card = load(db, DecisionCard, card_id)
        if card.status == "ACTIVE" and card.expires_at <= utcnow():
            card.status, card.version = "EXPIRED", card.version + 1
            close_cycle(db, actor, load(db, PairCycle, card.pair_cycle_id), "CLOSED_EXPIRED")
            emit(db, actor, "decision.expired", card)
            count += 1
    for item in db.scalars(
        select(WaitingItem)
        .where(WaitingItem.state == "WAITING", WaitingItem.expires_at <= utcnow())
        .limit(200)
    ):
        cycle = load(db, PairCycle, item.pair_cycle_id)
        lock_scopes(db, f"candidate:{cycle.candidate_id}", f"vacancy:{cycle.vacancy_id}")
        item, cycle = load(db, WaitingItem, item.id), load(db, PairCycle, cycle.id)
        if item.state == "WAITING" and item.expires_at <= utcnow() and not cycle.closed_at:
            close_cycle(db, actor, cycle, "CLOSED_EXPIRED")
    return count


def release_waiting(db: Session, actor: Actor) -> int:
    released = 0
    for item in db.scalars(
        select(WaitingItem)
        .where(WaitingItem.state == "WAITING", WaitingItem.expires_at > utcnow())
        .order_by(WaitingItem.created_at, WaitingItem.id)
        .limit(200)
    ):
        cycle = load(db, PairCycle, item.pair_cycle_id)
        lock_scopes(db, f"candidate:{cycle.candidate_id}", f"vacancy:{cycle.vacancy_id}")
        item, cycle = load(db, WaitingItem, item.id), load(db, PairCycle, cycle.id)
        if item.state != "WAITING" or cycle.closed_at:
            continue
        if item.expires_at <= utcnow():
            close_cycle(db, actor, cycle, "CLOSED_EXPIRED")
            continue
        candidate, vacancy = load(db, Candidate, cycle.candidate_id), load(db, Vacancy, cycle.vacancy_id)
        if vacancy.version != cycle.role_version or not feasible(db, candidate, vacancy)[0]:
            close_cycle(db, actor, cycle, "CLOSED_EXPIRED")
        elif _has_capacity(db, candidate, vacancy, item.side):
            cycle.version += 1
            _issue(db, actor, cycle, candidate, vacancy, item.side)
            item.state = "RELEASED"
            released += 1
    return released


def reconcile(
    db: Session, actor: Actor, vacancy_ids: list[str] | None = None, pool_limit: int = 200
) -> list[dict]:
    """Bounded indexed retrieval; no dense candidate-by-job matrix or public search."""
    proposals = []
    query = select(Vacancy).where(Vacancy.state == "ACTIVE").order_by(Vacancy.id).limit(50)
    if vacancy_ids:
        query = query.where(Vacancy.id.in_(vacancy_ids))
    for vacancy in db.scalars(query):
        price = db.scalar(select(MarketPrice).where(MarketPrice.cell == vacancy.role_family))
        job_congestion = db.scalar(
            select(CongestionPrice).where(
                CongestionPrice.scope_id == vacancy.id, CongestionPrice.side == "EMPLOYER"
            )
        )
        prices = MarketPrices(
            mu_candidate=price.candidate_price if price else 0,
            mu_employer=price.employer_price if price else 0,
            job_congestion=min(
                get_settings().congestion_price_max, job_congestion.price if job_congestion else 0
            ),
        )
        candidates = db.scalars(
            select(Candidate)
            .where(Candidate.state == "ACTIVE")
            .order_by(Candidate.created_at, Candidate.id)
            .limit(pool_limit)
        )
        for candidate in candidates:
            if vacancy.role_family not in candidate.role_families or not feasible(db, candidate, vacancy)[0]:
                continue
            existing = db.scalar(
                select(PairCycle.id).where(
                    PairCycle.candidate_id == candidate.id,
                    PairCycle.vacancy_id == vacancy.id,
                    (PairCycle.closed_at.is_(None) | (PairCycle.closed_at > utcnow() - timedelta(days=30))),
                )
            )
            if existing:
                continue
            skills = set(
                db.scalars(
                    select(Skill.name)
                    .join(CandidateSkill, CandidateSkill.skill_id == Skill.id)
                    .where(CandidateSkill.candidate_id == candidate.id)
                )
            )
            preferred = set(
                db.scalars(
                    select(Requirement.key).where(
                        Requirement.vacancy_id == vacancy.id, Requirement.kind == "PREFERENCE"
                    )
                )
            )
            features = SanitizedPairFeatures(
                candidate.id,
                vacancy.id,
                vacancy.role_family,
                "structured-v1",
                utcnow(),
                skill_alignment=len(skills.intersection(preferred)) / len(preferred) if preferred else 0,
                work_mode_alignment=1,
            )
            candidate_congestion = db.scalar(
                select(CongestionPrice).where(
                    CongestionPrice.scope_id == candidate.id, CongestionPrice.side == "CANDIDATE"
                )
            )
            pair_prices = MarketPrices(
                mu_candidate=prices.mu_candidate,
                mu_employer=prices.mu_employer,
                job_congestion=prices.job_congestion,
                candidate_congestion=min(
                    get_settings().congestion_price_max,
                    candidate_congestion.price if candidate_congestion else 0,
                ),
            )
            score = HeuristicPairScorer().score(features, pair_prices)
            if score.best.net_surplus <= 0:
                continue
            trace = {
                "model_version": score.model_version,
                "estimate_kind": "NONPROBABILISTIC",
                "feature_hash": features.digest,
                "reason_codes": list(score.factors),
                "candidate_first": asdict(score.candidate_first),
                "employer_first": asdict(score.employer_first),
                "prices": asdict(pair_prices),
            }
            proposals.append(
                (
                    score.best.net_surplus,
                    candidate.id,
                    vacancy.id,
                    vacancy.version,
                    score.best.side.value,
                    trace,
                )
            )
    issued = []
    for _, candidate_id, vacancy_id, version, side, trace in sorted(
        proposals, key=lambda p: (-p[0], p[1], p[2])
    ):
        try:
            # Conflicts roll back only this proposed introduction, not prior valid work.
            with db.begin_nested():
                card = issue_first(db, actor, candidate_id, vacancy_id, version, side, trace)
                issued.append(
                    {
                        "decision_id": card.id,
                        "candidate_id": candidate_id,
                        "vacancy_id": vacancy_id,
                        "side": side,
                    }
                )
        except AppError as exc:
            if exc.code not in {
                "CAP_FULL",
                "PAIR_EXISTS_OR_COOLDOWN",
                "WAITING_FULL",
                "PAIR_INELIGIBLE",
                "VERSION_CONFLICT",
            }:
                raise
    return issued
