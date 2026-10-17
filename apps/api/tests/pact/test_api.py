from datetime import timedelta
from uuid import uuid4

import pytest
from app.api.pact import router
from app.core.auth import mint_dev_token
from app.core.errors import AppError
from app.core.settings import Settings, get_settings
from app.db.models import User
from app.db.pact_models import EvidenceClaim
from app.services.common import utcnow
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture
def pact_client(pact_market, pact_engine):
    m = pact_market
    settings = Settings(
        environment="test",
        auth_mode="local",
        allow_dev_auth=True,
        dev_jwt_secret="fictional-pact-api-test-secret-more-than-32-characters",
        database_url=get_settings().database_url,
    )
    for user in m.db.scalars(select(User)):
        user.issuer, user.subject = settings.jwt_issuer, user.id
    m.db.commit()
    app = FastAPI()
    app.state.engine, app.state.settings = pact_engine, settings
    app.include_router(router, prefix="/v1")

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    token = mint_dev_token(m.candidate_actor.user_id, settings=settings)
    with TestClient(app) as client:
        yield client, {"Authorization": f"Bearer {token}"}, settings


def test_pact_api_durable_idempotency_conflict_and_version(pact_client, pact_market):
    client, auth, _ = pact_client
    m = pact_market
    payload = {
        "expected_version": 1,
        "claim_type": "LICENSE",
        "requirement_keys": [m.essential.key],
        "statement": "Fictional candidate license statement.",
        "job_related_purpose": "Fictional regulated work.",
    }
    headers = {**auth, "Idempotency-Key": "pact-claim-create-1"}
    first = client.post("/v1/evidence/claims", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    repeated = client.post("/v1/evidence/claims", json=payload, headers=headers)
    assert repeated.status_code == 201 and repeated.json() == first.json()
    assert repeated.headers["Idempotency-Replayed"] == "true"
    conflict = client.post(
        "/v1/evidence/claims",
        json={**payload, "statement": "A different fictional claim statement."},
        headers=headers,
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    stale = client.post(
        "/v1/evidence/claims",
        json={**payload, "expected_version": 99},
        headers={**auth, "Idempotency-Key": "pact-claim-stale-1"},
    )
    assert stale.status_code == 412
    missing_idempotency = client.post("/v1/evidence/claims", json=payload, headers=auth)
    assert missing_idempotency.status_code == 422
    assert m.db.scalar(select(func.count()).select_from(EvidenceClaim)) == 1
    own = client.get("/v1/evidence/claims/me", headers=auth)
    assert own.status_code == 200 and len(own.json()["data"]) == 1
    assert "statement" not in own.json()["data"][0]


def test_pact_api_every_route_requires_authentication(pact_client):
    client, _, _ = pact_client
    for route in router.routes:
        path = "/v1" + route.path
        for parameter in route.param_convertors:
            path = path.replace("{" + parameter + "}", str(uuid4()))
        for method in route.methods - {"HEAD", "OPTIONS"}:
            response = client.request(method, path, json={} if method == "POST" else None)
            assert response.status_code == 401, (method, path, response.text)


def test_pact_api_cannot_self_assert_verifier_or_signatory(pact_client, pact_market):
    client, auth, _ = pact_client
    m = pact_market
    create = client.post(
        "/v1/evidence/claims",
        headers={**auth, "Idempotency-Key": "test-spoof-create"},
        json={
            "expected_version": 1,
            "claim_type": "LICENSE",
            "requirement_keys": [m.essential.key],
            "statement": "A fictional license statement.",
            "job_related_purpose": "A fictional license requirement.",
        },
    )
    claim_id = create.json()["data"]["id"]
    response = client.post(
        f"/v1/evidence/claims/{claim_id}/verify",
        headers={**auth, "Idempotency-Key": "test-spoof-verify", "X-Platform-Roles": "VERIFIER"},
        json={
            "expected_version": 1,
            "decision": "VERIFIED",
            "method": "ISSUER_CONTACT",
            "issuer": "Fictional issuer",
            "source_reference": "A fictional independent source reference.",
            "expires_at": "2099-01-01T00:00:00Z",
            "affirm_independent_check": True,
        },
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "VERIFIER_REQUIRED"
    response = client.post(
        "/v1/pact/policies",
        headers={
            **auth,
            "Idempotency-Key": "test-spoof-signatory",
            "X-Organization-Role": "AUTHORIZED_SIGNATORY",
        },
        json={
            "roles": [
                {"vacancy_id": m.vacancy.id, "expected_version": 1, "terms_hash": m.vacancy.terms_hash}
            ],
            "policy_text": "A fictional policy statement.",
            "stage": "SCREENING",
            "expires_at": (utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 403
