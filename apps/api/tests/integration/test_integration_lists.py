"""Frontend listing contracts preserve tenant, role and double opt-in boundaries."""

from datetime import timedelta

import pytest
from app.db.models import Candidate, DecisionCard, OrgMember, Requirement, Vacancy, VacancyACL
from app.db.pact_models import PactPolicy
from app.services.common import utcnow
from app.services.profiles import refresh_terms
from sqlalchemy import select
from sqlalchemy.orm import Session


def data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


def second_vacancy(market):
    with Session(market.engine, expire_on_commit=False) as db:
        vacancy = Vacancy(
            org_id=market.org.id,
            owner_user_id=market.users[1].id,
            title="Fictional unrelated engineering vacancy",
            description="A separate fictional role for testing scoped disclosure only.",
            role_family="ENGINEERING",
            employment_type="FULL_TIME",
            work_mode="REMOTE",
            pay_min=90000,
            pay_max=130000,
            currency="USD",
            state="ACTIVE",
            reviewed_by=market.users[1].id,
        )
        db.add(vacancy)
        db.flush()
        db.add(
            VacancyACL(
                vacancy_id=vacancy.id, user_id=market.users[1].id, can_review=True, can_approve_policy=True
            )
        )
        refresh_terms(db, vacancy)
        db.commit()
        return vacancy


def policy(market, vacancies=None, authorized=True):
    roles = vacancies or [market.vacancy]
    created = data(
        market.call(
            1,
            "POST",
            "/pact/policies",
            {
                "roles": [
                    {"vacancy_id": role.id, "expected_version": role.version, "terms_hash": role.terms_hash}
                    for role in roles
                ],
                "policy_text": "Explicit human screening authorization for the exact fictional roles in scope.",
                "stage": "SCREENING",
                "expires_at": (utcnow() + timedelta(days=2)).isoformat(),
            },
        ),
        201,
    )
    if not authorized:
        return created
    return data(
        market.call(
            1,
            "POST",
            f"/pact/policies/{created['id']}/authorize",
            {
                "expected_version": created["version"],
                "scope_hash": created["scope_hash"],
                "affirm_human_authority": True,
            },
        )
    )


def first_decision(market):
    issued = data(
        market.call(
            2,
            "POST",
            "/internal/decisions/issue",
            {
                "candidate_id": market.candidate.id,
                "vacancy_id": market.vacancy.id,
                "role_version": market.vacancy.version,
                "first_mover": "CANDIDATE",
                "human_review_reason": "Fictional reviewed pair for listing integration tests.",
            },
        )
    )
    return data(market.call(0, "GET", f"/decisions/{issued['decision_id']}"))


def interested(market, actor, card):
    return data(
        market.call(
            actor,
            "POST",
            f"/decisions/{card['id']}/interested",
            {
                "expected_cycle_version": card["cycle_version"],
                "decision_token": card["decision_token"],
            },
        )
    )


def employer_decision(market):
    with Session(market.engine) as db:
        card_id = db.scalar(
            select(DecisionCard.id).where(
                DecisionCard.side == "EMPLOYER",
                DecisionCard.status == "ACTIVE",
                DecisionCard.candidate_id == market.candidate.id,
                DecisionCard.vacancy_id == market.vacancy.id,
            )
        )
    return data(market.call(1, "GET", f"/decisions/{card_id}"))


def match(market):
    interested(market, 0, first_decision(market))
    return interested(market, 1, employer_decision(market))["match_id"]


def test_employer_policy_list_requires_membership_and_every_scoped_vacancy_acl(market):
    other = second_vacancy(market)
    own = policy(market)
    unrelated = policy(market, [other])
    combined = policy(market, [market.vacancy, other])
    path = f"/organizations/{market.org.id}/pact/policies"
    assert {row["id"] for row in data(market.call(1, "GET", path))} == {
        own["id"],
        unrelated["id"],
        combined["id"],
    }
    for outsider in (0, 3, 4):
        assert market.call(outsider, "GET", path).status_code == 403
    with Session(market.engine) as db:
        db.add(OrgMember(org_id=market.org.id, user_id=market.users[3].id, role="RECRUITER"))
        db.add(VacancyACL(vacancy_id=market.vacancy.id, user_id=market.users[3].id, can_review=True))
        db.commit()
    listed = data(market.call(3, "GET", path))
    assert [row["id"] for row in listed] == [own["id"]]
    assert other.id not in str(listed)


def test_candidate_policy_list_requires_actual_double_opt_in_and_closes_with_match(market):
    authorized = policy(market)
    path = "/candidates/me/pact/policies"
    assert data(market.call(0, "GET", path)) == []
    first = first_decision(market)
    assert data(market.call(0, "GET", path)) == []
    interested(market, 0, first)
    assert data(market.call(0, "GET", path)) == []
    matched = interested(market, 1, employer_decision(market))
    listed = data(market.call(0, "GET", path))
    assert [row["id"] for row in listed] == [authorized["id"]]
    with Session(market.engine) as db:
        db.add(
            Candidate(user_id=market.users[3].id, headline="Another fictional candidate", region="Seattle")
        )
        db.commit()
    assert data(market.call(3, "GET", path)) == []
    current = data(market.call(0, "GET", f"/matches/{matched['match_id']}"))
    data(
        market.call(
            0,
            "POST",
            f"/matches/{matched['match_id']}/withdraw",
            {"expected_version": current["cycle_version"]},
        )
    )
    assert data(market.call(0, "GET", path)) == []


def test_candidate_policy_list_redacts_unmatched_vacancies_from_shared_policy(market):
    other = second_vacancy(market)
    authorized = policy(market, [market.vacancy, other])
    match(market)
    listed = data(market.call(0, "GET", "/candidates/me/pact/policies"))
    assert len(listed) == 1 and listed[0]["id"] == authorized["id"]
    assert set(listed[0]["scope"]) == {market.vacancy.id}
    assert listed[0]["scope"][market.vacancy.id] == authorized["scope"][market.vacancy.id]
    assert listed[0]["scope_hash"] == authorized["scope_hash"]
    assert other.id not in str(listed)


@pytest.mark.parametrize("condition", ["draft", "revoked", "expired", "stale_version", "stale_hash"])
def test_candidate_policy_list_omits_unauthorized_expired_or_changed_terms(market, condition):
    authorized = policy(market, authorized=condition != "draft")
    match(market)
    if condition == "revoked":
        data(
            market.call(
                1,
                "POST",
                f"/pact/policies/{authorized['id']}/revoke",
                {"expected_version": authorized["version"]},
            )
        )
    elif condition == "expired":
        with Session(market.engine) as db:
            db.get(PactPolicy, authorized["id"]).expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
    elif condition in {"stale_version", "stale_hash"}:
        with Session(market.engine) as db:
            vacancy = db.get(Vacancy, market.vacancy.id)
            if condition == "stale_version":
                vacancy.version += 1
            else:
                vacancy.terms_hash = "f" * 64
            db.commit()
    assert data(market.call(0, "GET", "/candidates/me/pact/policies")) == []


def clarification(market, vacancy):
    with Session(market.engine, expire_on_commit=False) as db:
        requirement = Requirement(
            vacancy_id=vacancy.id,
            key="fictional_bonus",
            kind="AMBIGUOUS",
            description="A fictional preference requiring human clarification.",
        )
        db.add(requirement)
        db.commit()
    return data(
        market.call(
            1,
            "POST",
            "/pact/clarifications",
            {
                "vacancy_id": vacancy.id,
                "expected_version": vacancy.version,
                "terms_hash": vacancy.terms_hash,
                "requirement_id": requirement.id,
                "requirement_expected_version": requirement.version,
                "proposed_kind": "PREFERENCE",
                "proposed_text": "Treat the fictional bonus qualification as a preference.",
                "reason": "Fictional reviewer identified that this qualification is optional.",
                "expires_at": (utcnow() + timedelta(days=2)).isoformat(),
            },
        ),
        201,
    )


def test_clarification_list_is_scoped_to_exact_vacancy_and_assigned_staff(market):
    other = second_vacancy(market)
    own = clarification(market, market.vacancy)
    hidden = clarification(market, other)
    path = f"/vacancies/{market.vacancy.id}/pact/clarifications"
    assert [row["id"] for row in data(market.call(1, "GET", path))] == [own["id"]]
    assert [
        row["id"] for row in data(market.call(1, "GET", f"/vacancies/{other.id}/pact/clarifications"))
    ] == [hidden["id"]]
    for outsider in (0, 3, 4):
        assert market.call(outsider, "GET", path).status_code == 403
    with Session(market.engine) as db:
        db.add(OrgMember(org_id=market.org.id, user_id=market.users[3].id, role="RECRUITER"))
        db.add(VacancyACL(vacancy_id=market.vacancy.id, user_id=market.users[3].id, can_review=True))
        db.commit()
    assert [row["id"] for row in data(market.call(3, "GET", path))] == [own["id"]]
    assert market.call(3, "GET", f"/vacancies/{other.id}/pact/clarifications").status_code == 403


@pytest.mark.parametrize("status,expired", [("REVOKED", False), ("PENDING", False), ("ACTIVE", True)])
def test_organization_list_omits_inactive_and_expired_memberships(market, status, expired):
    with Session(market.engine) as db:
        db.add(
            OrgMember(
                org_id=market.org.id,
                user_id=market.users[3].id,
                role="RECRUITER",
                status=status,
                expires_at=utcnow() - timedelta(seconds=1) if expired else None,
            )
        )
        db.commit()
    assert market.call(3, "GET", f"/organizations/{market.org.id}").status_code == 403
    assert data(market.call(3, "GET", "/organizations")) == []
    assert [row["id"] for row in data(market.call(1, "GET", "/organizations"))] == [market.org.id]


def test_organization_creator_can_list_own_pending_onboarding_organization(market):
    created = data(
        market.call(
            3,
            "POST",
            "/organizations",
            {
                "legal_name": "Fictional Pending Organization LLC",
                "display_name": "Fictional Pending Organization",
                "domain": "pending-organization.example.invalid",
            },
        ),
    )
    assert created["verification_state"] == "PENDING_VERIFICATION"
    with Session(market.engine) as db:
        creator_membership = db.scalar(
            select(OrgMember).where(
                OrgMember.user_id == market.users[3].id,
                OrgMember.org_id == created["id"],
            )
        )
        assert creator_membership.status == "PENDING"
        db.add(
            OrgMember(org_id=created["id"], user_id=market.users[4].id, role="RECRUITER", status="PENDING")
        )
        db.commit()
    assert [row["id"] for row in data(market.call(3, "GET", "/organizations"))] == [created["id"]]
    assert data(market.call(4, "GET", "/organizations")) == []
    assert market.call(3, "GET", f"/organizations/{created['id']}/pact/policies").status_code == 403
