"""Learning consent is explicit, owned, versioned and transactionally recorded."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import jwt
import pytest
from app.core.auth import mint_dev_token
from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.models import AuditEvent, Candidate, Organization, OrgMember, OutboxEvent, User
from app.services.common import utcnow
from app.services.matching_learning import set_learning_consent
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres


def data(response, status=200):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["meta"]["request_id"]
    assert body["meta"]["server_time"]
    return body["data"]


@pytest.mark.parametrize(
    "owner,path,model",
    [
        (0, "/candidates/me/learning-consent", Candidate),
        (1, "/organizations/{org_id}/learning-consent", Organization),
    ],
)
def test_learning_consent_default_opt_in_out_versions_audit_and_idempotency(market, owner, path, model):
    path = path.format(org_id=market.org.id)
    initial = data(market.call(owner, "GET", path))
    assert initial == {"enabled": False, "version": 1, "consent_version": 1}
    payload = {"enabled": True, "expected_version": initial["version"]}
    first_response = market.call(owner, "PUT", path, payload, key="explicit-learning-consent-enable")
    opted_in = data(first_response)
    assert opted_in == {"enabled": True, "version": 2, "consent_version": 2}
    repeated = market.call(owner, "PUT", path, payload, key="explicit-learning-consent-enable")
    assert repeated.status_code == 200
    assert repeated.headers["Idempotency-Replayed"] == "true"
    assert repeated.json() == first_response.json()
    stale = market.call(owner, "PUT", path, {"enabled": False, "expected_version": 1})
    assert stale.status_code == 412
    opted_out = data(market.call(owner, "PUT", path, {"enabled": False, "expected_version": 2}))
    assert opted_out == {"enabled": False, "version": 3, "consent_version": 3}
    # A retry returns its historical response; it cannot restore revoked consent.
    replay = market.call(owner, "PUT", path, payload, key="explicit-learning-consent-enable")
    assert replay.json() == first_response.json()
    assert data(market.call(owner, "GET", path)) == opted_out
    with Session(market.engine) as db:
        entity_id = market.candidate.id if model is Candidate else market.org.id
        row = db.get(model, entity_id)
        assert row.matching_learning_opt_in is False
        assert row.matching_learning_consent_version == 3
        assert (
            db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == entity_id))
            == 2
        )
        assert (
            db.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == entity_id)
            )
            == 2
        )


@pytest.mark.parametrize("invalid", ["true", "false", "yes", 1, 0, None, [], {}])
def test_learning_consent_rejects_truthy_and_falsy_non_booleans(market, invalid):
    response = market.call(
        0, "PUT", "/candidates/me/learning-consent", {"enabled": invalid, "expected_version": 1}
    )
    assert response.status_code == 422
    assert data(market.call(0, "GET", "/candidates/me/learning-consent"))["enabled"] is False


@pytest.mark.parametrize("invalid", [True, False, "1", 0, -1, 1.5, None])
def test_learning_consent_rejects_non_integer_or_invalid_resource_version(market, invalid):
    response = market.call(
        0, "PUT", "/candidates/me/learning-consent", {"enabled": True, "expected_version": invalid}
    )
    assert response.status_code == 422


def test_learning_consent_reads_and_writes_are_owned_and_replay_rechecks_membership(market):
    org_path = f"/organizations/{market.org.id}/learning-consent"
    assert market.call(0, "GET", org_path).status_code == 403
    assert market.call(3, "PUT", org_path, {"enabled": True, "expected_version": 1}).status_code == 403
    assert market.call(1, "GET", "/candidates/me/learning-consent").status_code == 404
    payload = {"enabled": True, "expected_version": 1}
    assert market.call(1, "PUT", org_path, payload, key="membership-learning-consent").status_code == 200
    with Session(market.engine) as db, db.begin():
        admin = db.scalar(
            select(OrgMember).where(
                OrgMember.org_id == market.org.id,
                OrgMember.user_id == market.users[1].id,
                OrgMember.role == "ORG_ADMIN",
            )
        )
        admin.status = "REVOKED"
    # The user's recruiter/signatory memberships do not authorize this setting.
    assert market.call(1, "GET", org_path).status_code == 403
    assert market.call(1, "PUT", org_path, payload, key="membership-learning-consent").status_code == 403


def test_learning_consent_expired_admin_cannot_read_or_update(market):
    with Session(market.engine) as db, db.begin():
        admin = db.scalar(
            select(OrgMember).where(
                OrgMember.org_id == market.org.id,
                OrgMember.user_id == market.users[1].id,
                OrgMember.role == "ORG_ADMIN",
            )
        )
        admin.expires_at = utcnow() - timedelta(days=1)
    path = f"/organizations/{market.org.id}/learning-consent"
    assert market.call(1, "GET", path).status_code == 403
    assert market.call(1, "PUT", path, {"enabled": True, "expected_version": 1}).status_code == 403


def test_learning_consent_concurrent_stale_updates_do_not_lose_versions(market):
    def update(index):
        with Session(market.engine) as db:
            try:
                with db.begin():
                    set_learning_consent(db, market.actor(0), db.get(Candidate, market.candidate.id), True, 1)
                return 200
            except AppError as exc:
                return exc.status

    with ThreadPoolExecutor(max_workers=2) as workers:
        statuses = list(workers.map(update, (0, 1)))
    assert sorted(statuses) == [200, 412]
    assert data(market.call(0, "GET", "/candidates/me/learning-consent")) == {
        "enabled": True,
        "version": 2,
        "consent_version": 2,
    }


def test_current_learning_consent_exposes_only_approved_state(market):
    result = data(market.call(0, "GET", "/candidates/me/learning-consent"))
    assert set(result) == {"enabled", "version", "consent_version"}
    assert (
        market.call(
            0,
            "PUT",
            "/candidates/me/learning-consent",
            {"enabled": True, "expected_version": 1, "candidate_id": market.users[3].id},
        ).status_code
        == 422
    )


def test_model_registry_is_restricted_to_persisted_research_or_system_roles(market):
    path = "/internal/matching/model"
    assert market.call(0, "GET", path).status_code == 403
    assert data(market.call(2, "GET", path)) == {"active": False, "model_id": None, "version": None}
    with Session(market.engine) as db, db.begin():
        db.get(User, market.users[2].id).platform_roles = ["OPERATIONS"]
        db.get(User, market.users[4].id).platform_roles = ["SYSTEM_WORKER"]
    assert market.call(2, "GET", path).status_code == 403
    assert data(market.call(4, "GET", path))["active"] is False
    assert (
        market.call(
            2, "POST", path, {"artifact": {}, "evaluation": {}, "expected_active_model_id": None}
        ).status_code
        == 403
    )
    assert (
        market.call(
            2,
            "POST",
            path + "/retire",
            {"expected_active_model_id": "a" * 64, "reason": "Fictional retirement fixture"},
        ).status_code
        == 403
    )


def test_jwt_role_metadata_cannot_grant_model_registry_access(market):
    token = mint_dev_token(market.users[0].id, email=market.users[0].verified_email)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["app_metadata"] = {"roles": ["RESEARCH_ADMIN", "SYSTEM_WORKER"]}
    claims["role"] = "RESEARCH_ADMIN"
    token = jwt.encode(claims, get_settings().dev_jwt_secret.get_secret_value(), algorithm="HS256")
    response = market.call(0, "GET", "/internal/matching/model", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 403


def test_model_activation_validates_explicit_incumbent_and_artifact(market):
    path = "/internal/matching/model"
    missing_incumbent = market.call(2, "POST", path, {"artifact": {}, "evaluation": {}})
    assert missing_incumbent.status_code == 422
    invalid_id = market.call(
        2, "POST", path, {"artifact": {}, "evaluation": {}, "expected_active_model_id": "invalid"}
    )
    assert invalid_id.status_code == 422
    invalid_artifact = market.call(
        2, "POST", path, {"artifact": {}, "evaluation": {}, "expected_active_model_id": None}
    )
    assert invalid_artifact.status_code == 422
    assert data(market.call(2, "GET", path)) == {"active": False, "model_id": None, "version": None}
