import pytest
from app.core.settings import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "origin,expected",
    [
        ("http://localhost:8000", 401),
        ("http://127.0.0.1:8000", 401),
        ("http://127.0.0.1:3000", 401),
        ("https://untrusted.example", 403),
    ],
)
def test_local_swagger_can_reach_authentication_but_untrusted_origins_cannot(origin, expected):
    application = create_app(Settings(_env_file=None))
    try:
        with TestClient(application) as client:
            response = client.post(
                "/v1/navigation/chat",
                headers={"Origin": origin},
                json={"message": "profile", "consent_to_gemini": True},
            )
        assert response.status_code == expected
        assert response.json()["error"]["code"] == ("UNAUTHORIZED" if expected == 401 else "ORIGIN_FORBIDDEN")
    finally:
        application.state.engine.dispose()


def test_explicit_origins_replace_defaults_and_preflight_matches(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:8000")
    application = create_app(Settings(_env_file=None))
    try:
        with TestClient(application) as client:
            for origin, status in (
                ("http://127.0.0.1:8000", 401),
                ("http://localhost:8000", 403),
                ("https://untrusted.example", 403),
            ):
                response = client.post(
                    "/v1/navigation/chat",
                    headers={"Origin": origin},
                    json={"message": "profile", "consent_to_gemini": True},
                )
                assert response.status_code == status
            response = client.options(
                "/v1/navigation/chat",
                headers={
                    "Origin": "http://127.0.0.1:8000",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
                },
            )
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"
    finally:
        application.state.engine.dispose()
