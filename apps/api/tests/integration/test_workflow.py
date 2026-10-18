"""Participant-only scheduling, documents, offers and stale role acceptance."""

from dataclasses import replace
from datetime import timedelta

import pytest
from app.core.settings import get_settings
from app.db.models import (
    AuditEvent,
    Candidate,
    DecisionCard,
    InterviewProposal,
    Organization,
    OrgMember,
    OutboxEvent,
    Vacancy,
    VacancyACL,
)
from app.services import clearing, workflow
from app.services.common import utcnow
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def data(response, status=200):
    assert response.status_code == status, response.text
    result = response.json()
    assert result["meta"]["request_id"] and result["meta"]["server_time"]
    return result["data"]


def first_card(market):
    issued = data(
        market.call(
            2,
            "POST",
            "/internal/decisions/issue",
            {
                "candidate_id": market.candidate.id,
                "vacancy_id": market.vacancy.id,
                "role_version": market.vacancy.version,
                "first_mover": "CANDIDATE",
                "human_review_reason": "Fictional authorized introduction for workflow tests.",
            },
        )
    )
    return data(market.call(0, "GET", f"/decisions/{issued['decision_id']}"))


def answer(market, index, card):
    return market.call(
        index,
        "POST",
        f"/decisions/{card['id']}/interested",
        {"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]},
    )


def mutual_match(market):
    first = first_card(market)
    interested = data(answer(market, 0, first))
    assert interested["pair_state"] != "MUTUAL_MATCH"
    with Session(market.engine) as db:
        second_id = db.scalar(
            select(DecisionCard.id).where(DecisionCard.status == "ACTIVE", DecisionCard.side == "EMPLOYER")
        )
    second = data(market.call(1, "GET", f"/decisions/{second_id}"))
    return data(answer(market, 1, second))["match_id"]


def times():
    start = (utcnow() + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
    return [
        {
            "start_at": (start + timedelta(hours=i * 2)).isoformat(),
            "end_at": (start + timedelta(hours=i * 2 + 1)).isoformat(),
        }
        for i in range(2)
    ]


def test_interview_counterpart_confirmation_overlap_and_timezone(market):
    match_id = mutual_match(market)
    path = f"/matches/{match_id}"
    options = times()
    request = {"expected_version": 1, "slots": options, "timezone_label": "America/Los_Angeles"}
    assert (
        market.call(
            0, "POST", path + "/interviews/proposals", {**request, "timezone_label": "Invalid/Timezone"}
        ).status_code
        == 422
    )
    proposal = data(market.call(0, "POST", path + "/interviews/proposals", request))
    assert proposal["status"] == "PROPOSED" and len(proposal["slots"]) == 2
    assert data(market.call(0, "GET", path + "/interviews/proposals"))[0]["can_confirm"] is False
    assert data(market.call(1, "GET", path + "/interviews/proposals"))[0]["can_confirm"] is True
    confirm = path + f"/interviews/{proposal['id']}/confirm"
    assert market.call(0, "POST", confirm, {"expected_version": 1, "slot_index": 0}).status_code == 403
    assert market.call(3, "POST", confirm, {"expected_version": 1, "slot_index": 0}).status_code == 403
    confirmed = data(market.call(1, "POST", confirm, {"expected_version": 1, "slot_index": 0}))
    assert confirmed["status"] == "CONFIRMED"
    assert data(market.call(1, "GET", path + "/interviews/proposals"))[0]["can_confirm"] is False
    assert market.call(1, "POST", confirm, {"expected_version": 1, "slot_index": 0}).status_code == 412
    info = data(market.call(0, "GET", path))
    assert info["state"] == "INTERVIEWING" and len(info["interviews"]) == 1
    other = data(
        market.call(
            1, "POST", path + "/interviews/proposals", {**request, "expected_version": info["version"]}
        )
    )
    conflict = market.call(
        0, "POST", path + f"/interviews/{other['id']}/confirm", {"expected_version": 1, "slot_index": 0}
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "SCHEDULE_CONFLICT"


def test_same_employer_colleague_is_not_the_candidate_counterpart(market, engine):
    match_id = mutual_match(market)
    with Session(engine) as db:
        db.add(OrgMember(org_id=market.org.id, user_id=market.users[3].id, role="RECRUITER"))
        db.add(VacancyACL(vacancy_id=market.vacancy.id, user_id=market.users[3].id, can_review=True))
        db.commit()
    proposal = data(
        market.call(
            1,
            "POST",
            f"/matches/{match_id}/interviews/proposals",
            {"expected_version": 1, "slots": times(), "timezone_label": "UTC"},
        )
    )
    proposals_path = f"/matches/{match_id}/interviews/proposals"
    assert data(market.call(3, "GET", proposals_path))[0]["can_confirm"] is False
    assert data(market.call(1, "GET", proposals_path))[0]["can_confirm"] is False
    assert data(market.call(0, "GET", proposals_path))[0]["can_confirm"] is True
    assert market.call(4, "GET", proposals_path).status_code == 403
    response = market.call(
        3,
        "POST",
        f"/matches/{match_id}/interviews/{proposal['id']}/confirm",
        {"expected_version": 1, "slot_index": 0},
    )
    assert response.status_code == 403


def test_calendar_overlap_checks_participants_across_candidate_and_employer_roles(market):
    first_match = mutual_match(market)
    slots = times()
    proposal = data(
        market.call(
            0,
            "POST",
            f"/matches/{first_match}/interviews/proposals",
            {"expected_version": 1, "slots": slots, "timezone_label": "UTC"},
        )
    )
    data(
        market.call(
            1,
            "POST",
            f"/matches/{first_match}/interviews/{proposal['id']}/confirm",
            {"expected_version": 1, "slot_index": 0},
        )
    )
    # Both people also participate in a distinct organization with their roles reversed.
    with Session(market.engine, expire_on_commit=False) as db:
        candidate = Candidate(
            user_id=market.users[1].id,
            headline="Fictional recruiter seeking a different role",
            state="ACTIVE",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
        )
        org = Organization(
            legal_name="Fictional Second Employer",
            display_name="Fictional Second Employer",
            domain="second-employer.example.invalid",
            created_by=market.users[0].id,
            verification_state="VERIFIED",
        )
        db.add_all([candidate, org])
        db.flush()
        vacancy = Vacancy(
            org_id=org.id,
            owner_user_id=market.users[0].id,
            title="Fictional second engineering role",
            description="A second fictional engineering vacancy for shared calendar testing.",
            role_family="ENGINEERING",
            employment_type="FULL_TIME",
            work_mode="REMOTE",
            pay_min=80000,
            pay_max=120000,
            currency="USD",
            state="ACTIVE",
        )
        db.add(vacancy)
        db.flush()
        db.add(OrgMember(org_id=org.id, user_id=market.users[0].id, role="RECRUITER"))
        db.add(VacancyACL(vacancy_id=vacancy.id, user_id=market.users[0].id, can_review=True))
        db.commit()
    other_market = replace(
        market,
        users=[market.users[1], market.users[0], *market.users[2:]],
        candidate=candidate,
        org=org,
        vacancy=vacancy,
    )
    other_match = mutual_match(other_market)
    proposal = data(
        other_market.call(
            0,
            "POST",
            f"/matches/{other_match}/interviews/proposals",
            {"expected_version": 1, "slots": slots, "timezone_label": "UTC"},
        )
    )
    response = other_market.call(
        1,
        "POST",
        f"/matches/{other_match}/interviews/{proposal['id']}/confirm",
        {"expected_version": 1, "slot_index": 0},
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "SCHEDULE_CONFLICT"


def test_withdrawal_prevents_pending_interview_confirmation(market):
    match_id = mutual_match(market)
    proposal = data(
        market.call(
            0,
            "POST",
            f"/matches/{match_id}/interviews/proposals",
            {"expected_version": 1, "slots": times(), "timezone_label": "UTC"},
        )
    )
    info = data(market.call(0, "GET", f"/matches/{match_id}"))
    data(market.call(0, "POST", f"/matches/{match_id}/withdraw", {"expected_version": info["cycle_version"]}))
    assert (
        market.call(
            1,
            "POST",
            f"/matches/{match_id}/interviews/{proposal['id']}/confirm",
            {"expected_version": 1, "slot_index": 0},
        ).status_code
        == 403
    )


def test_interview_proposal_rechecks_employer_authority_after_lock(market, monkeypatch):
    match_id = mutual_match(market)
    original_lock = workflow.lock_scopes

    def revoke_then_lock(db, *keys):
        with Session(market.engine) as other:
            for member in other.scalars(select(OrgMember).where(OrgMember.user_id == market.users[1].id)):
                member.status = "REVOKED"
            other.commit()
        original_lock(db, *keys)

    monkeypatch.setattr(workflow, "lock_scopes", revoke_then_lock)
    response = market.call(
        1,
        "POST",
        f"/matches/{match_id}/interviews/proposals",
        {"expected_version": 1, "slots": times(), "timezone_label": "UTC"},
    )
    assert response.status_code == 403
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(InterviewProposal)) == 0


def test_message_attachment_is_private_scanned_and_block_revokes_access(market, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "local_storage_dir", tmp_path)
    match_id = mutual_match(market)
    path = f"/matches/{match_id}/attachments"
    body = b"Fictional private interview preparation notes."
    uploaded = data(market.call(0, "POST", path, files={"file": ("notes.txt", body, "text/plain")}))
    assert uploaded["size"] == len(body) and len(uploaded["sha256"]) == 64
    assert "object_ref" not in uploaded
    link = path + f"/{uploaded['id']}"
    download = market.call(1, "GET", link)
    assert download.status_code == 200 and download.content == body
    assert download.headers["cache-control"] == "no-store"
    assert market.call(3, "GET", link).status_code == 403
    assert market.call(3, "POST", path, files={"file": ("notes.txt", body, "text/plain")}).status_code == 403
    assert (
        market.call(
            0, "POST", path, files={"file": ("malicious.exe", b"MZ executable", "application/x-msdownload")}
        ).status_code
        == 415
    )
    note = data(
        market.call(
            0,
            "POST",
            f"/matches/{match_id}/messages",
            {"expected_version": 1, "body": "Fictional preparation notes", "attachment_id": uploaded["id"]},
        )
    )
    assert note["attachment_id"] == uploaded["id"]
    assert (
        market.call(
            1,
            "POST",
            f"/matches/{match_id}/messages",
            {
                "expected_version": note["match_version"],
                "body": "Cannot claim another participant upload",
                "attachment_id": uploaded["id"],
            },
        ).status_code
        == 403
    )
    data(market.call(0, "POST", "/candidates/me/blocks", {"org_id": market.org.id}))
    assert market.call(1, "GET", link).status_code == 403
    assert (
        market.call(
            1,
            "POST",
            f"/matches/{match_id}/messages",
            {"expected_version": note["match_version"], "body": "Blocked conversation"},
        ).status_code
        == 403
    )


def test_offer_authority_candidate_ownership_and_nonbinding_pact(market, engine):
    match_id = mutual_match(market)
    path = f"/matches/{match_id}"
    current = data(market.call(1, "GET", path))
    assert current["start_report"] is None
    stage = data(
        market.call(
            1,
            "POST",
            path + "/stages",
            {
                "expected_version": current["cycle_version"],
                "stage": "INTERVIEWING",
                "source_reference": "Fictional human interview completed",
            },
        )
    )
    request = {
        "expected_version": stage["cycle_version"],
        "terms": "Fictional employer written offer for this exact engineering role at USD100000 annually.",
        "expires_at": (utcnow() + timedelta(days=4)).isoformat(),
        "start_at": (utcnow() + timedelta(days=14)).isoformat(),
        "affirm_human_authority": True,
    }
    assert market.call(0, "POST", path + "/offers", request).status_code == 403
    assert market.call(3, "POST", path + "/offers", request).status_code == 403
    with Session(engine) as db:
        member = db.scalar(
            select(OrgMember).where(
                OrgMember.org_id == market.org.id,
                OrgMember.user_id == market.users[1].id,
                OrgMember.role == "AUTHORIZED_SIGNATORY",
            )
        )
        member.status = "REVOKED"
        db.commit()
    assert market.call(1, "POST", path + "/offers", request).status_code == 403
    with Session(engine) as db:
        member = db.scalar(
            select(OrgMember).where(
                OrgMember.org_id == market.org.id,
                OrgMember.user_id == market.users[1].id,
                OrgMember.role == "AUTHORIZED_SIGNATORY",
            )
        )
        member.status = "ACTIVE"
        db.commit()
    offer = data(market.call(1, "POST", path + "/offers", request))
    assert offer["status"] == "OFFERED"
    assert market.call(1, "POST", f"/offers/{offer['id']}/accept", {"expected_version": 1}).status_code == 403
    assert market.call(3, "GET", f"/offers/{offer['id']}").status_code == 403
    accepted = data(market.call(0, "POST", f"/offers/{offer['id']}/accept", {"expected_version": 1}))
    assert accepted["pair_state"] == "OFFER_ACCEPTED"
    assert data(market.call(0, "GET", path))["state"] == "OFFER_ACCEPTED"


def test_closed_role_cancelled_decision_cannot_be_answered_with_old_token(market):
    card = first_card(market)
    closed = data(market.call(1, "POST", f"/vacancies/{market.vacancy.id}/close", {"expected_version": 1}))
    assert closed["state"] == "CLOSED"
    response = answer(market, 0, card)
    assert response.status_code in {409, 412}
    current = data(market.call(0, "GET", f"/decisions/{card['id']}"))
    assert current["status"] == "CANCELLED" and current["decision_token"] is None


def test_offer_replay_rechecks_signatory_authority(market):
    match_id = mutual_match(market)
    path = f"/matches/{match_id}"
    current = data(market.call(1, "GET", path))
    stage = data(
        market.call(
            1,
            "POST",
            path + "/stages",
            {
                "expected_version": current["cycle_version"],
                "stage": "INTERVIEWING",
                "source_reference": "Fictional completed interview for replay authorization test",
            },
        )
    )
    request = {
        "expected_version": stage["cycle_version"],
        "terms": "Fictional written employer offer at USD100000 annually.",
        "expires_at": (utcnow() + timedelta(days=4)).isoformat(),
        "start_at": (utcnow() + timedelta(days=14)).isoformat(),
        "affirm_human_authority": True,
    }
    key = "offer-signatory-replay"
    first = market.call(1, "POST", path + "/offers", request, key=key)
    assert first.status_code == 200, first.text
    repeated = market.call(1, "POST", path + "/offers", request, key=key)
    assert repeated.status_code == 200 and repeated.json() == first.json()
    with Session(market.engine) as db:
        member = db.scalar(
            select(OrgMember).where(
                OrgMember.org_id == market.org.id,
                OrgMember.user_id == market.users[1].id,
                OrgMember.role == "AUTHORIZED_SIGNATORY",
            )
        )
        member.status = "REVOKED"
        db.commit()
    repeated = market.call(1, "POST", path + "/offers", request, key=key)
    assert repeated.status_code == 403, repeated.text


@pytest.mark.parametrize("openings", [1, 2])
def test_verified_start_versions_and_audits_vacancy_capacity(market, openings):
    with Session(market.engine) as db:
        vacancy = db.get(Vacancy, market.vacancy.id)
        vacancy.openings_total = vacancy.openings_remaining = openings
        db.commit()
    match_id = mutual_match(market)
    path = f"/matches/{match_id}"
    current = data(market.call(1, "GET", path))
    stage = data(
        market.call(
            1,
            "POST",
            path + "/stages",
            {
                "expected_version": current["cycle_version"],
                "stage": "INTERVIEWING",
                "source_reference": "Fictional completed interview",
            },
        )
    )
    offer = data(
        market.call(
            1,
            "POST",
            path + "/offers",
            {
                "expected_version": stage["cycle_version"],
                "terms": "Fictional written engineering offer for USD 100000 per year.",
                "expires_at": (utcnow() + timedelta(days=7)).isoformat(),
                "start_at": (utcnow() + timedelta(days=14)).isoformat(),
                "affirm_human_authority": True,
            },
        )
    )
    data(market.call(0, "POST", f"/offers/{offer['id']}/accept", {"expected_version": offer["version"]}))
    current = data(market.call(0, "GET", path))
    report = data(
        market.call(
            0,
            "POST",
            path + "/starts/report",
            {
                "expected_version": current["cycle_version"],
                "started_at": (utcnow() - timedelta(hours=1)).isoformat(),
                "source_reference": "Fictional candidate report of actual employment start",
            },
        )
    )
    candidate_view = data(market.call(0, "GET", path))
    employer_view = data(market.call(1, "GET", path))
    assert candidate_view["state"] == "OFFER_ACCEPTED"
    assert candidate_view["start_report"] == employer_view["start_report"]
    assert candidate_view["start_report"]["id"] == report["id"]
    assert candidate_view["start_report"]["version"] == report["version"]
    assert candidate_view["start_report"]["verification_state"] == "PENDING"
    assert set(candidate_view["start_report"]) == {"id", "version", "verification_state", "started_at"}
    assert market.call(3, "GET", path).status_code == 403
    with Session(market.engine) as db:
        other_candidate = Candidate(
            user_id=market.users[4].id,
            headline="Fictional pending introduction",
            state="ACTIVE",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
        )
        db.add(other_candidate)
        db.flush()
        pending = clearing.issue_first(
            db, market.actor(2), other_candidate.id, market.vacancy.id, 1, "CANDIDATE"
        )
        pending_id = pending.id
        db.commit()
    body = {
        "expected_version": report["version"],
        "corroboration_source": "Independent fictional employment start corroboration",
        "independently_checked": True,
    }
    verified = market.call(2, "POST", path + "/starts/verify", body, key="verified-start-capacity")
    assert data(verified)["pair_state"] == "START_CONFIRMED"
    verified_view = data(market.call(0, "GET", path))["start_report"]
    assert verified_view["verification_state"] == "VERIFIED"
    assert verified_view["version"] == report["version"] + 1
    replay = market.call(2, "POST", path + "/starts/verify", body, key="verified-start-capacity")
    assert data(replay) == data(verified)
    assert replay.headers["Idempotency-Replayed"] == "true"
    vacancy = data(market.call(1, "GET", f"/vacancies/{market.vacancy.id}"))
    assert vacancy["version"] == 2
    assert vacancy["openings_remaining"] == openings - 1
    assert vacancy["state"] == ("FILLED" if openings == 1 else "ACTIVE")
    assert vacancy["terms_hash"] != market.vacancy.terms_hash
    stale = market.call(1, "POST", f"/vacancies/{market.vacancy.id}/close", {"expected_version": 1})
    assert stale.status_code == 412
    with Session(market.engine) as db:
        assert db.get(DecisionCard, pending_id).status == "CANCELLED"
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.kind == "vacancy.capacity_changed"))
        assert event.aggregate_id == market.vacancy.id and event.payload["version"] == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "vacancy.capacity_changed")
            )
            == 1
        )
