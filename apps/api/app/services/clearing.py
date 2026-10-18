"""The only live decision-card executor. Optimizers cannot bypass this module."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from hmac import compare_digest

from sqlalchemy import and_, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
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
from app.matching.learning import apply_learned_score
from app.matching.live import AttentionCapacity, LiveProposal, allocate_live
from app.matching.reciprocal import ReciprocalFeatures, score_reciprocal, skill_coverage, skill_overlap
from app.matching.text_alignment import professional_text_alignment
from app.matching.types import Side
from app.services import matching_learning
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


def compatibility_features(
    candidate: Candidate,
    vacancy: Vacancy,
    confirmed_skills: tuple[tuple[str, tuple[str, ...]], ...],
    preferred: tuple[str, ...],
    as_of: datetime,
    *,
    text_learning_enabled: bool = False,
) -> ReciprocalFeatures:
    """Shared live/shadow feature contract for an already eligibility-checked pair.

    Missing experience/evidence targets stay unknown. Only confirmed taxonomy
    skills and stated preferences enter deterministic compatibility. Consented
    self-declared text alignment is an additional frozen learning input, never
    a verified credential or an eligibility gate.
    """
    precision, jaccard = skill_overlap(confirmed_skills, preferred)
    if type(text_learning_enabled) is not bool:
        raise ValueError("Text learning capture requires an explicit consent boolean")
    text_value, extractor_id = (
        professional_text_alignment(
            candidate.headline, candidate.summary or "", vacancy.title, vacancy.description
        )
        if text_learning_enabled
        else (None, None)
    )
    return ReciprocalFeatures(
        candidate_id=candidate.id,
        vacancy_id=vacancy.id,
        candidate_version=candidate.version,
        vacancy_version=vacancy.version,
        as_of=as_of.isoformat(),
        employer_skills=skill_coverage(confirmed_skills, preferred),
        candidate_role=float(vacancy.role_family in candidate.role_families),
        candidate_work_mode=float(vacancy.work_mode in candidate.work_modes),
        candidate_employment_type=float(vacancy.employment_type in candidate.employment_types),
        eligible=True,
        skill_precision=precision,
        skill_jaccard=jaccard,
        text_relevance=text_value,
        text_relevance_model_id=extractor_id,
    )


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
    if not candidate.terms_accepted or not candidate.privacy_accepted or not candidate.confirmed_at:
        reasons.append("CANDIDATE_CONSENT_REQUIRED")
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


def receiving_count(
    db: Session, side: str, candidate_id: str | None = None, vacancy_id: str | None = None
) -> int:
    """Include pending first-side decisions which can enter this receiving queue.

    First-side Interested replaces this reservation with a second-side card or
    WaitingItem under the same participant locks. Pass, expiry and cancellation
    release it. Counting persisted ACTIVE status matches active_count semantics.
    """
    first = "EMPLOYER" if side == "CANDIDATE" else "CANDIDATE"
    query = (
        select(func.count())
        .select_from(DecisionCard)
        .join(PairCycle, PairCycle.id == DecisionCard.pair_cycle_id)
        .where(
            DecisionCard.status == "ACTIVE",
            DecisionCard.side == first,
            PairCycle.first_mover == first,
            PairCycle.closed_at.is_(None),
        )
    )
    query = (
        query.where(PairCycle.candidate_id == candidate_id)
        if candidate_id
        else query.where(PairCycle.vacancy_id == vacancy_id)
    )
    return waiting_count(db, side, candidate_id, vacancy_id) + (db.scalar(query) or 0)


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
    emit(
        db,
        actor,
        "decision.issued",
        card,
        org_id=vacancy.org_id,
        payload={"pair_cycle_id": cycle.id, "exposure_side": side, "model_version": cycle.model_version},
    )
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
    snapshot = (score_trace or {}).get("features", {})
    if snapshot and snapshot.get("candidate_version") != candidate.version:
        raise AppError(412, "VERSION_CONFLICT", "Candidate changed; recompute compatibility")
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
        receiving_count(
            db,
            other,
            **({"candidate_id": candidate.id} if other == "CANDIDATE" else {"vacancy_id": vacancy.id}),
        )
        >= 10
    ):
        raise AppError(409, "WAITING_FULL", "The receiving attention queue is full")
    if not _has_capacity(db, candidate, vacancy, first_mover):
        raise AppError(409, "CAP_FULL", "Decision capacity is full")
    if isinstance((score_trace or {}).get("learning_snapshot"), dict):
        lock_scopes(db, matching_learning.COORDINATION_SCOPE)
    score_trace = matching_learning.capture_learning_consent(
        score_trace or {}, candidate, load(db, Organization, vacancy.org_id)
    )
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
    matching_learning.record_observation(db, actor, cycle)
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
    """Retrieve bounded eligible pairs, optimize attention, execute under locks."""
    proposals = []
    candidate_capacities = {}
    vacancy_capacities = {}
    learned_model, learning_reason = matching_learning.current_scoring_model(db)
    planned_model_id = learned_model.model_id if learned_model else None
    now = utcnow()
    query = (
        select(Vacancy)
        .where(
            Vacancy.state == "ACTIVE",
            Vacancy.openings_remaining > 0,
            or_(Vacancy.deadline_at.is_(None), Vacancy.deadline_at > now),
        )
        .order_by(Vacancy.id)
        .limit(50)
    )
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
        vacancy_capacities[vacancy.id] = AttentionCapacity(
            max(0, min(10, vacancy.cap) - active_count(db, vacancy_id=vacancy.id)),
            max(0, 10 - receiving_count(db, "EMPLOYER", vacancy_id=vacancy.id)),
        )
        vacancy_capacity = vacancy_capacities[vacancy.id]
        if not (vacancy_capacity.active_remaining or vacancy_capacity.waiting_remaining):
            continue
        # Apply public structured gates before the bounded pool. Otherwise old
        # incompatible, already introduced or blocked profiles can monopolize it
        # indefinitely. Private compensation and evidence remain service checks.
        from app.db.pact_models import ExclusiveReservation

        active_candidate = (
            select(func.count())
            .select_from(DecisionCard)
            .where(
                DecisionCard.candidate_id == Candidate.id,
                DecisionCard.side == "CANDIDATE",
                DecisionCard.status == "ACTIVE",
            )
            .correlate(Candidate)
            .scalar_subquery()
        )
        waiting_candidate = (
            select(func.count())
            .select_from(WaitingItem)
            .join(PairCycle, PairCycle.id == WaitingItem.pair_cycle_id)
            .where(
                PairCycle.candidate_id == Candidate.id,
                WaitingItem.side == "CANDIDATE",
                WaitingItem.state == "WAITING",
            )
            .correlate(Candidate)
            .scalar_subquery()
        )
        pending_candidate = (
            select(func.count())
            .select_from(DecisionCard)
            .join(PairCycle, PairCycle.id == DecisionCard.pair_cycle_id)
            .where(
                PairCycle.candidate_id == Candidate.id,
                PairCycle.closed_at.is_(None),
                PairCycle.first_mover == "EMPLOYER",
                DecisionCard.side == "EMPLOYER",
                DecisionCard.status == "ACTIVE",
            )
            .correlate(Candidate)
            .scalar_subquery()
        )
        prefilters = [
            Candidate.state == "ACTIVE",
            Candidate.terms_accepted.is_(True),
            Candidate.privacy_accepted.is_(True),
            Candidate.confirmed_at.is_not(None),
            Candidate.user_id != vacancy.owner_user_id,
            Candidate.currency == vacancy.currency,
            Candidate.compensation_period == vacancy.compensation_period,
            cast(Candidate.role_families, JSONB).contains([vacancy.role_family]),
            cast(Candidate.work_modes, JSONB).contains([vacancy.work_mode]),
            cast(Candidate.employment_types, JSONB).contains([vacancy.employment_type]),
            or_(Candidate.available_until.is_(None), Candidate.available_until > now),
            select(User.id).where(User.id == Candidate.user_id, User.status == "ACTIVE").exists(),
            ~select(CandidateBlock.id)
            .where(CandidateBlock.candidate_id == Candidate.id, CandidateBlock.org_id == vacancy.org_id)
            .exists(),
            ~select(PairCycle.id)
            .where(
                PairCycle.candidate_id == Candidate.id,
                PairCycle.vacancy_id == vacancy.id,
                or_(PairCycle.closed_at.is_(None), PairCycle.closed_at > now - timedelta(days=30)),
            )
            .exists(),
            ~select(OrgMember.id)
            .where(
                OrgMember.user_id == Candidate.user_id,
                OrgMember.org_id == vacancy.org_id,
                OrgMember.status == "ACTIVE",
                or_(OrgMember.expires_at.is_(None), OrgMember.expires_at > now),
            )
            .exists(),
            ~select(ExclusiveReservation.id)
            .where(
                ExclusiveReservation.candidate_id == Candidate.id,
                ExclusiveReservation.vacancy_id != vacancy.id,
                ExclusiveReservation.status == "ACTIVE",
                ExclusiveReservation.expires_at > now,
            )
            .exists(),
            or_(
                and_(
                    literal(vacancy_capacity.waiting_remaining > 0),
                    active_candidate < func.least(10, Candidate.cap),
                ),
                and_(
                    literal(vacancy_capacity.active_remaining > 0), waiting_candidate + pending_candidate < 10
                ),
            ),
        ]
        if vacancy.start_until:
            prefilters.append(
                or_(Candidate.available_from.is_(None), Candidate.available_from <= vacancy.start_until)
            )
        if vacancy.start_from:
            prefilters.append(
                or_(Candidate.available_until.is_(None), Candidate.available_until >= vacancy.start_from)
            )
        if vacancy.work_mode != "REMOTE":
            prefilters.append(
                or_(
                    cast(Candidate.locations, JSONB) == [],
                    cast(Candidate.locations, JSONB).contains([vacancy.location_region]),
                )
            )
        candidates = db.scalars(
            select(Candidate)
            .where(*prefilters)
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
            skills = tuple(
                (skill.name, tuple(skill.aliases))
                for skill in db.scalars(
                    select(Skill)
                    .join(CandidateSkill, CandidateSkill.skill_id == Skill.id)
                    .where(CandidateSkill.candidate_id == candidate.id, CandidateSkill.confirmed.is_(True))
                )
            )
            preferred = tuple(
                db.scalars(
                    select(Requirement.key).where(
                        Requirement.vacancy_id == vacancy.id, Requirement.kind == "PREFERENCE"
                    )
                )
            )
            organization = db.get(Organization, vacancy.org_id)
            features = compatibility_features(
                candidate,
                vacancy,
                skills,
                preferred,
                utcnow(),
                text_learning_enabled=bool(
                    candidate.matching_learning_opt_in
                    and organization is not None
                    and organization.matching_learning_opt_in
                ),
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
            trace = apply_learned_score(
                score_reciprocal(features, pair_prices), features, learned_model, learning_reason
            )
            if trace["net_surplus"] <= 0:
                continue
            # Preserve the native structured inputs before any optional learned
            # scorer or compatibility transformation is applied in the future.
            trace["learning_snapshot"] = {
                "employer_skills": features.employer_skills,
                "candidate_role": features.candidate_role,
                "candidate_work_mode": features.candidate_work_mode,
                "candidate_employment_type": features.candidate_employment_type,
                "skill_precision": features.skill_precision,
                "skill_jaccard": features.skill_jaccard,
                "text_relevance": features.text_relevance,
            }
            trace["learning_feature_version"] = "reciprocal-structured-v2"
            trace["learning_feature_provenance"] = {
                "text_relevance_model_id": features.text_relevance_model_id,
            }
            if features.text_relevance is not None:
                assert organization is not None
                trace["learning_planned_consent"] = {
                    "candidate_consent_version": candidate.matching_learning_consent_version,
                    "organization_consent_version": organization.matching_learning_consent_version,
                }
            if candidate.id not in candidate_capacities:
                candidate_capacities[candidate.id] = AttentionCapacity(
                    max(0, min(10, candidate.cap) - active_count(db, candidate_id=candidate.id)),
                    max(0, 10 - receiving_count(db, "CANDIDATE", candidate_id=candidate.id)),
                )
            if vacancy.id not in vacancy_capacities:
                vacancy_capacities[vacancy.id] = AttentionCapacity(
                    max(0, min(10, vacancy.cap) - active_count(db, vacancy_id=vacancy.id)),
                    max(0, 10 - receiving_count(db, "EMPLOYER", vacancy_id=vacancy.id)),
                )
            proposals.append(
                (
                    trace["net_surplus"],
                    candidate.id,
                    vacancy.id,
                    vacancy.version,
                    trace["first_mover"],
                    trace,
                )
            )
    allocation = allocate_live(
        tuple(
            LiveProposal(candidate, vacancy, Side(side), weight)
            for weight, candidate, vacancy, _, side, _ in proposals
        ),
        candidate_capacities,
        vacancy_capacities,
    )
    by_pair = {
        (candidate, vacancy): (version, side, trace)
        for _, candidate, vacancy, version, side, trace in proposals
    }
    issued = []
    if allocation.proposals:
        # Acquire every participant before the registry lock. Later introductions
        # reuse these locks, so consent revocation cannot create a lock inversion.
        lock_scopes(
            db,
            *(f"candidate:{item.candidate_id}" for item in allocation.proposals),
            *(f"vacancy:{item.vacancy_id}" for item in allocation.proposals),
        )
        lock_scopes(db, matching_learning.COORDINATION_SCOPE)
        current_model, _ = matching_learning.current_scoring_model(db)
        if (current_model.model_id if current_model else None) != planned_model_id:
            raise AppError(409, "MODEL_VERSION_CONFLICT", "Scoring model changed; retry allocation")
    for proposal in allocation.proposals:
        candidate_id, vacancy_id = proposal.pair
        version, side, trace = by_pair[proposal.pair]
        trace["allocation"] = {
            "allocator_version": allocation.allocator_version,
            "solver": allocation.solver,
            "objective": allocation.objective,
            "baseline_objective": allocation.baseline_objective,
            "search_complete": allocation.search_complete,
            "fallback_reason": allocation.fallback_reason,
            "objective_kind": "SUPPLIED_CONDITIONAL_UTILITY"
            if planned_model_id
            else "SUPPLIED_COMPATIBILITY_UTILITY",
        }
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
