from copy import deepcopy

import pytest
from app.core.errors import AppError
from app.db.models import AuditEvent, Candidate, CandidateSkill, IdempotencyRecord, OutboxEvent, Skill
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def payload(version=0):
    return {
        "profile": {
            "expected_version": version,
            "headline": "Fictional backend engineer",
            "summary": "Prefers building APIs; profile reviewed by the fictional tester.",
            "region": "Seattle",
            "role_families": ["ENGINEERING"],
            "employment_types": ["FULL_TIME"],
            "work_modes": ["REMOTE"],
            "locations": [],
            "currency": "USD",
            "compensation_period": "ANNUAL",
            "compensation_floor": None,
            "cap": 2,
            "terms_accepted": True,
            "privacy_accepted": True,
            "profile_confirmed": True,
        },
        "skills": [{"name": "Python", "level": 3}],
        "skills_confirmed": True,
    }


def test_confirmation_creates_owned_draft_and_self_reported_skills_atomically(market):
    body = payload()
    response = market.call(3, "POST", "/candidates/me/onboarding", body)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["candidate"]["state"] == "DRAFT"
    assert data["candidate"]["role_families"] == ["ENGINEERING"]
    assert data["candidate"]["cap"] == 2
    assert [(s["name"], s["level"], s["verification_status"]) for s in data["skills"]] == [
        ("python", 3, "SELF_REPORTED")
    ]
    with Session(market.engine) as db:
        candidate = db.scalar(select(Candidate).where(Candidate.user_id == market.users[3].id))
        assert candidate.id == data["candidate"]["id"]
        assert candidate.confirmed_at is not None
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.kind == "candidate.onboarding_confirmed"))
        assert event.payload["skill_source"] == "SELF_REPORTED"
        assert "Python" not in str(event.payload)
        assert body["profile"]["summary"] not in str(event.payload)


def test_confirmation_replay_is_actor_scoped_and_version_checked(market):
    body = payload()
    key = "onboarding-confirm-replay"
    first = market.call(3, "POST", "/candidates/me/onboarding", body, key=key)
    again = market.call(3, "POST", "/candidates/me/onboarding", body, key=key)
    assert first.status_code == again.status_code == 200
    assert again.headers["Idempotency-Replayed"] == "true"
    assert first.json() == again.json()
    assert market.call(3, "POST", "/candidates/me/onboarding", body).status_code == 412
    changed = deepcopy(body)
    changed["skills"][0]["level"] = 4
    assert market.call(3, "POST", "/candidates/me/onboarding", changed, key=key).status_code == 409
    other = market.call(4, "POST", "/candidates/me/onboarding", body, key=key)
    assert other.status_code == 200
    assert other.json()["data"]["candidate"]["id"] != first.json()["data"]["candidate"]["id"]
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(CandidateSkill)) == 2
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 2


def test_confirmation_updates_selected_skills_and_preserves_unmentioned_skills(market):
    first_body = payload(market.candidate.version)
    first_body["skills"].append({"name": "SQL", "level": 2})
    first = market.call(0, "POST", "/candidates/me/onboarding", first_body)
    assert first.status_code == 200, first.text
    update = payload(first.json()["data"]["version"])
    update["skills"][0]["level"] = 4
    response = market.call(0, "POST", "/candidates/me/onboarding", update)
    assert response.status_code == 200, response.text
    skills = {skill["name"]: skill for skill in response.json()["data"]["skills"]}
    assert skills["python"]["level"] == 4
    assert skills["python"]["version"] == 2
    assert skills["sql"]["level"] == 2
    assert all(skill["verification_status"] == "SELF_REPORTED" for skill in skills.values())


def test_confirmation_resolves_only_curated_skill_aliases(market):
    with Session(market.engine) as db:
        db.add(Skill(name="javascript", aliases=["JS"]))
        db.commit()
    body = payload()
    body["skills"] = [{"name": "JS", "level": 2}]
    response = market.call(3, "POST", "/candidates/me/onboarding", body)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["skills"][0]["name"] == "javascript"
    with Session(market.engine) as db:
        assert db.scalar(select(Skill).where(Skill.name == "js")) is None


def test_confirmation_rejects_two_aliases_for_one_skill_without_partial_profile_write(market):
    with Session(market.engine) as db:
        db.add(Skill(name="javascript", aliases=["JS"]))
        db.commit()
    body = payload()
    body["skills"] = [{"name": "JS", "level": 2}, {"name": "javascript", "level": 3}]
    response = market.call(3, "POST", "/candidates/me/onboarding", body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DUPLICATE_SKILL"
    with Session(market.engine) as db:
        assert db.scalar(select(Candidate).where(Candidate.user_id == market.users[3].id)) is None


def test_confirmation_does_not_guess_ambiguous_curated_aliases(market):
    with Session(market.engine) as db:
        db.add_all(
            [
                Skill(name="first skill", aliases=["ambiguous"]),
                Skill(name="second skill", aliases=["AMBIGUOUS"]),
            ]
        )
        db.commit()
    body = payload()
    body["skills"] = [{"name": "ambiguous", "level": 2}]
    response = market.call(3, "POST", "/candidates/me/onboarding", body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SKILL_ALIAS_AMBIGUOUS"


@pytest.mark.parametrize("invalid", [False, 1, "true", None])
def test_explicit_skill_confirmation_cannot_be_inferred_or_coerced(market, invalid):
    body = payload()
    body["skills_confirmed"] = invalid
    response = market.call(3, "POST", "/candidates/me/onboarding", body)
    assert response.status_code == 422
    with Session(market.engine) as db:
        assert db.scalar(select(Candidate).where(Candidate.user_id == market.users[3].id)) is None


@pytest.mark.parametrize("field", ["terms_accepted", "privacy_accepted", "profile_confirmed"])
def test_reviewed_profile_requires_separate_literal_consents(market, field):
    body = payload()
    body["profile"][field] = 1
    assert market.call(3, "POST", "/candidates/me/onboarding", body).status_code == 422


@pytest.mark.parametrize(
    "skills",
    [
        [{"name": "python", "level": None}],
        [{"name": "python", "level": True}],
        [{"name": "python", "level": 6}],
        [{"name": "python", "level": 2}, {"name": " Python ", "level": 3}],
        [{"name": "python", "level": 3, "verified": True}],
    ],
)
def test_unknown_invalid_duplicate_or_certified_skill_claims_are_rejected(market, skills):
    body = payload()
    body["skills"] = skills
    assert market.call(3, "POST", "/candidates/me/onboarding", body).status_code == 422


def test_confirmation_rejects_unauthenticated_and_other_candidate_identifiers(market):
    assert market.client.post("/v1/candidates/me/onboarding", json=payload()).status_code == 401
    body = {**payload(), "candidate_id": market.candidate.id}
    assert market.call(3, "POST", "/candidates/me/onboarding", body).status_code == 422


def test_confirmation_does_not_treat_unknown_onsite_locations_as_worldwide_consent(market):
    body = payload()
    body["profile"]["work_modes"] = ["REMOTE", "HYBRID"]
    assert market.call(3, "POST", "/candidates/me/onboarding", body).status_code == 422
    body["profile"]["locations"] = ["Seattle"]
    assert market.call(3, "POST", "/candidates/me/onboarding", body).status_code == 200


def test_confirmation_failure_rolls_back_profile_skills_audit_and_outbox(market, monkeypatch):
    from app.api import onboarding_confirmation

    def fail(*args, **kwargs):
        raise AppError(503, "INJECTED_FAILURE", "Fictional atomicity test failure")

    monkeypatch.setattr(onboarding_confirmation, "emit", fail)
    response = market.call(3, "POST", "/candidates/me/onboarding", payload())
    assert response.status_code == 503
    with Session(market.engine) as db:
        assert db.scalar(select(Candidate).where(Candidate.user_id == market.users[3].id)) is None
        for model in (CandidateSkill, Skill, AuditEvent, OutboxEvent, IdempotencyRecord):
            assert db.scalar(select(func.count()).select_from(model)) == 0
