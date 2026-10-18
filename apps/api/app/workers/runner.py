"""Durable outbox consumption, maintenance and isolated shadow research.

Run ``python -m app.workers.runner --once`` or keep the process running. There is
no Redis-only correctness dependency and no email delivery claim without a vendor.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.models import (
    Candidate,
    CandidateSkill,
    CongestionPrice,
    DecisionCard,
    EmploymentStart,
    InboxConsumption,
    Interview,
    InterviewProposal,
    MarketPrice,
    Message,
    MutualMatch,
    Notification,
    NotificationPreference,
    OutboxEvent,
    PairCycle,
    PrivacyRequest,
    Requirement,
    ShadowRun,
    Skill,
    StageEvent,
    User,
    Vacancy,
)
from app.db.pact_models import (
    Clarification,
    EvidenceClaim,
    EvidenceGrant,
    ExclusiveReservation,
    ReadinessProof,
    TermConsent,
)
from app.matching.attention import DualPrice, MarketPrices, update_price
from app.matching.baseline import AllocationProposal, HeuristicPairScorer
from app.matching.portfolio import Commitment, MarketSnapshot, ResearchEdge, VacancyResearch
from app.matching.score import DirectionScore, PairScore
from app.matching.shadow_adapter import run_shadow
from app.matching.types import EstimateKind, SanitizedPairFeatures, Side, stable_hash
from app.services import clearing
from app.services.common import Actor, digest, emit, lock_scopes, require_vacancy, utcnow

LOG = logging.getLogger("career_kitchen.worker")
CONSUMER = "career-kitchen-outbox-v1"
WORKER_ISSUER = "urn:career-kitchen:internal-worker"
WORKER_SUBJECT = "outbox-runner"
MAX_ATTEMPTS = 5
RESEARCH_EVENTS = frozenset({"shortlist.replan_requested"})
RECONCILE_EVENTS = frozenset(
    {
        "candidate.activated",
        "candidate.paused",
        "candidate.profile_updated",
        "candidate.preferences_changed",
        "candidate.skill_added",
        "candidate.org_blocked",
        "candidate.evidence_changed",
        "candidate.consent_granted",
        "candidate.consent_revoked",
        "candidate.reservation_released",
        "vacancy.activated",
        "vacancy.updated",
        "candidate.consent_expired",
        "candidate.evidence_expired",
        "vacancy.paused",
        "vacancy.closed",
        "vacancy.requirements_updated",
        "organization.verified",
        "decision.interested",
        "decision.passed",
        "decision.expired",
        "pact.clarification_resolved",
        "pact.policy_revoked",
        "employment_start.verified",
        "market.price_updated",
    }
)


@dataclass(frozen=True)
class WorkerResult:
    consumed: int = 0
    failed: int = 0
    expired: int = 0
    released: int = 0
    reminders: int = 0


def worker_actor(db: Session) -> Actor:
    """Machine identity is persisted, unavailable through the public JWT issuer."""
    user = db.scalar(select(User).where(User.issuer == WORKER_ISSUER, User.subject == WORKER_SUBJECT))
    if user is None:
        lock_scopes(db, "worker:identity:outbox-runner")
        user = db.scalar(select(User).where(User.issuer == WORKER_ISSUER, User.subject == WORKER_SUBJECT))
        if user is None:
            user = User(
                issuer=WORKER_ISSUER,
                subject=WORKER_SUBJECT,
                verified_email="",
                platform_roles=["SYSTEM_WORKER"],
            )
            db.add(user)
            db.flush()
    if user.status != "ACTIVE" or user.platform_roles != ["SYSTEM_WORKER"]:
        raise RuntimeError("worker identity disabled or unexpectedly privileged")
    return Actor(user.id, utcnow(), ("SYSTEM_WORKER",), request_id="outbox-worker")


def _authorized_employer(db: Session, user_id: str, vacancy_id: str) -> bool:
    try:
        require_vacancy(db, Actor(user_id, utcnow()), vacancy_id)
        return True
    except AppError:
        return False


def _cycle_recipients(db: Session, cycle: PairCycle) -> set[str]:
    candidate, vacancy = db.get(Candidate, cycle.candidate_id), db.get(Vacancy, cycle.vacancy_id)
    if candidate is None or vacancy is None:
        return set()
    recipients = {candidate.user_id}
    if _authorized_employer(db, vacancy.owner_user_id, vacancy.id):
        recipients.add(vacancy.owner_user_id)
    return recipients


def notification_recipients(db: Session, event: OutboxEvent) -> set[str]:
    """Resolve references against current state; payload never supplies user IDs."""
    if event.kind == "privacy.export_ready":
        operation = db.get(PrivacyRequest, event.aggregate_id)
        return (
            {operation.user_id}
            if operation and operation.kind == "EXPORT" and operation.status == "COMPLETE"
            else set()
        )
    if event.kind in {"decision.issued", "decision.expiring", "decision.expired"}:
        card = db.get(DecisionCard, event.aggregate_id)
        if card is None:
            return set()
        cycle = db.get(PairCycle, card.pair_cycle_id)
        vacancy = db.get(Vacancy, card.vacancy_id)
        if cycle is None or vacancy is None:
            return set()
        if event.kind in {"decision.issued", "decision.expiring"} and (
            card.status != "ACTIVE"
            or card.expires_at <= utcnow()
            or cycle.closed_at
            or vacancy.state != "ACTIVE"
            or vacancy.version != cycle.role_version
        ):
            return set()
        if card.side == "CANDIDATE":
            candidate = db.get(Candidate, card.candidate_id)
            return {candidate.user_id} if candidate and candidate.user_id == card.recipient_user_id else set()
        return (
            {card.recipient_user_id}
            if _authorized_employer(db, card.recipient_user_id, vacancy.id)
            else set()
        )
    match_id = None
    sender = None
    cycle = None
    if event.kind == "pair.mutual":
        match_id = event.aggregate_id
    elif event.kind == "message.sent":
        message = db.get(Message, event.aggregate_id)
        if message:
            match_id, sender = message.match_id, message.sender_user_id
    elif event.kind in {"interview.proposed", "interview.confirmed"}:
        interview = (
            db.get(InterviewProposal, event.aggregate_id)
            if event.kind == "interview.proposed"
            else db.get(Interview, event.aggregate_id)
        )
        if interview:
            match_id = interview.match_id
            sender = getattr(interview, "initiator_id", None)
    elif event.kind in {"offer.issued", "offer.accepted", "offer.declined"}:
        from app.db.models import Offer

        offer = db.get(Offer, event.aggregate_id)
        if offer:
            cycle = db.get(PairCycle, offer.pair_cycle_id)
    elif event.kind == "process.stage_changed":
        stage = db.get(StageEvent, event.aggregate_id)
        if stage:
            cycle = db.get(PairCycle, stage.pair_cycle_id)
    elif event.kind in {"employment_start.reported", "employment_start.verified"}:
        start = db.get(EmploymentStart, event.aggregate_id)
        if start:
            cycle = db.get(PairCycle, start.pair_cycle_id)
    elif event.kind in {"candidate.evidence_changed", "candidate.evidence_pending"}:
        claim = db.get(EvidenceClaim, event.aggregate_id)
        candidate = db.get(Candidate, claim.candidate_id) if claim else None
        return {candidate.user_id} if candidate else set()
    elif event.kind in {"pact.clarification_requested", "pact.clarification_resolved"}:
        clarification = db.get(Clarification, event.aggregate_id)
        if clarification:
            ids = {clarification.requested_by}
            vacancy = db.get(Vacancy, clarification.vacancy_id)
            if vacancy and _authorized_employer(db, vacancy.owner_user_id, vacancy.id):
                ids.add(vacancy.owner_user_id)
            return {key for key in ids if _authorized_employer(db, key, clarification.vacancy_id)}
    if match_id:
        match = db.get(MutualMatch, match_id)
        if match is None or match.status != "ACTIVE":
            return set()
        cycle = db.get(PairCycle, match.pair_cycle_id)
        if (
            cycle is None
            or cycle.closed_at
            or not (cycle.candidate_interested_at and cycle.employer_interested_at)
        ):
            return set()
    return _cycle_recipients(db, cycle) - {sender} if cycle else set()


def enqueue_notifications(db: Session, event: OutboxEvent) -> int:
    added = 0
    for user_id in sorted(notification_recipients(db, event)):
        user = db.get(User, user_id)
        if user is None or user.status != "ACTIVE":
            continue
        preference = db.scalar(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        if preference and not preference.in_app_opt_in:
            continue
        existing = db.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.event_id == event.id,
                Notification.kind == event.kind,
            )
        )
        if existing is None:
            # A persisted in-app item is delivery. External mail is deliberately not
            # marked SENT: no mail provider adapter exists in this deployment.
            db.add(
                Notification(
                    user_id=user_id,
                    event_id=event.id,
                    kind=event.kind,
                    entity_id=event.aggregate_id,
                    email_status="NOT_CONFIGURED",
                )
            )
            added += 1
    return added


def expiring_reminders(db: Session, actor: Actor, batch_size: int = 100) -> int:
    """At most two reminders, one in each final 24h / 12h window, with DB locks."""
    now = utcnow()
    cards = list(
        db.scalars(
            select(DecisionCard)
            .where(
                DecisionCard.status == "ACTIVE",
                DecisionCard.expires_at > now,
                DecisionCard.expires_at <= now + timedelta(hours=24),
                DecisionCard.reminder_count < 2,
            )
            .order_by(DecisionCard.expires_at, DecisionCard.id)
            .limit(batch_size)
        )
    )
    count = 0
    for old in cards:
        lock_scopes(db, f"candidate:{old.candidate_id}", f"vacancy:{old.vacancy_id}")
        card = db.scalar(
            select(DecisionCard).where(DecisionCard.id == old.id).execution_options(populate_existing=True)
        )
        if card is None or card.status != "ACTIVE" or card.expires_at <= now or card.reminder_count >= 2:
            continue
        if card.reminder_count == 1 and card.expires_at > now + timedelta(hours=12):
            continue
        cycle = db.get(PairCycle, card.pair_cycle_id)
        vacancy = db.get(Vacancy, card.vacancy_id)
        if (
            not cycle
            or cycle.closed_at
            or not vacancy
            or vacancy.state != "ACTIVE"
            or vacancy.version != cycle.role_version
        ):
            continue
        card.reminder_count += 1
        card.version += 1
        emit(db, actor, "decision.expiring", card, payload={"reminder_number": card.reminder_count})
        count += 1
    return count


def affected_vacancies(db: Session, event: OutboxEvent) -> list[str]:
    """Only bounded active scopes are reconciled; event JSON cannot widen authority."""
    kind = event.payload.get("entity_type")
    entity_id = event.aggregate_id
    vacancy_id = None
    if kind == "vacancies":
        vacancy_id = entity_id
    elif kind == "decision_cards":
        card = db.get(DecisionCard, entity_id)
        vacancy_id = card.vacancy_id if card else None
    elif kind == "vacancy_requirements":
        requirement = db.get(Requirement, entity_id)
        vacancy_id = requirement.vacancy_id if requirement else None
    elif kind == "policy_clarification_requests":
        clarification = db.get(Clarification, entity_id)
        vacancy_id = clarification.vacancy_id if clarification else None
    elif kind in {"evidence_access_grants", "candidate_term_consents"}:
        grant = (
            db.get(EvidenceGrant, entity_id)
            if kind == "evidence_access_grants"
            else db.get(TermConsent, entity_id)
        )
        vacancy_id = grant.vacancy_id if grant else None
    if vacancy_id:
        return [vacancy_id]
    return list(
        db.scalars(select(Vacancy.id).where(Vacancy.state == "ACTIVE").order_by(Vacancy.id).limit(20))
    )


def handle_event(db: Session, actor: Actor, event: OutboxEvent) -> list[dict[str, Any]]:
    if event.kind in RESEARCH_EVENTS:
        return []  # Research requests run after commit; they never issue live cards.
    if event.kind in {"privacy.export_requested", "privacy.delete_requested"}:
        from app.workers.privacy import process_privacy_request

        process_privacy_request(db, actor, event.aggregate_id)
        return []
    enqueue_notifications(db, event)
    if event.kind not in RECONCILE_EVENTS:
        return []  # decision.issued must not recursively issue more cards.
    clearing.expire_due(db, actor)
    clearing.release_waiting(db, actor)
    scopes = affected_vacancies(db, event)
    invalidate_pending(db, actor, scopes)
    return clearing.reconcile(db, actor, vacancy_ids=scopes, pool_limit=50) if scopes else []


def invalidate_pending(db: Session, actor: Actor, vacancy_ids: list[str], limit: int = 200) -> int:
    """Pending cards cannot retain stale terms or missing essential qualifications."""
    if not vacancy_ids:
        return 0
    count = 0
    rows = list(
        db.scalars(
            select(PairCycle)
            .where(
                PairCycle.vacancy_id.in_(vacancy_ids),
                PairCycle.closed_at.is_(None),
                PairCycle.state.not_in(clearing.POST_MATCH),
            )
            .order_by(PairCycle.created_at, PairCycle.id)
            .limit(limit)
        )
    )
    for old in rows:
        lock_scopes(db, f"candidate:{old.candidate_id}", f"vacancy:{old.vacancy_id}")
        pair = db.scalar(
            select(PairCycle).where(PairCycle.id == old.id).execution_options(populate_existing=True)
        )
        if pair is None or pair.closed_at:
            continue
        candidate, vacancy = db.get(Candidate, pair.candidate_id), db.get(Vacancy, pair.vacancy_id)
        if (
            candidate is None
            or vacancy is None
            or pair.role_version != vacancy.version
            or not clearing.feasible(db, candidate, vacancy)[0]
        ):
            clearing.close_cycle(db, actor, pair, "CLOSED_EXPIRED")
            count += 1
    return count


def expire_pact_dependencies(db: Session, actor: Actor, batch_size: int = 100) -> int:
    """Make timed transitions explicit without inventing user revocation timestamps."""
    from app.services.pact import invalidate_readiness

    now = utcnow()
    changed = 0
    for old_reservation in db.scalars(
        select(ExclusiveReservation)
        .where(
            ExclusiveReservation.status == "ACTIVE",
            ExclusiveReservation.expires_at <= now,
        )
        .order_by(ExclusiveReservation.id)
        .limit(batch_size)
    ):
        lock_scopes(db, f"candidate:{old_reservation.candidate_id}", f"vacancy:{old_reservation.vacancy_id}")
        reservation = db.scalar(
            select(ExclusiveReservation)
            .where(ExclusiveReservation.id == old_reservation.id)
            .execution_options(populate_existing=True)
        )
        if reservation and reservation.status == "ACTIVE" and reservation.expires_at <= now:
            reservation.status = "EXPIRED"
            reservation.version += 1
            emit(db, actor, "candidate.reservation_released", reservation)
            changed += 1
    for old_proof in db.scalars(
        select(ReadinessProof)
        .where(ReadinessProof.state == "READY", ReadinessProof.expires_at <= now)
        .order_by(ReadinessProof.id)
        .limit(batch_size)
    ):
        lock_scopes(db, f"candidate:{old_proof.candidate_id}", f"vacancy:{old_proof.vacancy_id}")
        proof = db.scalar(
            select(ReadinessProof)
            .where(ReadinessProof.id == old_proof.id)
            .execution_options(populate_existing=True)
        )
        if proof and proof.state == "READY" and proof.expires_at <= now:
            proof.state, proof.invalidated_reason = "EXPIRED", "TIME_EXPIRED"
            proof.version += 1
            emit(db, actor, "pact.readiness_expired", proof)
            changed += 1
    for old_clarification in db.scalars(
        select(Clarification)
        .where(Clarification.status == "REQUESTED", Clarification.expires_at <= now)
        .order_by(Clarification.id)
        .limit(batch_size)
    ):
        lock_scopes(db, f"vacancy:{old_clarification.vacancy_id}")
        clarification = db.scalar(
            select(Clarification)
            .where(Clarification.id == old_clarification.id)
            .execution_options(populate_existing=True)
        )
        if clarification and clarification.status == "REQUESTED" and clarification.expires_at <= now:
            clarification.status = "EXPIRED"
            clarification.version += 1
            emit(db, actor, "pact.clarification_expired", clarification)
            changed += 1
    expiration_models: tuple[tuple[Any, str], ...] = (
        (EvidenceGrant, "candidate.consent_expired"),
        (TermConsent, "candidate.consent_expired"),
        (EvidenceClaim, "candidate.evidence_expired"),
    )
    for model, event_kind in expiration_models:
        # An append-only expiration event is the processing marker for records
        # whose schema intentionally distinguishes expiry from revocation.
        prior = (
            select(OutboxEvent.id)
            .where(OutboxEvent.aggregate_id == model.id, OutboxEvent.kind == event_kind)
            .exists()
        )
        query = (
            select(model)
            .where(model.expires_at <= now, model.revoked_at.is_(None), ~prior)
            .order_by(model.id)
            .limit(batch_size)
        )
        expired_rows: list[Any] = list(db.execute(query).scalars())
        for item in expired_rows:
            keys = [f"candidate:{item.candidate_id}"]
            vacancy_id = getattr(item, "vacancy_id", None)
            if vacancy_id:
                keys.append(f"vacancy:{vacancy_id}")
            lock_scopes(db, *keys)
            item = db.scalar(
                select(model).where(model.id == item.id).execution_options(populate_existing=True)
            )
            if (
                item is None
                or item.revoked_at is not None
                or item.expires_at is None
                or item.expires_at > now
            ):
                continue
            if db.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.aggregate_id == item.id, OutboxEvent.kind == event_kind
                )
            ):
                continue
            invalidate_readiness(
                db, candidate_id=item.candidate_id, vacancy_id=vacancy_id, reason="DEPENDENCY_EXPIRED"
            )
            emit(db, actor, event_kind, item)
            changed += 1
    db.flush()
    return changed


def _shadow_snapshot(db: Session, state_version: str) -> MarketSnapshot:
    """Authorized builder only. No database handle is passed into the pure planner."""
    jobs = list(db.scalars(select(Vacancy).where(Vacancy.state == "ACTIVE").order_by(Vacancy.id).limit(20)))
    job_ids = [job.id for job in jobs]
    candidates = list(
        db.scalars(select(Candidate).where(Candidate.state == "ACTIVE").order_by(Candidate.id).limit(100))
    )
    reservations = list(
        db.scalars(
            select(ExclusiveReservation)
            .where(
                ExclusiveReservation.status == "ACTIVE",
                ExclusiveReservation.expires_at > utcnow(),
                ExclusiveReservation.candidate_id.in_([candidate.id for candidate in candidates]),
            )
            .limit(100)
        )
    )
    reserved_for = {reserve.candidate_id: reserve.vacancy_id for reserve in reservations}
    definitions = tuple(VacancyResearch(job.id, job.version, min(10, job.cap)) for job in jobs)
    attention = {
        row.cell: row
        for row in db.scalars(
            select(MarketPrice).where(MarketPrice.cell.in_([job.role_family for job in jobs]))
        )
    }
    congestion = {
        (row.scope_id, row.side): row
        for row in db.scalars(
            select(CongestionPrice).where(
                CongestionPrice.scope_id.in_(job_ids + [candidate.id for candidate in candidates])
            )
        )
    }
    edges = []
    versions: list[Any] = [(job.id, job.version) for job in jobs]
    versions.extend((row.id, row.version) for row in attention.values())
    versions.extend((row.id, row.version) for row in congestion.values())
    for candidate in candidates:
        versions.append((candidate.id, candidate.version))
        skills = set(
            db.scalars(
                select(Skill.name)
                .join(CandidateSkill, CandidateSkill.skill_id == Skill.id)
                .where(CandidateSkill.candidate_id == candidate.id)
            )
        )
        for job in jobs:
            if candidate.id in reserved_for and reserved_for[candidate.id] != job.id:
                continue
            if job.role_family not in candidate.role_families or not clearing.feasible(db, candidate, job)[0]:
                continue
            preferred = set(
                db.scalars(
                    select(Requirement.key).where(
                        Requirement.vacancy_id == job.id, Requirement.kind == "PREFERENCE"
                    )
                )
            )
            feature = SanitizedPairFeatures(
                candidate.id,
                job.id,
                job.role_family,
                "structured-v1",
                utcnow(),
                skill_alignment=len(skills & preferred) / len(preferred) if preferred else 0,
                work_mode_alignment=1,
            )
            market = attention.get(job.role_family)
            candidate_congestion = congestion.get((candidate.id, "CANDIDATE"))
            job_congestion = congestion.get((job.id, "EMPLOYER"))
            prices = MarketPrices(
                mu_candidate=market.candidate_price if market else 0,
                mu_employer=market.employer_price if market else 0,
                candidate_congestion=candidate_congestion.price if candidate_congestion else 0,
                job_congestion=job_congestion.price if job_congestion else 0,
            )
            score = HeuristicPairScorer().score(feature, prices)
            edges.append(ResearchEdge(candidate.id, job.id, max(0, score.best.net_surplus)))
    commitments: dict[tuple[str, str], Commitment] = {}
    for pair in db.scalars(
        select(PairCycle).where(PairCycle.vacancy_id.in_(job_ids), PairCycle.closed_at.is_(None)).limit(2000)
    ):
        versions.append((pair.id, pair.version))
        commitments[(pair.candidate_id, pair.vacancy_id)] = Commitment(
            pair.candidate_id,
            pair.vacancy_id,
            "MUTUAL" if pair.state in clearing.POST_MATCH else "ACTIVE_DECISION",
        )
    for reserve in reservations:
        if reserve.vacancy_id not in job_ids:
            continue
        versions.append((reserve.id, reserve.version))
        commitments[(reserve.candidate_id, reserve.vacancy_id)] = Commitment(
            reserve.candidate_id, reserve.vacancy_id, "CONSENTED_EXCLUSIVE"
        )
    return MarketSnapshot(
        digest([state_version, versions]), definitions, tuple(edges), tuple(commitments.values())
    )


def record_shadow(factory: sessionmaker[Session], event_id: str, issued: list[dict[str, Any]]) -> None:
    try:
        with factory() as db:
            snapshot = _shadow_snapshot(db, event_id)
            baseline = []
            for row in issued:
                card = db.get(DecisionCard, row["decision_id"])
                pair = db.get(PairCycle, card.pair_cycle_id) if card else None
                if not pair:
                    continue
                trace = pair.score_trace
                directional = []
                for name, side in (("candidate_first", Side.CANDIDATE), ("employer_first", Side.EMPLOYER)):
                    data = trace.get(name, {})
                    directional.append(
                        DirectionScore(
                            side,
                            data.get("gross_value", 0),
                            data.get("attention_cost", 0),
                            data.get("congestion_cost", 0),
                            data.get("net_surplus", 0),
                        )
                    )
                score = PairScore(
                    pair.candidate_id,
                    pair.vacancy_id,
                    directional[0],
                    directional[1],
                    EstimateKind.NONPROBABILISTIC,
                    pair.model_version,
                    trace.get("feature_hash", ""),
                    tuple(trace.get("reason_codes", ())),
                )
                baseline.append(
                    AllocationProposal(
                        pair.candidate_id,
                        pair.vacancy_id,
                        Side(row["side"]),
                        score.best.net_surplus,
                        score,
                        snapshot.digest,
                    )
                )
        # The session has closed; pure computation has neither DB handle nor notifier.
        result = run_shadow(snapshot, tuple(baseline), enabled=True)
        with factory.begin() as db:
            lock_scopes(db, f"shadow:{event_id}")
            if db.scalar(select(ShadowRun.id).where(ShadowRun.event_id == event_id)):
                return
            db.add(
                ShadowRun(
                    event_id=event_id,
                    snapshot_hash=result.snapshot_hash,
                    baseline_hash=result.baseline_proposal_hash,
                    proposal_hash=stable_hash(result.advanced_plan),
                    diagnostics={
                        "reasons": result.reasons,
                        "elapsed_seconds": result.elapsed_seconds,
                        "certification_state": "CANNOT_CERTIFY",
                        "vacancies": len(snapshot.vacancies),
                        "model_coverage": result.advanced_plan.population_coverage
                        if result.advanced_plan
                        else 0,
                    },
                    side_effect_count=result.side_effect_count,
                )
            )
    except Exception as error:
        # A sidecar failure never retries/reverts committed baseline decisions.
        LOG.warning("shadow failure type=%s event=%s", type(error).__name__, event_id)


def process_one(factory: sessionmaker[Session], *, shadow: bool | None = None) -> tuple[bool, bool]:
    issued: list[dict[str, Any]] = []
    event_id = None
    success = False
    research_requested = False
    with factory.begin() as db:
        actor = worker_actor(db)
        event = db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.dispatched_at.is_(None),
                OutboxEvent.dead_letter_at.is_(None),
                OutboxEvent.available_at <= utcnow(),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            return False, False
        event_id = event.id
        research_requested = event.kind in RECONCILE_EVENTS or event.kind in RESEARCH_EVENTS
        if db.get(InboxConsumption, (CONSUMER, event.id)):
            event.dispatched_at = utcnow()
            return True, True
        event.attempts += 1
        try:
            with db.begin_nested():
                issued = handle_event(db, actor, event)
                db.add(InboxConsumption(consumer_name=CONSUMER, event_id=event.id))
                db.flush()
            event.dispatched_at = utcnow()
            event.last_error = None
            success = True
        except Exception as error:
            event.last_error = type(error).__name__[:80]
            if event.attempts >= MAX_ATTEMPTS:
                event.dead_letter_at = utcnow()
            else:
                event.available_at = utcnow() + timedelta(seconds=min(300, 2**event.attempts))
            LOG.warning(
                "outbox retry type=%s event=%s attempt=%d", type(error).__name__, event.id, event.attempts
            )
    if (
        success
        and event_id
        and research_requested
        and (get_settings().feature_mode == "SHADOW" if shadow is None else shadow)
    ):
        record_shadow(factory, event_id, issued)
    return True, success


def maintenance(factory: sessionmaker[Session]) -> tuple[int, int, int]:
    with factory.begin() as db:
        actor = worker_actor(db)
        # Only one periodic pass per market at once; request-level card locks remain
        # authoritative and individual state changes are idempotent under replay.
        lock_scopes(db, "worker:periodic-maintenance")
        expire_pact_dependencies(db, actor)
        expired = clearing.expire_due(db, actor)
        released = clearing.release_waiting(db, actor)
        reminders = expiring_reminders(db, actor)
        update_congestion_prices(db, actor)
        update_market_prices(db, actor)
        return expired, released, reminders


def update_market_prices(db: Session, actor: Actor, now: datetime | None = None) -> int:
    """Persist original adaptive duals once per configured control window.

    A is actual new decision cards in the window. B is current free selected
    slots plus completed decisions in the same interval (responsible throughput).
    Candidate free slots are global across their active markets, so this is a
    per-cell scarcity approximation; transactional caps remain authoritative.
    """
    end = now or utcnow()
    settings = get_settings()
    families = list(
        db.scalars(
            select(Vacancy.role_family)
            .where(Vacancy.state == "ACTIVE")
            .distinct()
            .order_by(Vacancy.role_family)
            .limit(50)
        )
    )
    changed = 0
    for family in families:
        lock_scopes(db, f"market-prices:{family}")
        price = db.scalar(select(MarketPrice).where(MarketPrice.cell == family))
        if price is None:
            price = MarketPrice(cell=family)
            db.add(price)
            db.flush()
        previous = db.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.aggregate_id == price.id, OutboxEvent.kind == "market.price_updated")
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id)
            .limit(1)
        )
        start = (
            datetime.fromisoformat(previous.payload["window_end"])
            if previous and previous.payload.get("window_end")
            else end - timedelta(seconds=settings.market_price_window_seconds)
        )
        if previous and end - start < timedelta(seconds=settings.market_price_window_seconds):
            continue
        candidate_ids = select(Candidate.id).where(
            Candidate.state == "ACTIVE", cast(Candidate.role_families, JSONB).contains([family])
        )
        vacancy_ids = select(Vacancy.id).where(Vacancy.state == "ACTIVE", Vacancy.role_family == family)
        candidate_limit = (
            db.scalar(
                select(func.coalesce(func.sum(Candidate.cap), 0)).where(Candidate.id.in_(candidate_ids))
            )
            or 0
        )
        employer_limit = (
            db.scalar(select(func.coalesce(func.sum(Vacancy.cap), 0)).where(Vacancy.id.in_(vacancy_ids))) or 0
        )
        completed = or_(
            ((DecisionCard.answered_at >= start) & (DecisionCard.answered_at < end)),
            (
                (DecisionCard.status == "EXPIRED")
                & (DecisionCard.expires_at >= start)
                & (DecisionCard.expires_at < end)
            ),
        )
        statistics = {}
        for side, limit in (("CANDIDATE", candidate_limit), ("EMPLOYER", employer_limit)):
            scope = (
                DecisionCard.candidate_id.in_(candidate_ids)
                if side == "CANDIDATE"
                else DecisionCard.vacancy_id.in_(vacancy_ids)
            )
            active = (
                db.scalar(
                    select(func.count())
                    .select_from(DecisionCard)
                    .where(scope, DecisionCard.side == side, DecisionCard.status == "ACTIVE")
                )
                or 0
            )
            resolved = (
                db.scalar(
                    select(func.count())
                    .select_from(DecisionCard)
                    .where(scope, DecisionCard.side == side, completed)
                )
                or 0
            )
            family_jobs = select(Vacancy.id).where(Vacancy.role_family == family)
            issued = (
                db.scalar(
                    select(func.count())
                    .select_from(DecisionCard)
                    .where(
                        DecisionCard.side == side,
                        DecisionCard.vacancy_id.in_(family_jobs),
                        DecisionCard.created_at >= start,
                        DecisionCard.created_at < end,
                    )
                )
                or 0
            )
            capacity = max(0, limit - active) + resolved
            statistics[side] = {
                "issued": issued,
                "free_slots": max(0, limit - active),
                "completed": resolved,
                "capacity": capacity,
            }
            before = (
                DualPrice(price.candidate_price, price.candidate_h)
                if side == "CANDIDATE"
                else DualPrice(price.employer_price, price.employer_h)
            )
            after = update_price(before, issued, capacity, maximum=settings.market_price_max)
            if side == "CANDIDATE":
                price.candidate_price, price.candidate_h = after.price, after.gradient_sum_sq
            else:
                price.employer_price, price.employer_h = after.price, after.gradient_sum_sq
        price.version += 1
        emit(
            db,
            actor,
            "market.price_updated",
            price,
            payload={
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "config": {
                    "controller_version": "legacy-dual-v1",
                    "window_seconds": settings.market_price_window_seconds,
                    "maximum": settings.market_price_max,
                },
                "statistics": statistics,
            },
        )
        changed += 1
    return changed


def update_congestion_prices(
    db: Session, actor: Actor, now: datetime | None = None, batch_size: int = 200
) -> int:
    """Original entity dual controller on actual active + hidden waiting load.

    Processing capacity is selected slots plus completed decisions in the control
    interval. Oldest/uncontrolled scopes are processed first to avoid starvation.
    """
    if not 1 <= batch_size <= 1000:
        raise ValueError("congestion batch size must be in 1..1000")
    end = now or utcnow()
    settings = get_settings()
    changed = 0
    entity_models: tuple[tuple[Any, str], ...] = ((Candidate, "CANDIDATE"), (Vacancy, "EMPLOYER"))
    for model, side in entity_models:
        query = select(model).outerjoin(
            CongestionPrice, (CongestionPrice.scope_id == model.id) & (CongestionPrice.side == side)
        )
        query = (
            query.where(model.state == "ACTIVE")
            .order_by(CongestionPrice.controlled_at.asc().nulls_first(), model.id)
            .limit(batch_size)
        )
        scopes: list[Any] = list(db.execute(query).scalars())
        for entity in scopes:
            lock_scopes(db, f"congestion:{side}:{entity.id}")
            price = db.scalar(
                select(CongestionPrice).where(
                    CongestionPrice.scope_id == entity.id, CongestionPrice.side == side
                )
            )
            if (
                price
                and price.controlled_at
                and end - price.controlled_at < timedelta(seconds=settings.market_price_window_seconds)
            ):
                continue
            if price is None:
                price = CongestionPrice(scope_id=entity.id, side=side)
                db.add(price)
                db.flush()
            start = price.controlled_at or end - timedelta(seconds=settings.market_price_window_seconds)
            scope = (
                DecisionCard.candidate_id == entity.id
                if side == "CANDIDATE"
                else DecisionCard.vacancy_id == entity.id
            )
            active = (
                db.scalar(
                    select(func.count())
                    .select_from(DecisionCard)
                    .where(scope, DecisionCard.side == side, DecisionCard.status == "ACTIVE")
                )
                or 0
            )
            completed = or_(
                (DecisionCard.answered_at >= start) & (DecisionCard.answered_at < end),
                (DecisionCard.status == "EXPIRED")
                & (DecisionCard.expires_at >= start)
                & (DecisionCard.expires_at < end),
            )
            resolved = (
                db.scalar(
                    select(func.count())
                    .select_from(DecisionCard)
                    .where(scope, DecisionCard.side == side, completed)
                )
                or 0
            )
            waiting = clearing.waiting_count(
                db,
                side,
                **({"candidate_id": entity.id} if side == "CANDIDATE" else {"vacancy_id": entity.id}),
            )
            capacity = min(10, entity.cap) + resolved
            after = update_price(
                DualPrice(price.price, price.gradient_h),
                active + waiting,
                capacity,
                maximum=settings.congestion_price_max,
            )
            price.price, price.gradient_h, price.controlled_at = after.price, after.gradient_sum_sq, end
            price.version += 1
            emit(
                db,
                actor,
                "congestion.price_updated",
                price,
                payload={
                    "scope_id": entity.id,
                    "side": side,
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "active": active,
                    "waiting": waiting,
                    "completed": resolved,
                    "processing_capacity": capacity,
                    "controller_version": "legacy-dual-v1",
                    "maximum": settings.congestion_price_max,
                },
            )
            changed += 1
    return changed


def run_once(factory: sessionmaker[Session] | None = None, batch_size: int = 50) -> WorkerResult:
    if not 1 <= batch_size <= 200:
        raise ValueError("worker batch size must be in 1..200")
    if factory is None:
        from app.db.session import SessionLocal

        factory = SessionLocal
    expired, released, reminders = maintenance(factory)
    consumed = failed = 0
    for _ in range(batch_size):
        found, success = process_one(factory)
        if not found:
            break
        consumed += int(success)
        failed += int(not success)
    return WorkerResult(consumed, failed, expired, released, reminders)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one bounded maintenance/queue batch")
    parser.add_argument("--batch-size", type=int, default=50)
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    while True:
        try:
            result = run_once(batch_size=options.batch_size)
            LOG.info(
                "batch consumed=%d failed=%d expired=%d released=%d reminders=%d",
                result.consumed,
                result.failed,
                result.expired,
                result.released,
                result.reminders,
            )
        except Exception as error:
            LOG.error("worker batch failure type=%s", type(error).__name__)
            if options.once:
                raise SystemExit(1) from None
        if options.once:
            return
        time.sleep(get_settings().worker_poll_seconds)


if __name__ == "__main__":
    main()
