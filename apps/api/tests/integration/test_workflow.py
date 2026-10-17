"""Participant-only scheduling, documents, offers and stale role acceptance."""

from datetime import timedelta

from app.core.settings import get_settings
from app.db.models import DecisionCard, OrgMember, VacancyACL
from app.services.common import utcnow
from sqlalchemy import select
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
    confirm = path + f"/interviews/{proposal['id']}/confirm"
    assert market.call(0, "POST", confirm, {"expected_version": 1, "slot_index": 0}).status_code == 403
    assert market.call(3, "POST", confirm, {"expected_version": 1, "slot_index": 0}).status_code == 403
    confirmed = data(market.call(1, "POST", confirm, {"expected_version": 1, "slot_index": 0}))
    assert confirmed["status"] == "CONFIRMED"
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
    response = market.call(
        3,
        "POST",
        f"/matches/{match_id}/interviews/{proposal['id']}/confirm",
        {"expected_version": 1, "slot_index": 0},
    )
    assert response.status_code == 403


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
