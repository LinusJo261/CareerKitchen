from __future__ import annotations

import html
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.db.models import (
    Attachment,
    Candidate,
    EmploymentStart,
    Interview,
    InterviewProposal,
    Message,
    MutualMatch,
    Offer,
    PairCycle,
    StageEvent,
    Vacancy,
)
from app.services.clearing import POST_MATCH, close_cycle
from app.services.common import (
    Actor,
    digest,
    emit,
    load,
    lock_scopes,
    require_platform,
    require_vacancy,
    require_version,
    utcnow,
)


def participant(
    db: Session, actor: Actor, match_id: str, active: bool = True
) -> tuple[MutualMatch, PairCycle, Candidate, Vacancy, bool]:
    match = load(db, MutualMatch, match_id)
    cycle = load(db, PairCycle, match.pair_cycle_id)
    candidate, vacancy = load(db, Candidate, cycle.candidate_id), load(db, Vacancy, cycle.vacancy_id)
    is_candidate = candidate.user_id == actor.user_id
    if not is_candidate:
        require_vacancy(db, actor, vacancy.id)
    if active and (match.status != "ACTIVE" or cycle.closed_at or cycle.state not in POST_MATCH):
        raise AppError(403, "MUTUAL_MATCH_REQUIRED", "An active mutual match is required")
    if not cycle.candidate_interested_at or not cycle.employer_interested_at:
        raise AppError(403, "DOUBLE_OPT_IN_REQUIRED", "Both participants must express interest")
    return match, cycle, candidate, vacancy, is_candidate


def match_out(db: Session, actor: Actor, match_id: str) -> dict:
    match, cycle, candidate, vacancy, _ = participant(db, actor, match_id, active=False)
    return {
        "id": match.id,
        "version": match.version,
        "pair_cycle_id": cycle.id,
        "cycle_version": cycle.version,
        "state": cycle.state,
        "status": match.status,
        "candidate": {"id": candidate.id, "headline": candidate.headline},
        "vacancy": {"id": vacancy.id, "title": vacancy.title, "org_id": vacancy.org_id},
        "timeline": [
            {"id": event.id, "stage": event.stage, "occurred_at": event.created_at}
            for event in db.scalars(
                select(StageEvent)
                .where(StageEvent.pair_cycle_id == cycle.id)
                .order_by(StageEvent.created_at, StageEvent.id)
            )
        ],
        "offers": [
            {
                "id": offer.id,
                "version": offer.version,
                "status": offer.status,
                "expires_at": offer.expires_at,
                "start_at": offer.start_at,
                "terms": decrypt(offer.terms_cipher).decode(),
            }
            for offer in db.scalars(select(Offer).where(Offer.pair_cycle_id == cycle.id))
        ],
        "interviews": [
            {"id": row.id, "start_at": row.start_at, "end_at": row.end_at}
            for row in db.scalars(select(Interview).where(Interview.match_id == match.id))
        ],
    }


def send_message(db: Session, actor: Actor, match_id: str, data) -> dict:
    match, cycle, candidate, vacancy, _ = participant(db, actor, match_id)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    match, cycle, _, _, _ = participant(db, actor, match_id)
    require_version(match, data.expected_version)
    # The API stores text, not executable HTML/markdown. Clients render as text.
    if data.attachment_id:
        attachment = load(db, Attachment, str(data.attachment_id))
        if attachment.match_id != match.id or attachment.uploaded_by != actor.user_id:
            raise AppError(403, "ATTACHMENT_FORBIDDEN", "Attachment is outside this conversation")
    message = Message(
        match_id=match.id,
        sender_user_id=actor.user_id,
        body=html.escape(data.body, quote=True),
        attachment_id=str(data.attachment_id) if data.attachment_id else None,
    )
    db.add(message)
    match.version += 1
    emit(db, actor, "message.sent", message, org_id=vacancy.org_id)
    return {
        "id": message.id,
        "body": message.body,
        "attachment_id": message.attachment_id,
        "sender_user_id": actor.user_id,
        "created_at": message.created_at,
        "match_version": match.version,
    }


def propose_interview(db: Session, actor: Actor, match_id: str, data) -> dict:
    match, _, candidate, vacancy, _ = participant(db, actor, match_id)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    require_version(load(db, MutualMatch, match.id), data.expected_version)
    if any(slot.start_at <= utcnow() for slot in data.slots):
        raise AppError(422, "PAST_INTERVIEW", "Interview options must be in the future")
    proposal = InterviewProposal(
        match_id=match_id,
        initiator_id=actor.user_id,
        slots=[slot.model_dump(mode="json") for slot in data.slots],
        timezone_label=data.timezone_label,
    )
    db.add(proposal)
    match.version += 1
    emit(db, actor, "interview.proposed", proposal, org_id=vacancy.org_id)
    return {
        "id": proposal.id,
        "version": proposal.version,
        "slots": proposal.slots,
        "timezone_label": proposal.timezone_label,
        "status": proposal.status,
    }


def confirm_interview(db: Session, actor: Actor, match_id: str, proposal_id: str, data) -> dict:
    from datetime import datetime

    match, cycle, candidate, vacancy, _ = participant(db, actor, match_id)
    proposal = load(db, InterviewProposal, proposal_id)
    lock_scopes(
        db,
        f"candidate:{candidate.id}",
        f"vacancy:{vacancy.id}",
        f"calendar:{candidate.user_id}",
        f"calendar:{vacancy.owner_user_id}",
    )
    match, cycle, candidate, vacancy, _ = participant(db, actor, match_id)
    proposal = load(db, InterviewProposal, proposal_id)
    require_version(proposal, data.expected_version)
    same_side = (proposal.initiator_id == candidate.user_id) == (actor.user_id == candidate.user_id)
    if proposal.match_id != match_id or proposal.status != "PROPOSED" or same_side:
        raise AppError(
            403, "COUNTERPART_CONFIRMATION_REQUIRED", "The other participant must confirm this proposal"
        )
    if data.slot_index >= len(proposal.slots):
        raise AppError(422, "INVALID_SLOT", "Choose a proposed interview slot")
    slot = proposal.slots[data.slot_index]
    start, end = (
        datetime.fromisoformat(slot["start_at"].replace("Z", "+00:00")),
        datetime.fromisoformat(slot["end_at"].replace("Z", "+00:00")),
    )
    if start <= utcnow():
        raise AppError(409, "SLOT_EXPIRED", "This interview slot has passed")
    conflict = db.scalar(
        select(Interview.id).where(
            (
                (Interview.candidate_user_id == candidate.user_id)
                | (Interview.employer_user_id == vacancy.owner_user_id)
            ),
            Interview.start_at < end,
            Interview.end_at > start,
        )
    )
    if conflict:
        raise AppError(409, "SCHEDULE_CONFLICT", "A participant has an overlapping interview")
    event = Interview(
        proposal_id=proposal.id,
        match_id=match.id,
        candidate_user_id=candidate.user_id,
        employer_user_id=vacancy.owner_user_id,
        start_at=start,
        end_at=end,
    )
    db.add(event)
    proposal.status, proposal.version = "CONFIRMED", proposal.version + 1
    if cycle.state == "MUTUAL_MATCH":
        cycle.state, cycle.version = "INTERVIEWING", cycle.version + 1
        db.add(StageEvent(pair_cycle_id=cycle.id, actor_id=actor.user_id, stage="INTERVIEWING"))
    emit(db, actor, "interview.confirmed", event, org_id=vacancy.org_id)
    return {"id": event.id, "start_at": start, "end_at": end, "status": "CONFIRMED"}


def stage(db: Session, actor: Actor, match_id: str, data) -> dict:
    _, cycle, candidate, vacancy, is_candidate = participant(db, actor, match_id)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    cycle = load(db, PairCycle, cycle.id)
    require_version(cycle, data.expected_version)
    if is_candidate:
        raise AppError(
            403, "EMPLOYER_STAGE_REQUIRED", "Only the authorized employer can advance or reject this process"
        )
    allowed = {
        "MUTUAL_MATCH": {"INTERVIEWING", "CLOSED_REJECTED"},
        "INTERVIEWING": {"CLOSED_REJECTED"},
        "OFFERED": {"CLOSED_REJECTED"},
    }
    if data.stage not in allowed.get(cycle.state, set()):
        raise AppError(409, "INVALID_STAGE", "This process transition is not permitted")
    if data.stage.startswith("CLOSED_"):
        close_cycle(db, actor, cycle, data.stage)
    else:
        cycle.state, cycle.version = data.stage, cycle.version + 1
    event = StageEvent(
        pair_cycle_id=cycle.id,
        actor_id=actor.user_id,
        stage=data.stage,
        source_hash=digest(data.source_reference),
    )
    db.add(event)
    emit(db, actor, "process.stage_changed", event, org_id=vacancy.org_id)
    return {"state": cycle.state, "cycle_version": cycle.version}


def issue_offer(db: Session, actor: Actor, match_id: str, data) -> dict:
    from app.services.pact import signatory

    _, cycle, candidate, vacancy, is_candidate = participant(db, actor, match_id)
    if is_candidate:
        raise AppError(403, "EMPLOYER_ONLY", "An authorized employer must issue an offer")
    signatory(db, actor, vacancy.id)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    cycle, vacancy = load(db, PairCycle, cycle.id), load(db, Vacancy, vacancy.id)
    participant(db, actor, match_id)
    signatory(db, actor, vacancy.id)
    require_version(cycle, data.expected_version)
    if cycle.state != "INTERVIEWING" or vacancy.state != "ACTIVE" or vacancy.openings_remaining <= 0:
        raise AppError(409, "OFFER_NOT_PERMITTED", "Interviewing and an active open role are required")
    if not utcnow() < data.expires_at <= utcnow() + timedelta(days=90) or data.start_at <= utcnow():
        raise AppError(422, "INVALID_OFFER_DATES", "Offer expiry and employment start must be in the future")
    offer = Offer(
        pair_cycle_id=cycle.id,
        issued_by=actor.user_id,
        terms_cipher=encrypt(data.terms),
        expires_at=data.expires_at,
        start_at=data.start_at,
    )
    db.add(offer)
    cycle.state, cycle.version = "OFFERED", cycle.version + 1
    db.add(StageEvent(pair_cycle_id=cycle.id, actor_id=actor.user_id, stage="OFFERED"))
    emit(db, actor, "offer.issued", offer, org_id=vacancy.org_id)
    return {
        "id": offer.id,
        "version": offer.version,
        "status": offer.status,
        "terms": data.terms,
        "expires_at": offer.expires_at,
        "start_at": offer.start_at,
        "cycle_version": cycle.version,
    }


def answer_offer(db: Session, actor: Actor, offer_id: str, expected: int, accept: bool) -> dict:
    offer = load(db, Offer, offer_id)
    cycle = load(db, PairCycle, offer.pair_cycle_id)
    candidate = load(db, Candidate, cycle.candidate_id)
    if candidate.user_id != actor.user_id:
        raise AppError(403, "CANDIDATE_ONLY", "Only the candidate may answer an offer")
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{cycle.vacancy_id}")
    offer, cycle = load(db, Offer, offer.id), load(db, PairCycle, cycle.id)
    require_version(offer, expected)
    if (
        offer.status != "OFFERED"
        or offer.expires_at <= utcnow()
        or cycle.closed_at
        or cycle.state != "OFFERED"
    ):
        raise AppError(409, "OFFER_UNAVAILABLE", "This offer is no longer open")
    offer.status, offer.version = "ACCEPTED" if accept else "DECLINED", offer.version + 1
    if accept:
        cycle.state, cycle.version = "OFFER_ACCEPTED", cycle.version + 1
    else:
        close_cycle(db, actor, cycle, "CLOSED_OFFER_DECLINED")
    db.add(StageEvent(pair_cycle_id=cycle.id, actor_id=actor.user_id, stage=cycle.state))
    emit(db, actor, "offer.accepted" if accept else "offer.declined", offer)
    return {
        "id": offer.id,
        "version": offer.version,
        "status": offer.status,
        "pair_state": cycle.state,
        "notice": "An accepted offer is not a verified employment start",
    }


def report_start(db: Session, actor: Actor, match_id: str, data) -> dict:
    _, cycle, candidate, vacancy, _ = participant(db, actor, match_id)
    lock_scopes(db, f"candidate:{candidate.id}", f"vacancy:{vacancy.id}")
    cycle = load(db, PairCycle, cycle.id)
    require_version(cycle, data.expected_version)
    if cycle.state != "OFFER_ACCEPTED" or data.started_at > utcnow():
        raise AppError(409, "START_NOT_OCCURRED", "An accepted offer and actual past start are required")
    record = EmploymentStart(
        pair_cycle_id=cycle.id,
        reported_by=actor.user_id,
        started_at=data.started_at,
        source_hash=digest(data.source_reference),
    )
    db.add(record)
    emit(db, actor, "employment_start.reported", record, org_id=vacancy.org_id)
    return {"id": record.id, "version": record.version, "verification_state": "PENDING"}


def verify_start(db: Session, actor: Actor, match_id: str, data) -> dict:
    require_platform(actor, "VERIFIER")
    match = load(db, MutualMatch, match_id)
    cycle = load(db, PairCycle, match.pair_cycle_id)
    lock_scopes(db, f"candidate:{cycle.candidate_id}", f"vacancy:{cycle.vacancy_id}")
    cycle, vacancy = load(db, PairCycle, cycle.id), load(db, Vacancy, cycle.vacancy_id)
    record = db.scalar(select(EmploymentStart).where(EmploymentStart.pair_cycle_id == cycle.id))
    if not record:
        raise AppError(404, "START_REPORT_REQUIRED", "Submit an employment start report first")
    require_version(record, data.expected_version)
    candidate = load(db, Candidate, cycle.candidate_id)
    from app.db.models import OrgMember

    if actor.user_id in {record.reported_by, candidate.user_id} or db.scalar(
        select(OrgMember.id).where(
            OrgMember.org_id == vacancy.org_id,
            OrgMember.user_id == actor.user_id,
            OrgMember.status == "ACTIVE",
        )
    ):
        raise AppError(403, "INDEPENDENT_VERIFIER_REQUIRED", "Employment start needs an independent verifier")
    if (
        cycle.state != "OFFER_ACCEPTED"
        or record.verification_state != "PENDING"
        or vacancy.openings_remaining < 1
        or digest(data.corroboration_source) == record.source_hash
    ):
        raise AppError(
            409,
            "START_VERIFICATION_CONFLICT",
            "Independent corroboration and remaining role capacity are required",
        )
    record.verification_state, record.verified_by, record.version = (
        "VERIFIED",
        actor.user_id,
        record.version + 1,
    )
    vacancy.openings_remaining -= 1
    cycle.state, cycle.version = "START_CONFIRMED", cycle.version + 1
    db.add(
        StageEvent(
            pair_cycle_id=cycle.id,
            actor_id=actor.user_id,
            stage="START_CONFIRMED",
            source_hash=digest(data.corroboration_source),
        )
    )
    if vacancy.openings_remaining == 0:
        from app.services.clearing import cancel_vacancy_pending
        from app.services.common import invalidate

        vacancy.state = "FILLED"
        cancel_vacancy_pending(db, actor, vacancy.id, "FILLED")
        invalidate(db, vacancy_id=vacancy.id, reason="FILLED")
    emit(db, actor, "employment_start.verified", record, org_id=vacancy.org_id)
    return {"id": record.id, "verification_state": record.verification_state, "pair_state": cycle.state}
