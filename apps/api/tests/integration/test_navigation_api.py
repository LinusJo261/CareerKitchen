from app.db.models import AuditEvent, OutboxEvent
from app.schemas.navigation import NavigationChatOut, NavigationLink
from sqlalchemy import func, select


def test_navigation_is_authenticated_consented_audited_and_idempotent(market, monkeypatch):
    calls = []

    async def fake(message, settings):
        calls.append(message)
        return NavigationChatOut(
            reply="Open your profile.", links=[NavigationLink(label="Profile", path="/candidate/profile")]
        )

    monkeypatch.setattr("app.api.navigation.navigate", fake)
    assert market.client.post("/v1/navigation/chat", json={}).status_code == 401
    payload = {"message": "Where is my profile?", "consent_to_gemini": True}
    assert (
        market.call(0, "POST", "/navigation/chat", {**payload, "consent_to_gemini": False}).status_code == 422
    )
    key = "navigation-test-key"
    first = market.call(0, "POST", "/navigation/chat", payload, key=key)
    assert first.status_code == 200, first.text
    replay = market.call(0, "POST", "/navigation/chat", payload, key=key)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert calls == [payload["message"]]
    assert (
        market.call(0, "POST", "/navigation/chat", {**payload, "message": "offers"}, key=key).status_code
        == 409
    )
    from sqlalchemy.orm import Session

    with Session(market.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "NAVIGATION_ASSISTED")
            )
            == 1
        )
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.kind == "NAVIGATION_ASSISTED"))
        assert event.payload["consent_to_gemini"] is True
        assert payload["message"] not in str(event.payload)
