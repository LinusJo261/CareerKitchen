"""Real PostgreSQL demo preparation, bounded allocation and ordinary mutual decisions."""

import json
from uuid import uuid4

import pytest
from app.core.auth import mint_dev_token
from app.core.settings import get_settings
from app.db.base import Base
from app.db.models import (
    AuditEvent,
    Candidate,
    CandidateSkill,
    DecisionCard,
    EmploymentStart,
    MatchingObservation,
    MutualMatch,
    Organization,
    OutboxEvent,
    Vacancy,
)
from app.main import create_app
from app.services.common import verify_audit_integrity
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.api.demo import IMPORT_MARKER, sample_identity
from scripts.prepare_sample_demo import activate_samples
from scripts.seed_samples import import_samples

pytestmark = pytest.mark.postgres


@pytest.fixture
def sample_market():
    url = make_url(get_settings().database_url).set(database="career_kitchen_samples")
    schema = "sample_demo_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "connect_timeout": 5,
            "options": f"-c search_path={schema} -c statement_timeout=15000 -c lock_timeout=10000",
        },
    )
    settings = get_settings().model_copy(
        update={"database_url": url.render_as_string(hide_password=False), "sample_demo_enabled": True}
    )
    resume = {
        "resume_id": "R_000000",
        "role": "Software Engineer",
        "seniority": "Mid",
        "years_experience": 4,
        "industry": "Technology",
        "education": "BSc",
        "skills": ["Python", "SQL"],
        "summary": "Synthetic developer",
        "experience_bullets": ["Fictional software delivery"],
    }
    job = {
        "job_id": "J_000000",
        "job_title": "Software Engineer",
        "seniority": "Mid",
        "industry": "Technology",
        "must_have_skills": ["Python"],
        "nice_to_have_skills": ["SQL"],
        "description": "Synthetic Python role",
        "responsibilities": ["Fictional engineering"],
        "requirements": ["Source fixture preference"],
    }
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE ck_sample_marker(marker text PRIMARY KEY)"))
            connection.execute(
                text("INSERT INTO ck_sample_marker VALUES (:marker)"), {"marker": IMPORT_MARKER}
            )
        with Session(engine) as db, db.begin():
            import_samples(
                db,
                {"resumes": [resume], "jobs": [job]},
                {"manifest_sha256": "a" * 64},
                candidates=6,
                vacancies=8,
                batch_size=2,
            )
        yield engine, settings
    finally:
        engine.dispose()
        with admin.connect() as connection:
            # Fixed prefix plus random hex; test rows never share the public schema.
            assert schema.startswith("sample_demo_test_") and len(schema) == len("sample_demo_test_") + 32
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def activate(market):
    engine, settings = market
    with Session(engine) as db, db.begin():
        return activate_samples(db, settings)


def headers(account):
    label = "employer" if account == "employer" else "candidate-user-000001"
    return {
        "Authorization": "Bearer "
        + mint_dev_token(sample_identity(label), email=f"{account}@samples.example.invalid"),
        "Idempotency-Key": str(uuid4()),
    }


def test_preparation_is_atomic_versioned_audited_and_replayable(sample_market):
    result = activate(sample_market)
    engine, _ = sample_market
    assert result["ready"] and result["initial_decision_cards"] == 3
    with Session(engine) as db:
        before = {
            table: db.scalar(select(func.count()).select_from(model))
            for table, model in [("audit", AuditEvent), ("outbox", OutboxEvent), ("cards", DecisionCard)]
        }
        assert all(
            row.state == "ACTIVE"
            and row.version == 2
            and row.terms_accepted
            and row.privacy_accepted
            and not row.matching_learning_opt_in
            for row in db.scalars(select(Candidate))
        )
        assert all(row.state == "ACTIVE" and row.version == 2 for row in db.scalars(select(Vacancy)))
        assert all(
            row.verification_state == "VERIFIED" and not row.matching_learning_opt_in
            for row in db.scalars(select(Organization))
        )
        assert all(row.confirmed and row.version == 2 for row in db.scalars(select(CandidateSkill)))
        assert all(verify_audit_integrity(row) for row in db.scalars(select(AuditEvent)))
        assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0
        assert db.scalar(select(func.count()).select_from(EmploymentStart)) == 0
        assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 0
    assert activate(sample_market) == result
    with Session(engine) as db:
        assert before == {
            table: db.scalar(select(func.count()).select_from(model))
            for table, model in [("audit", AuditEvent), ("outbox", OutboxEvent), ("cards", DecisionCard)]
        }


def test_demo_uses_executor_caps_and_requires_both_actual_decisions(sample_market):
    prepared = activate(sample_market)
    engine, settings = sample_market
    with TestClient(create_app(settings, engine)) as client:
        candidate_headers = headers("candidate-000001")
        cards = client.get("/v1/candidates/me/decisions", headers=candidate_headers).json()["data"]
        assert len(cards) == 3
        first = cards[0]
        assert first["vacancy"]["id"] in prepared["vacancy_ids"]
        # Running again cannot overfill the existing three-card attention limit.
        allocation = client.post("/v1/demo/reconcile", headers=candidate_headers, json={})
        assert allocation.status_code == 200 and allocation.json()["data"]["issued_count"] == 0
        replay = client.post("/v1/demo/reconcile", headers=candidate_headers, json={})
        assert replay.headers["Idempotency-Replayed"] == "true"
        employer_headers = headers("employer")
        endpoint = f"/v1/vacancies/{first['vacancy']['id']}/decisions"
        assert client.get(endpoint, headers=employer_headers).json()["data"] == []
        interested = {
            "expected_cycle_version": first["cycle_version"],
            "decision_token": first["decision_token"],
        }
        decision_path = f"/v1/decisions/{first['id']}/interested"
        response = client.post(decision_path, headers=headers("candidate-000001"), json=interested)
        assert response.status_code == 200, response.text
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(MutualMatch)) == 0
        employer_card = client.get(endpoint, headers=employer_headers).json()["data"][0]
        response = client.post(
            f"/v1/decisions/{employer_card['id']}/interested",
            headers=headers("employer"),
            json={
                "expected_cycle_version": employer_card["cycle_version"],
                "decision_token": employer_card["decision_token"],
            },
        )
        assert response.status_code == 200, response.text
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(MutualMatch)) == 1
        replenished = client.post("/v1/demo/reconcile", headers=headers("candidate-000001"), json={})
        assert replenished.status_code == 200 and replenished.json()["data"]["issued_count"] == 1
        assert (
            len(client.get("/v1/candidates/me/decisions", headers=headers("candidate-000001")).json()["data"])
            == 3
        )


def test_demo_catalog_pages_original_fixtures_without_private_edits(sample_market):
    activate(sample_market)
    engine, settings = sample_market
    with TestClient(create_app(settings, engine)) as client:
        auth = headers("candidate-000001")
        first = client.get("/v1/demo/catalog?kind=jobs&limit=1", headers=auth).json()["data"]
        second = client.get("/v1/demo/catalog?kind=jobs&limit=1&offset=1", headers=auth).json()["data"]
        assert first["total"] == 8 and first["next_offset"] == 1
        assert first["items"][0]["id"] != second["items"][0]["id"]
        result = client.get("/v1/demo/catalog?kind=applicants&q=Python", headers=auth)
        assert result.status_code == 200 and result.json()["data"]["total"] == 6
        with Session(engine) as db, db.begin():
            candidate = db.get(Candidate, sample_identity("candidate-000002"))
            candidate.summary = "PRIVATE EDIT SENTINEL"
            candidate.version += 1
            job = Vacancy(
                org_id=sample_identity("org-000001"),
                owner_user_id=sample_identity("employer"),
                title="[SYNTHETIC PRIVATE] New private draft",
                description="PRIVATE DRAFT SENTINEL",
                role_family="ENGINEERING",
                employment_type="FULL_TIME",
                work_mode="REMOTE",
                pay_min=0,
                pay_max=0,
                currency="USD",
            )
            db.add(job)
        catalog = client.get("/v1/demo/catalog?kind=applicants", headers=auth).json()["data"]
        assert catalog["total"] == 5 and "PRIVATE EDIT SENTINEL" not in json.dumps(catalog)
        catalog = client.get("/v1/demo/catalog?kind=jobs", headers=auth).json()["data"]
        assert catalog["total"] == 8 and "PRIVATE DRAFT SENTINEL" not in json.dumps(catalog)
        assert client.get("/v1/demo/catalog?limit=500", headers=auth).status_code == 422


def test_disabled_wrong_database_and_unprepared_replays_fail_closed(sample_market):
    engine, settings = sample_market
    with TestClient(create_app(settings, engine)) as client:
        assert client.get("/v1/demo/status").json()["data"]["ready"] is False
        assert (
            client.post("/v1/demo/reconcile", headers=headers("candidate-000001"), json={}).status_code == 409
        )
    activate(sample_market)
    with TestClient(create_app(settings, engine)) as client:
        auth = headers("candidate-000001")
        assert client.post("/v1/demo/reconcile", headers=auth, json={}).status_code == 200
        # A stored result cannot authorize replay after the feature is disabled.
        settings.sample_demo_enabled = False
        assert client.post("/v1/demo/reconcile", headers=auth, json={}).status_code == 404
        assert client.get("/v1/demo/catalog", headers=auth).status_code == 404
    settings.sample_demo_enabled = True
    settings.database_url = settings.database_url.replace("/career_kitchen_samples", "/career_kitchen")
    with TestClient(create_app(settings, engine)) as client:
        assert client.get("/v1/demo/status").status_code == 404
