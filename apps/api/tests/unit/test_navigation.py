import asyncio
import json

import httpx
import pytest
from app.core.errors import AppError
from app.core.settings import Settings
from app.integrations.gemini_navigation import navigate
from app.schemas.navigation import NavigationChatIn


def test_consent_and_bounded_message():
    from pydantic import ValidationError

    for body in (
        {"message": "help"},
        {"message": "help", "consent_to_gemini": False},
        {"message": " " * 5, "consent_to_gemini": True},
        {"message": "x" * 2001, "consent_to_gemini": True},
    ):
        with pytest.raises(ValidationError):
            NavigationChatIn.model_validate(body)


def test_disabled_without_key():
    with pytest.raises(AppError) as error:
        asyncio.run(navigate("help", Settings(gemini_api_key="")))
    assert error.value.code == "CHAT_UNAVAILABLE"


@pytest.mark.parametrize("topics", [["profile", "privacy"], [], ["https://evil.invalid"], ["profile"] * 4])
def test_provider_output_is_allowlisted(monkeypatch, topics):
    original = httpx.AsyncClient

    def respond(request):
        assert request.headers["x-goog-api-key"] == "test-key"
        assert request.url.host == "generativelanguage.googleapis.com"
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][0]["text"] == "Where is my profile?"
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"topics": topics})}]}}
                ]
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond))
    )
    if len(topics) > 3 or any(topic.startswith("https:") for topic in topics):
        with pytest.raises(AppError):
            asyncio.run(navigate("Where is my profile?", Settings(gemini_api_key="test-key")))
    else:
        result = asyncio.run(navigate("Where is my profile?", Settings(gemini_api_key="test-key")))
        assert len(result.links) == len(topics)
        assert all(link.path.startswith("/candidate/") for link in result.links)


@pytest.mark.parametrize(
    "status,body", [(429, {}), (500, {}), (200, {}), (200, {"candidates": [{"finishReason": "SAFETY"}]})]
)
def test_provider_failures_are_sanitized(monkeypatch, status, body):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        ),
    )
    with pytest.raises(AppError) as error:
        asyncio.run(navigate("help", Settings(gemini_api_key="test-key")))
    assert error.value.status == 503
    assert "test-key" not in error.value.message
