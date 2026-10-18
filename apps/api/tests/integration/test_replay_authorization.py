from datetime import timedelta

import jwt
from app.core.auth import mint_dev_token
from app.core.settings import get_settings
from app.services.common import utcnow


def test_policy_revocation_with_old_authentication_remains_replayable(market):
    created = market.call(
        1,
        "POST",
        "/pact/policies",
        {
            "roles": [
                {
                    "vacancy_id": market.vacancy.id,
                    "expected_version": market.vacancy.version,
                    "terms_hash": market.vacancy.terms_hash,
                }
            ],
            "policy_text": "Explicit fictional policy for testing authorization revocation retries.",
            "stage": "SCREENING",
            "expires_at": (utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    policy = created.json()["data"]
    settings = get_settings()
    token = mint_dev_token(market.users[1].id, email=market.users[1].verified_email)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["auth_time"] = int((utcnow() - timedelta(hours=1)).timestamp())
    token = jwt.encode(claims, settings.dev_jwt_secret.get_secret_value(), algorithm="HS256")
    headers = {"Authorization": "Bearer " + token}
    path = f"/pact/policies/{policy['id']}/revoke"
    payload = {"expected_version": policy["version"]}
    first = market.call(1, "POST", path, payload, key="old-auth-policy-revoke", headers=headers)
    assert first.status_code == 200, first.text
    repeated = market.call(1, "POST", path, payload, key="old-auth-policy-revoke", headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == first.json()
    assert repeated.headers["Idempotency-Replayed"] == "true"
