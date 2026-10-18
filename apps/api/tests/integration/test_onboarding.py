"""API acceptance tests for profile ownership and independently approved tenancy."""

import re
from datetime import timedelta
from uuid import uuid4

import pytest
from app.core.auth import mint_dev_token
from app.db.models import Candidate, OrgMember
from app.services.common import utcnow
from sqlalchemy import select
from sqlalchemy.orm import Session


def profile_payload(**changes):
    return {
        "expected_version": 0,
        "headline": "Fictional embedded engineer",
        "summary": "Fictional test profile",
        "region": "Seattle",
        "role_families": ["ENGINEERING"],
        "employment_types": ["FULL_TIME"],
        "work_modes": ["REMOTE"],
        "locations": [],
        "compensation_floor": "75000.00",
        "currency": "USD",
        "cap": 2,
        "terms_accepted": True,
        "privacy_accepted": True,
        "profile_confirmed": True,
        **changes,
    }


def vacancy_payload(org_id, **changes):
    return {
        "org_id": org_id,
        "title": "Fictional controls engineer",
        "description": "A fictional controls engineering vacancy used solely for tests.",
        "role_family": "ENGINEERING",
        "employment_type": "FULL_TIME",
        "work_mode": "REMOTE",
        "pay_min": "90000.00",
        "pay_max": "140000.00",
        "currency": "USD",
        "cap": 2,
        **changes,
    }


def ok(response, status=200):
    assert response.status_code == status, response.text
    content = response.json()
    assert content["meta"]["request_id"] and content["meta"]["server_time"]
    return content["data"]


def test_new_candidate_persisted_onboarding_preferences_and_capacity(market, engine):
    created = ok(market.call(3, "PUT", "/candidates/me", profile_payload()))
    assert created["state"] == "DRAFT" and created["version"] == 1 and created["cap"] == 2
    assert created["compensation_floor"] == "75000.00"
    active = ok(market.call(3, "POST", "/candidates/me/activate", {"expected_version": 1}))
    assert active["state"] == "ACTIVE" and active["version"] == 2
    settings = {
        "expected_version": 2,
        "cap": 10,
        "compensation_floor": "80000.00",
        "currency": "USD",
        "employment_types": ["FULL_TIME"],
        "work_modes": ["REMOTE"],
        "locations": [],
    }
    preferences = ok(market.call(3, "PUT", "/candidates/me/preferences", settings))
    assert preferences["cap"] == 10 and preferences["version"] == 3
    stale = market.call(3, "PUT", "/candidates/me/preferences", settings)
    assert stale.status_code == 412
    invalid = market.call(
        3, "PUT", "/candidates/me/preferences", {**settings, "expected_version": 3, "cap": 11}
    )
    assert invalid.status_code == 422
    with Session(engine) as db:
        row = db.scalar(select(Candidate).where(Candidate.user_id == market.users[3].id))
        assert row.cap == 10 and row.compensation_floor_cipher != "80000.00"
    assert ok(market.call(0, "GET", "/candidates/me"))["id"] != created["id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("platform_roles", ["VERIFIER"]),
        ("user_id", str(uuid4())),
        ("state", "ACTIVE"),
        ("org_role", "AUTHORIZED_SIGNATORY"),
    ],
)
def test_candidate_cannot_self_assert_identity_or_privileged_fields(market, field, value):
    response = market.call(3, "PUT", "/candidates/me", profile_payload(**{field: value}))
    assert response.status_code == 422
    assert market.call(3, "GET", "/candidates/me").status_code == 404


def test_pending_organization_requires_independent_verification_without_signatory_escalation(market, engine):
    organization = ok(
        market.call(
            3,
            "POST",
            "/organizations",
            {
                "legal_name": "Fictional New Company LLC",
                "display_name": "Fictional New Company",
                "domain": "new-company.example.invalid",
            },
        )
    )
    org_id = organization["id"]
    assert organization["verification_state"] == "PENDING_VERIFICATION"
    assert market.call(3, "POST", "/vacancies", vacancy_payload(org_id)).status_code == 403
    spoof = market.call(
        3,
        "POST",
        f"/organizations/{org_id}/verify",
        {
            "expected_version": 1,
            "source_reference": "Fictional issuer check",
            "independent_check_completed": True,
        },
    )
    assert spoof.status_code == 403
    verified = ok(
        market.call(
            2,
            "POST",
            f"/organizations/{org_id}/verify",
            {
                "expected_version": 1,
                "source_reference": "Independent fictional entity evidence checked by operator",
                "independent_check_completed": True,
            },
        )
    )
    assert verified["verification_state"] == "VERIFIED"
    role = ok(market.call(3, "POST", "/vacancies", vacancy_payload(org_id)))
    assert role["state"] == "DRAFT"
    activated = ok(market.call(3, "POST", f"/vacancies/{role['id']}/activate", {"expected_version": 1}))
    assert activated["state"] == "ACTIVE"
    with Session(engine) as db:
        roles = set(
            db.scalars(
                select(OrgMember.role).where(
                    OrgMember.org_id == org_id,
                    OrgMember.user_id == market.users[3].id,
                    OrgMember.status == "ACTIVE",
                )
            )
        )
    assert roles == {"ORG_ADMIN"}
    denied = market.call(
        3,
        "POST",
        "/pact/policies",
        {
            "roles": [
                {
                    "vacancy_id": role["id"],
                    "expected_version": activated["version"],
                    "terms_hash": activated["terms_hash"],
                }
            ],
            "policy_text": "Fictional exact-role screening policy.",
            "stage": "SCREENING",
            "expires_at": (utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert denied.status_code == 403


def test_unverified_organization_never_activates_existing_draft(market, engine):
    with Session(engine) as db:
        from app.db.models import Organization, Vacancy

        db.get(Organization, market.org.id).verification_state = "PENDING_VERIFICATION"
        db.get(Vacancy, market.vacancy.id).state = "DRAFT"
        db.commit()
    response = market.call(1, "POST", f"/vacancies/{market.vacancy.id}/activate", {"expected_version": 1})
    assert response.status_code == 409 and response.json()["error"]["code"] == "ACTIVATION_BLOCKED"


def test_invitation_is_exact_email_single_use_and_cannot_escalate(market):
    path = f"/organizations/{market.org.id}/members/invite"
    assert (
        market.call(
            1, "POST", path, {"email": market.users[3].verified_email, "role": "AUTHORIZED_SIGNATORY"}
        ).status_code
        == 422
    )
    invitation = ok(
        market.call(1, "POST", path, {"email": market.users[3].verified_email, "role": "RECRUITER"})
    )
    accepted_path = "/organizations/invitations/accept"
    assert market.call(4, "POST", accepted_path, {"token": invitation["token"]}).status_code == 403
    accepted = ok(
        market.call(3, "POST", accepted_path, {"token": invitation["token"]}, key="invitation-accept-once")
    )
    assert accepted["role"] == "RECRUITER" and accepted["org_id"] == market.org.id
    replay = ok(
        market.call(3, "POST", accepted_path, {"token": invitation["token"]}, key="invitation-accept-once")
    )
    assert replay == accepted
    assert market.call(3, "POST", accepted_path, {"token": invitation["token"]}).status_code == 403
    member_path = f"/organizations/{market.org.id}/members/{accepted['id']}"
    assert (
        market.call(1, "PATCH", member_path, {"expected_version": 1, "role": "ORG_ADMIN"}).status_code == 422
    )


def test_invitation_uses_current_provider_verified_email_after_change(market):
    invitation = ok(
        market.call(
            1,
            "POST",
            f"/organizations/{market.org.id}/members/invite",
            {"email": market.users[3].verified_email, "role": "RECRUITER"},
        )
    )
    token = mint_dev_token(market.users[3].id, email="new-verified-address@example.invalid")
    response = market.call(
        3,
        "POST",
        "/organizations/invitations/accept",
        {"token": invitation["token"]},
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code == 403


def test_member_needs_exact_vacancy_acl_and_privileged_grant(market):
    invited = ok(
        market.call(
            1,
            "POST",
            f"/organizations/{market.org.id}/members/invite",
            {"email": market.users[3].verified_email, "role": "RECRUITER"},
        )
    )
    ok(market.call(3, "POST", "/organizations/invitations/accept", {"token": invited["token"]}))
    vacancy_path = f"/vacancies/{market.vacancy.id}"
    assert market.call(3, "GET", vacancy_path).status_code == 403
    acl = {
        "expected_version": 1,
        "user_id": market.users[3].id,
        "can_review": True,
        "can_edit": False,
        "can_approve_policy": True,
    }
    assert market.call(1, "PUT", vacancy_path + "/acl", acl).status_code == 403
    ok(market.call(1, "PUT", vacancy_path + "/acl", {**acl, "can_approve_policy": False}))
    assert ok(market.call(3, "GET", vacancy_path))["id"] == market.vacancy.id
    assert market.call(3, "POST", vacancy_path + "/close", {"expected_version": 1}).status_code == 403
    assert market.call(4, "GET", f"/organizations/{market.org.id}").status_code == 403
    assert market.call(4, "GET", vacancy_path).status_code == 403


def test_skills_crud_ownership_versions_and_availability(market):
    candidate_version = ok(market.call(0, "GET", "/candidates/me"))["version"]
    skill = ok(market.call(0, "POST", "/candidates/me/skills", {"name": "Python", "level": 3}))
    assert ok(market.call(0, "GET", "/candidates/me"))["version"] == candidate_version + 1
    skills = ok(market.call(0, "GET", "/candidates/me/skills"))
    assert skills[0]["name"] == "python" and skills[0]["verification_status"] == "SELF_REPORTED"
    assert market.call(0, "POST", "/candidates/me/skills", {"name": "PYTHON", "level": 3}).status_code == 409
    changed = ok(
        market.call(0, "PATCH", f"/candidates/me/skills/{skill['id']}", {"expected_version": 1, "level": 4})
    )
    assert changed["version"] == 2
    assert (
        market.call(
            0, "PATCH", f"/candidates/me/skills/{skill['id']}", {"expected_version": 1, "level": 2}
        ).status_code
        == 412
    )
    ok(market.call(3, "PUT", "/candidates/me", profile_payload()))
    assert (
        market.call(3, "DELETE", f"/candidates/me/skills/{skill['id']}", {"expected_version": 2}).status_code
        == 403
    )
    ok(market.call(0, "DELETE", f"/candidates/me/skills/{skill['id']}", {"expected_version": 2}))
    assert ok(market.call(0, "GET", "/candidates/me/skills")) == []
    after_skills = ok(market.call(0, "GET", "/candidates/me"))["version"]
    assert after_skills == candidate_version + 2
    window = {
        "expected_version": after_skills,
        "available_from": (utcnow() + timedelta(days=1)).isoformat(),
        "available_until": (utcnow() + timedelta(days=30)).isoformat(),
    }
    updated = ok(market.call(0, "PUT", "/candidates/me/availability", window))
    assert updated["version"] == after_skills + 1 and updated["available_from"]
    assert market.call(0, "PUT", "/candidates/me/availability", window).status_code == 412
    assert (
        market.call(
            0,
            "PUT",
            "/candidates/me/availability",
            {
                **window,
                "expected_version": updated["version"],
                "available_until": (utcnow() - timedelta(days=1)).isoformat(),
            },
        ).status_code
        == 422
    )


def test_every_mutation_route_rejects_missing_authentication(market):
    checked = 0
    paths = market.client.get("/openapi.json").json()["paths"]
    for template, operations in paths.items():
        methods = set(operations) & {"post", "put", "patch", "delete"}
        if not methods or not template.startswith("/v1/"):
            continue
        path = re.sub(r"\{[^}]+\}", lambda _: str(uuid4()), template)
        for method in methods:
            response = market.client.request(method.upper(), path, json={})
            assert response.status_code == 401, (method, path, response.text)
            checked += 1
    assert checked >= 60
