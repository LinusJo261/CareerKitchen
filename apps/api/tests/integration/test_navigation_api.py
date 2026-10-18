import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from app.core.auth import mint_dev_token
from app.db.models import AuditEvent, IdempotencyRecord, OutboxEvent, RateBucket, RevokedSession, User
from app.services.common import utcnow
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

PAYLOAD = {"message": "Where is my profile?", "consent_to_gemini": True}
REPLY = "Open your candidate profile to update your experience and job preferences."


def gemini_response(reply=REPLY, topics=None):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [{"text": json.dumps({"reply": reply, "topics": topics or ["profile"]})}]
                },
            }
        ]
    }


def install_gemini(market, monkeypatch, handler=None):
    """Exercise the actual HTTP integration while keeping Google calls deterministic."""
    requests = []
    original = httpx.AsyncClient
    monkeypatch.setattr(market.client.app.state.settings, "gemini_api_key", SecretStr("test-key"))

    def respond(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "test-key"
        return handler(request) if handler else httpx.Response(200, json=gemini_response())

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond))
    )
    return requests


def assert_no_navigation_writes(market):
    with Session(market.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "NAVIGATION_ASSISTED")
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.kind == "NAVIGATION_ASSISTED")
            )
            == 0
        )
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
        assert db.scalar(select(func.count()).select_from(RateBucket)) == 0


def test_navigation_is_authenticated_consented_audited_and_idempotent(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    assert market.client.post("/v1/navigation/chat", json=PAYLOAD).status_code == 401
    assert (
        market.call(0, "POST", "/navigation/chat", {**PAYLOAD, "consent_to_gemini": False}).status_code == 422
    )
    assert not requests
    assert_no_navigation_writes(market)

    key = "navigation-test-key"
    first = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert first.status_code == 200, first.text
    assert first.json()["data"] == {
        "reply": REPLY,
        "links": [{"label": "Candidate profile", "path": "/candidate/profile"}],
        "version": 1,
    }
    assert first.json()["meta"]["resource_version"] == 1
    replay = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()
    assert len(requests) == 1
    assert (
        market.call(0, "POST", "/navigation/chat", {**PAYLOAD, "message": "offers"}, key=key).status_code
        == 409
    )
    assert len(requests) == 1

    with Session(market.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "NAVIGATION_ASSISTED")
            )
            == 1
        )
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.kind == "NAVIGATION_ASSISTED"))
        assert event.payload["consent_to_gemini"] is True
        assert event.payload["contract_version"] == 1
        assert PAYLOAD["message"] not in str(event.payload)
        assert REPLY not in str(event.payload)
        record = db.scalar(select(IdempotencyRecord))
        assert REPLY not in record.response_json
        assert PAYLOAD["message"] not in record.request_hash
        assert db.get(RateBucket, f"write:{market.users[0].id}").count == 1


@pytest.mark.parametrize("consent", [None, False, 1, "true"])
def test_invalid_consent_never_calls_gemini_or_persists_changes(market, monkeypatch, consent):
    requests = install_gemini(market, monkeypatch)
    response = market.call(0, "POST", "/navigation/chat", {**PAYLOAD, "consent_to_gemini": consent})
    assert response.status_code == 422
    assert not requests
    assert_no_navigation_writes(market)


def test_missing_idempotency_key_never_calls_gemini_or_persists_changes(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    user = market.users[0]
    response = market.client.post(
        "/v1/navigation/chat",
        json=PAYLOAD,
        headers={"Authorization": "Bearer " + mint_dev_token(user.id, email=user.verified_email)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert not requests
    assert_no_navigation_writes(market)


def test_history_reaches_gemini_without_account_context_or_audit_content(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    history = [
        {"role": "user", "content": "I want to find opportunities."},
        {"role": "assistant", "content": "Complete your profile first."},
    ]
    payload = {**PAYLOAD, "history": history}
    key = "navigation-history-key"
    result = market.call(0, "POST", "/navigation/chat", payload, key=key)
    assert result.status_code == 200, result.text
    assert json.loads(requests[0].content)["contents"] == [
        {"role": "user", "parts": [{"text": history[0]["content"]}]},
        {"role": "model", "parts": [{"text": history[1]["content"]}]},
        {"role": "user", "parts": [{"text": PAYLOAD["message"]}]},
    ]
    outbound = requests[0].content.decode()
    assert market.users[0].id not in outbound
    assert market.users[0].verified_email not in outbound
    assert market.org.id not in outbound
    assert "Fictional engineering candidate" not in outbound
    assert "70000" not in outbound
    changed_history = [history[0], {**history[1], "content": "Review your preferences first."}]
    assert (
        market.call(
            0, "POST", "/navigation/chat", {**payload, "history": changed_history}, key=key
        ).status_code
        == 409
    )
    assert len(requests) == 1
    with Session(market.engine) as db:
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.kind == "NAVIGATION_ASSISTED"))
        for turn in history:
            assert turn["content"] not in str(event.payload)
        assert "history" not in event.payload


def test_same_key_for_different_actors_has_independent_responses(market, monkeypatch):
    replies = iter(["First fictional actor's generated reply.", "Second fictional actor's generated reply."])
    requests = install_gemini(
        market, monkeypatch, lambda request: httpx.Response(200, json=gemini_response(next(replies)))
    )
    key = "navigation-shared-key"
    first = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    second = market.call(1, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["reply"] != second.json()["data"]["reply"]
    assert "Idempotency-Replayed" not in second.headers
    assert market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key).json() == first.json()
    assert market.call(1, "POST", "/navigation/chat", PAYLOAD, key=key).json() == second.json()
    assert len(requests) == 2
    with Session(market.engine) as db:
        records = list(db.scalars(select(IdempotencyRecord)))
        assert {record.actor_id for record in records} == {market.users[0].id, market.users[1].id}
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "NAVIGATION_ASSISTED")))
        assert {event.actor_id for event in events} == {market.users[0].id, market.users[1].id}


def test_longest_generated_reply_can_be_used_in_next_api_request(market, monkeypatch):
    longest_reply = "x" * 4000
    requests = install_gemini(
        market, monkeypatch, lambda request: httpx.Response(200, json=gemini_response(reply=longest_reply))
    )
    first = market.call(0, "POST", "/navigation/chat", PAYLOAD)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["reply"] == longest_reply
    follow_up = {
        "message": "What should I do next?",
        "consent_to_gemini": True,
        "history": [
            {"role": "user", "content": PAYLOAD["message"]},
            {"role": "assistant", "content": first.json()["data"]["reply"]},
        ],
    }
    second = market.call(0, "POST", "/navigation/chat", follow_up)
    assert second.status_code == 200, second.text
    assert len(requests) == 2
    assert json.loads(requests[1].content)["contents"][1]["parts"][0]["text"] == longest_reply


@pytest.mark.parametrize("failure", ["http", "invalid", "timeout"])
def test_provider_failure_rolls_back_and_same_key_can_be_retried(market, monkeypatch, failure):
    attempts = 0

    def respond(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if failure == "http":
                return httpx.Response(429, json={"error": {"message": "test-key secret-provider-detail"}})
            if failure == "invalid":
                return httpx.Response(200, json=gemini_response(reply=""))
            raise httpx.ReadTimeout("test-key secret-provider-detail", request=request)
        return httpx.Response(200, json=gemini_response())

    install_gemini(market, monkeypatch, respond)
    key = "navigation-retry-key"
    first = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert first.status_code == 503, first.text
    assert first.json()["error"]["code"] == "CHAT_UNAVAILABLE"
    assert "test-key" not in first.text
    assert "secret-provider-detail" not in first.text
    assert_no_navigation_writes(market)
    retry = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert retry.status_code == 200, retry.text
    assert "Idempotency-Replayed" not in retry.headers
    assert attempts == 2
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "NAVIGATION_ASSISTED")
            )
            == 1
        )


def test_missing_gemini_key_returns_actionable_failure_without_writes(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    monkeypatch.setattr(market.client.app.state.settings, "gemini_api_key", SecretStr(""))
    response = market.call(0, "POST", "/navigation/chat", PAYLOAD)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_UNAVAILABLE"
    assert not requests
    assert_no_navigation_writes(market)


def test_missing_encryption_key_does_not_send_message_to_gemini(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    monkeypatch.setattr(market.client.app.state.settings, "encryption_key", SecretStr(""))
    response = market.call(0, "POST", "/navigation/chat", PAYLOAD)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_UNAVAILABLE"
    assert not requests
    assert_no_navigation_writes(market)


def test_rate_limit_precedes_provider_and_replay_is_free(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    monkeypatch.setattr(market.client.app.state.settings, "rate_limit_per_minute", 1)
    key = "navigation-rate-key"
    first = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert first.status_code == 200, first.text
    replay = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    limited = market.call(0, "POST", "/navigation/chat", PAYLOAD)
    assert limited.status_code == 429, limited.text
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert len(requests) == 1
    assert market.call(1, "POST", "/navigation/chat", PAYLOAD).status_code == 200
    assert len(requests) == 2


def test_suspended_actor_cannot_replay_prior_reply(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    key = "navigation-suspended-key"
    assert market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key).status_code == 200
    with Session(market.engine) as db:
        db.get(User, market.users[0].id).status = "SUSPENDED"
        db.commit()
    response = market.call(0, "POST", "/navigation/chat", PAYLOAD, key=key)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"
    assert REPLY not in response.text
    assert len(requests) == 1


def test_revoked_session_cannot_replay_prior_reply(market, monkeypatch):
    requests = install_gemini(market, monkeypatch)
    session_id = uuid4()
    user = market.users[0]
    token = mint_dev_token(user.id, email=user.verified_email, session_id=session_id)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "navigation-revoked-key"}
    first = market.client.post("/v1/navigation/chat", json=PAYLOAD, headers=headers)
    assert first.status_code == 200, first.text
    with Session(market.engine) as db:
        db.add(RevokedSession(id=str(session_id), user_id=user.id, expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
    response = market.client.post("/v1/navigation/chat", json=PAYLOAD, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_REVOKED"
    assert REPLY not in response.text
    assert len(requests) == 1
