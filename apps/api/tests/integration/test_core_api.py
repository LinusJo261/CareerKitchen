from datetime import timedelta
from uuid import uuid4

from app.db.models import DecisionCard, Exposure, MutualMatch, OutboxEvent, PairCycle
from app.services import clearing
from app.services.common import utcnow
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def issue(market, side="CANDIDATE"):
    result = market.call(
        2,
        "POST",
        "/internal/decisions/issue",
        {
            "candidate_id": market.candidate.id,
            "vacancy_id": market.vacancy.id,
            "role_version": market.vacancy.version,
            "first_mover": side,
            "human_review_reason": "Fictional test reviewed pair",
        },
    )
    assert result.status_code == 200, result.text
    return result.json()["data"]["decision_id"]


def get_card(market, card_id, index=0):
    result = market.call(index, "GET", f"/decisions/{card_id}")
    assert result.status_code == 200, result.text
    return result.json()["data"]


def answer(market, card_id, index=0, action="interested", key=None):
    card = get_card(market, card_id, index)
    return market.call(
        index,
        "POST",
        f"/decisions/{card_id}/{action}",
        {"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]},
        key=key,
    )


def mutual(market, side="CANDIDATE"):
    card_id = issue(market, side)
    first = answer(market, card_id, 0 if side == "CANDIDATE" else 1)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["pair_state"] != "MUTUAL_MATCH"
    with Session(market.engine) as db:
        next_card = db.scalar(select(DecisionCard).where(DecisionCard.status == "ACTIVE"))
        next_id = next_card.id
    second = answer(market, next_id, 1 if side == "CANDIDATE" else 0)
    assert second.status_code == 200, second.text
    assert second.json()["data"]["pair_state"] == "MUTUAL_MATCH"
    return second.json()["data"]["match_id"]


def test_health_and_auth(market):
    assert market.client.get("/v1/health").status_code == 200
    assert market.client.get("/v1/candidates/me").status_code == 401
    assert market.call(0, "GET", "/sessions/me").json()["data"]["platform_roles"] == []
    assert market.call(0, "GET", "/candidates/me").json()["data"]["compensation_floor"] == "70000"


def test_candidate_first_double_opt_in_and_tenant_chat(market):
    match_id = mutual(market)
    result = market.call(
        0,
        "POST",
        f"/matches/{match_id}/messages",
        {"expected_version": 1, "body": "<script>test</script> Hello"},
    )
    assert result.status_code == 200, result.text
    assert "<script>" not in result.json()["data"]["body"]
    assert market.call(3, "GET", f"/matches/{match_id}").status_code == 403
    assert (
        market.call(
            3, "POST", f"/matches/{match_id}/messages", {"expected_version": 2, "body": "Cross tenant"}
        ).status_code
        == 403
    )
    assert len(market.call(1, "GET", f"/matches/{match_id}/messages").json()["data"]) == 1
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 1
        assert (
            db.scalar(select(func.count()).select_from(Exposure).where(Exposure.recipient_side == "EMPLOYER"))
            == 1
        )


def test_employer_first_and_private_floor(market):
    card_id = issue(market, "EMPLOYER")
    employer_card = get_card(market, card_id, 1)
    assert "compensation_floor" not in str(employer_card)
    assert "70000" not in str(employer_card)
    result = answer(market, card_id, 1)
    assert result.json()["data"]["pair_state"] == "CANDIDATE_DECISION_REQUIRED"
    with Session(market.engine) as db:
        card = db.scalar(select(DecisionCard).where(DecisionCard.side == "CANDIDATE"))
        candidate_id = card.id
    assert answer(market, candidate_id, 0, "pass").json()["data"]["pair_state"] == "CLOSED_CANDIDATE_PASS"
    assert market.call(0, "GET", f"/matches/{uuid4()}/messages").status_code == 404
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0


def test_idempotency_replay_and_payload_conflict(market):
    card_id = issue(market)
    card = get_card(market, card_id)
    body = {"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]}
    first = market.call(0, "POST", f"/decisions/{card_id}/interested", body, key="same-key-123")
    second = market.call(0, "POST", f"/decisions/{card_id}/interested", body, key="same-key-123")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    body["expected_cycle_version"] += 1
    assert (
        market.call(0, "POST", f"/decisions/{card_id}/interested", body, key="same-key-123").status_code
        == 409
    )
    with Session(market.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.kind == "decision.interested")
            )
            == 1
        )


def test_expiry_pass_stale_and_rollback(market):
    card_id = issue(market)
    card = get_card(market, card_id)
    body = {"expected_cycle_version": card["cycle_version"] + 1, "decision_token": card["decision_token"]}
    assert market.call(0, "POST", f"/decisions/{card_id}/interested", body).status_code == 412
    body["expected_cycle_version"] -= 1
    with Session(market.engine) as db:
        db.get(DecisionCard, card_id).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert (
        market.call(0, "POST", f"/decisions/{card_id}/interested", body).json()["error"]["code"]
        == "EXPIRED_DECISION"
    )
    with Session(market.engine) as db:
        assert db.get(DecisionCard, card_id).status == "ACTIVE"
        clearing.expire_due(db, market.actor(2))
        db.commit()
        assert db.get(DecisionCard, card_id).status == "EXPIRED"


def test_closed_role_cancels_and_prevents_new_cycles(market):
    card_id = issue(market)
    assert (
        market.call(
            1, "POST", f"/vacancies/{market.vacancy.id}/close", {"expected_version": market.vacancy.version}
        ).status_code
        == 200
    )
    card = get_card(market, card_id)
    assert card["status"] == "CANCELLED"
    assert card["pair_state"] == "CLOSED_JOB_CLOSED"


def test_candidate_pause_and_block(market):
    card_id = issue(market)
    result = market.call(0, "POST", "/candidates/me/pause", {"expected_version": market.candidate.version})
    assert result.status_code == 200, result.text
    assert get_card(market, card_id)["status"] == "CANCELLED"
    assert market.call(0, "POST", "/candidates/me/blocks", {"org_id": market.org.id}).status_code == 200


def test_reconcile_actual_persistent_heuristic_no_probabilities(market):
    result = market.call(2, "POST", "/internal/reconcile")
    assert result.status_code == 200, result.text
    assert len(result.json()["data"]["issued"]) == 1
    metrics = market.call(1, "GET", f"/vacancies/{market.vacancy.id}/metrics").json()["data"]
    assert metrics["n_delivered"] == 0
    assert metrics["candidate_attempts"] == 1
    with Session(market.engine) as db:
        cycle = db.scalar(select(PairCycle))
        assert cycle.score_trace["estimate_kind"] == "NONPROBABILISTIC"


def test_offer_accepted_is_not_started(market):
    match_id = mutual(market)
    cycle_version = market.call(1, "GET", f"/matches/{match_id}").json()["data"]["cycle_version"]
    stage = market.call(
        1,
        "POST",
        f"/matches/{match_id}/stages",
        {
            "expected_version": cycle_version,
            "stage": "INTERVIEWING",
            "source_reference": "Fictional manual interview",
        },
    )
    assert stage.status_code == 200, stage.text
    offer = market.call(
        1,
        "POST",
        f"/matches/{match_id}/offers",
        {
            "expected_version": stage.json()["data"]["cycle_version"],
            "terms": "Fictional written offer: engineering position at USD 100000 per year.",
            "expires_at": (utcnow() + timedelta(days=7)).isoformat(),
            "start_at": (utcnow() + timedelta(days=14)).isoformat(),
            "affirm_human_authority": True,
        },
    )
    assert offer.status_code == 200, offer.text
    accepted = market.call(0, "POST", f"/offers/{offer.json()['data']['id']}/accept", {"expected_version": 1})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["pair_state"] == "OFFER_ACCEPTED"
    info = market.call(0, "GET", f"/matches/{match_id}").json()["data"]
    report = market.call(
        0,
        "POST",
        f"/matches/{match_id}/starts/report",
        {
            "expected_version": info["cycle_version"],
            "started_at": (utcnow() - timedelta(hours=1)).isoformat(),
            "source_reference": "Fictional candidate reported completed start",
        },
    )
    assert report.status_code == 200, report.text
    verify = market.call(
        2,
        "POST",
        f"/matches/{match_id}/starts/verify",
        {
            "expected_version": report.json()["data"]["version"],
            "corroboration_source": "Independent fictional corroboration reviewed by test verifier",
            "independently_checked": True,
        },
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["data"]["pair_state"] == "START_CONFIRMED"


def test_forged_role_extra_fields_origin_idem_validation(market):
    assert market.call(0, "POST", "/internal/reconcile").status_code == 403
    assert (
        market.call(
            1,
            "POST",
            f"/organizations/{market.org.id}/members/invite",
            {"email": "fake@example.invalid", "role": "AUTHORIZED_SIGNATORY"},
        ).status_code
        == 422
    )
    assert (
        market.call(
            0,
            "POST",
            "/candidates/me/pause",
            {"expected_version": 1},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        market.call(
            0, "POST", "/candidates/me/pause", {"expected_version": 1}, headers={"Idempotency-Key": ""}
        ).status_code
        == 422
    )
    assert (
        market.call(
            0, "POST", "/candidates/me/pause", {"expected_version": 1}, headers={"If-Match": '"2"'}
        ).status_code
        == 412
    )


def test_export_report_and_notifications_acl(market):
    assert market.call(0, "POST", "/privacy/export").status_code == 202
    assert market.call(0, "GET", "/privacy/export").json()["data"]["status"] == "QUEUED"
    report = market.call(
        0,
        "POST",
        "/reports",
        {
            "entity_type": "VACANCY",
            "entity_id": market.vacancy.id,
            "reason": "CORRECTION",
            "description": "Fictional report requesting correction of role description",
        },
    )
    assert report.status_code == 200, report.text
    assert market.call(0, "GET", "/admin/reports").status_code == 403
    assert len(market.call(2, "GET", "/admin/reports").json()["data"]) == 1
    assert market.call(3, "GET", f"/vacancies/{market.vacancy.id}/metrics").status_code == 403


def test_logout_revokes_existing_token(market):
    from app.core.auth import mint_dev_token

    token = mint_dev_token(market.users[0].id)
    headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "logout-key-1"}
    assert market.client.post("/v1/sessions/logout", headers=headers).status_code == 200
    assert market.client.get("/v1/sessions/me", headers=headers).status_code == 401
