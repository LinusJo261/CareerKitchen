"""Draft generation must never mutate a candidate before explicit confirmation."""

import json

import httpx
import pytest
from app.db.models import AuditEvent, Candidate, CandidateSkill, IdempotencyRecord, OutboxEvent, RateBucket
from app.schemas.onboarding import OnboardingDraft
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PAYLOAD = {
    "message": "I enjoy Python data pipelines and want to explore analytics engineering.",
    "consent_to_gemini": True,
    "draft": {},
    "history": [],
}
REPLY = "Let's explore the work you enjoy before choosing a role."


def response():
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "reply": REPLY,
                                    "question": {
                                        "field": "headline",
                                        "kind": "preference",
                                        "prompt": "What short headline describes the work you want?",
                                        "skill": None,
                                        "choices": [],
                                    },
                                    "draft": OnboardingDraft(
                                        role_families=["ENGINEERING"], skills=[{"name": "Python"}]
                                    ).model_dump(mode="json"),
                                }
                            )
                        }
                    ]
                },
            }
        ]
    }


def install(market, monkeypatch, handler=None):
    requests = []
    original = httpx.AsyncClient
    monkeypatch.setattr(market.client.app.state.settings, "gemini_api_key", SecretStr("fictional-test-key"))

    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(200, json=response())

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond))
    )
    return requests


def profile_snapshot(market):
    with Session(market.engine) as db:
        return {
            "candidates": [dict(row) for row in db.execute(select(Candidate.__table__)).mappings()],
            "skills": [dict(row) for row in db.execute(select(CandidateSkill.__table__)).mappings()],
        }


def assert_no_chat_writes(market):
    with Session(market.engine) as db:
        for model in (IdempotencyRecord, RateBucket):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "ONBOARDING_ASSISTED")
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.kind == "ONBOARDING_ASSISTED")
            )
            == 0
        )


def test_authenticated_consented_generation_is_idempotent_and_draft_only(market, monkeypatch):
    before = profile_snapshot(market)
    requests = install(market, monkeypatch)
    assert market.client.post("/v1/navigation/onboarding", json=PAYLOAD).status_code == 401
    assert (
        market.call(0, "POST", "/navigation/onboarding", {**PAYLOAD, "consent_to_gemini": False}).status_code
        == 422
    )
    assert not requests
    assert_no_chat_writes(market)
    key = "fictional-onboarding-once"
    first = market.call(0, "POST", "/navigation/onboarding", PAYLOAD, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["ready_for_review"] is False
    assert first.json()["data"]["draft"]["skills"][0]["level"] is None
    assert first.json()["meta"]["resource_version"] == 1
    replay = market.call(0, "POST", "/navigation/onboarding", PAYLOAD, key=key)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()
    assert len(requests) == 1
    assert (
        market.call(
            0, "POST", "/navigation/onboarding", {**PAYLOAD, "message": "a different answer"}, key=key
        ).status_code
        == 409
    )
    assert profile_snapshot(market) == before
    outbound = requests[0].content.decode()
    assert market.users[0].id not in outbound
    assert market.users[0].verified_email not in outbound
    assert market.org.id not in outbound
    assert "Fictional engineering candidate" not in outbound
    with Session(market.engine) as db:
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.kind == "ONBOARDING_ASSISTED"))
        assert event.payload["contract_version"] == 1
        assert event.payload["consent_to_gemini"] is True
        assert PAYLOAD["message"] not in str(event.payload)
        assert REPLY not in str(event.payload)
        assert "draft" not in event.payload
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "ONBOARDING_ASSISTED"))
        audit_values = {column.name: getattr(audit, column.name) for column in AuditEvent.__table__.columns}
        assert PAYLOAD["message"] not in str(audit_values)
        assert REPLY not in str(audit_values)
        record = db.scalar(select(IdempotencyRecord))
        assert REPLY not in record.response_json
        assert PAYLOAD["message"] not in record.request_hash


def test_history_and_edited_draft_are_the_only_user_context_sent(market, monkeypatch):
    requests = install(market, monkeypatch)
    payload = {
        **PAYLOAD,
        "history": [
            {"role": "user", "content": "I dislike onsite roles."},
            {"role": "assistant", "content": "Would remote work fit your preferences?"},
        ],
        "draft": {"work_modes": ["REMOTE"], "skills": [{"name": "Python"}]},
    }
    result = market.call(0, "POST", "/navigation/onboarding", payload)
    assert result.status_code == 200, result.text
    outbound = json.loads(requests[0].content)
    assert outbound["contents"][0] == {"role": "user", "parts": [{"text": payload["history"][0]["content"]}]}
    assert outbound["contents"][1]["role"] == "model"
    context = json.loads(outbound["contents"][2]["parts"][0]["text"])
    assert context["message"] == payload["message"]
    assert context["draft"]["work_modes"] == ["REMOTE"]
    assert set(context) == {"message", "draft"}
    assert "tools" not in outbound


@pytest.mark.parametrize("failure", ["http", "invalid", "timeout"])
def test_provider_failure_rolls_back_and_exact_request_can_retry(market, monkeypatch, failure):
    before = profile_snapshot(market)
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        if count == 1:
            if failure == "http":
                return httpx.Response(503, json={"error": "fictional-test-key private-provider-detail"})
            if failure == "invalid":
                return httpx.Response(200, json={"candidates": []})
            raise httpx.ReadTimeout("fictional-test-key private-provider-detail", request=request)
        return httpx.Response(200, json=response())

    install(market, monkeypatch, respond)
    key = "fictional-onboarding-retry"
    first = market.call(0, "POST", "/navigation/onboarding", PAYLOAD, key=key)
    assert first.status_code == 503, first.text
    assert first.json()["error"]["code"] == "CHAT_UNAVAILABLE"
    assert "fictional-test-key" not in first.text
    assert "private-provider-detail" not in first.text
    assert_no_chat_writes(market)
    assert profile_snapshot(market) == before
    retry = market.call(0, "POST", "/navigation/onboarding", PAYLOAD, key=key)
    assert retry.status_code == 200, retry.text
    assert count == 2
    assert profile_snapshot(market) == before


def test_same_key_is_scoped_to_authenticated_actor(market, monkeypatch):
    requests = install(market, monkeypatch)
    first = market.call(0, "POST", "/navigation/onboarding", PAYLOAD, key="fictional-actor-key")
    second = market.call(1, "POST", "/navigation/onboarding", PAYLOAD, key="fictional-actor-key")
    assert first.status_code == second.status_code == 200
    assert len(requests) == 2
    with Session(market.engine) as db:
        records = list(db.scalars(select(IdempotencyRecord)))
        assert {record.actor_id for record in records} == {market.users[0].id, market.users[1].id}


def test_policy_repair_is_two_provider_calls_but_one_atomic_audited_operation(market, monkeypatch):
    before = profile_snapshot(market)
    generated = response()
    content = json.loads(generated["candidates"][0]["content"]["parts"][0]["text"])
    valid_question = content["question"]
    content["question"] = {
        "field": "role_families",
        "kind": "preference",
        "prompt": "Which role family?",
        "skill": None,
        "choices": [],
    }
    generated["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(content)
    calls = 0

    def respond(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=generated)
        repair = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "reply": "Let's describe the work you want.",
                                        "question": valid_question,
                                    }
                                )
                            }
                        ]
                    },
                }
            ]
        }
        return httpx.Response(200, json=repair)

    install(market, monkeypatch, respond)
    key = "fictional-repaired-operation"
    first = market.call(0, "POST", "/navigation/onboarding", PAYLOAD, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["draft"] == content["draft"]
    assert calls == 2
    replay = market.call(0, "POST", "/navigation/onboarding", PAYLOAD, key=key)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()
    assert calls == 2
    assert profile_snapshot(market) == before
    with Session(market.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "ONBOARDING_ASSISTED")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.kind == "ONBOARDING_ASSISTED")
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
