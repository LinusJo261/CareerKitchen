"""Public synthetic profiles stay draft, isolated, audited and replay-safe."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from app.core.auth import mint_dev_token
from app.core.settings import Settings, get_settings
from app.db.base import Base
from app.db.models import (
    AuditEvent,
    Candidate,
    CandidateSkill,
    DecisionCard,
    EmploymentStart,
    Exposure,
    IdempotencyRecord,
    MatchingModel,
    MatchingObservation,
    MutualMatch,
    Organization,
    OrgMember,
    OutboxEvent,
    PairCycle,
    Requirement,
    Skill,
    User,
    Vacancy,
    VacancyACL,
)
from app.main import create_app
from app.services.common import digest, verify_audit_integrity
from app.services.profiles import refresh_terms
from app.workers.runner import RECONCILE_EVENTS
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from scripts import seed_samples
from scripts.local_dev import LocalSetupError

pytestmark = pytest.mark.postgres


@pytest.fixture
def source_tables():
    """Tiny source-schema fixtures; no external documents or outcome labels."""
    return {
        "resumes": [
            {
                "resume_id": "R_000001",
                "role": "Backend Engineer",
                "seniority": "Mid",
                "years_experience": 4,
                "industry": "Technology",
                "education": "Fictional source education text",
                "skills": ["Python", "PostgreSQL"],
                "summary": "Fictional private source summary alpha, never event content.",
                "experience_bullets": ["Fictional private source experience alpha."],
            },
            {
                "resume_id": "R_000002",
                "role": "Data Engineer",
                "seniority": "Senior",
                "years_experience": 8,
                "industry": "Technology",
                "education": "Fictional source education text",
                "skills": ["Python", "SQL"],
                "summary": "Fictional private source summary beta, never event content.",
                "experience_bullets": ["Fictional private source experience beta."],
            },
        ],
        "jobs": [
            {
                "job_id": "J_000001",
                "job_title": "Backend Engineer",
                "seniority": "Mid",
                "industry": "Technology",
                "must_have_skills": ["Python"],
                "nice_to_have_skills": ["PostgreSQL"],
                "description": "Fictional private source vacancy alpha, never event content.",
                "responsibilities": ["Fictional source responsibility alpha."],
                "requirements": ["Fictional source requirement alpha."],
            },
            {
                "job_id": "J_000002",
                "job_title": "Data Engineer",
                "seniority": "Senior",
                "industry": "Technology",
                "must_have_skills": ["SQL"],
                "nice_to_have_skills": ["Python"],
                "description": "Fictional private source vacancy beta, never event content.",
                "responsibilities": ["Fictional source responsibility beta."],
                "requirements": ["Fictional source requirement beta."],
            },
        ],
    }


@pytest.fixture
def provenance():
    return {
        "dataset": "michaelozon/candidate-matching-synthetic",
        "revision": "178ab864dcad9910c5670d43e4bdbbb901a11f18",
        "manifest_sha256": digest("explicitly fictional source-schema test fixture"),
    }


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def snapshot(db):
    """Compare all application state, including event IDs, timestamps and receipts."""
    return {
        table.name: digest(
            [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
        )
        for table in Base.metadata.sorted_tables
    }


def import_fixture(engine, source_tables, provenance, **changes):
    with Session(engine) as db, db.begin():
        return seed_samples.import_samples(
            db, source_tables, provenance, **{"candidates": 5, "vacancies": 4, "batch_size": 2, **changes}
        )


def test_sample_import_preserves_schema_versions_and_draft_consent_boundaries(
    engine, source_tables, provenance
):
    result = import_fixture(engine, source_tables, provenance)
    assert isinstance(result, dict) and result
    with Session(engine) as db:
        assert count(db, Candidate) == 5
        assert count(db, Vacancy) == 4
        assert count(db, CandidateSkill) == 10
        assert count(db, Skill) == 3
        assert count(db, Requirement) >= 4
        assert count(db, VacancyACL) == 4
        assert count(db, Organization) >= 1

        for model in (
            User,
            Candidate,
            CandidateSkill,
            Skill,
            Organization,
            OrgMember,
            Vacancy,
            VacancyACL,
            Requirement,
        ):
            assert all(row.version == 1 for row in db.scalars(select(model)))
        for candidate in db.scalars(select(Candidate)):
            assert candidate.state == "DRAFT" and candidate.cap == 3
            assert candidate.terms_accepted is False
            assert candidate.privacy_accepted is False
            assert candidate.confirmed_at is None
            assert candidate.matching_learning_opt_in is False
        assert all(skill.confirmed is False for skill in db.scalars(select(CandidateSkill)))
        for vacancy in db.scalars(select(Vacancy)):
            assert vacancy.state == "DRAFT" and vacancy.cap == 3
            assert vacancy.reviewed_by is None
            assert vacancy.terms_hash
            saved_terms = vacancy.terms_hash
            refresh_terms(db, vacancy)
            assert vacancy.terms_hash == saved_terms
            assert 0 <= vacancy.pay_min <= vacancy.pay_max
            assert vacancy.openings_remaining <= vacancy.openings_total
        for organization in db.scalars(select(Organization)):
            assert organization.verification_state == "PENDING_VERIFICATION"
            assert organization.verified_by is None
            assert organization.matching_learning_opt_in is False
        assert {member.role for member in db.scalars(select(OrgMember))} <= {"ORG_ADMIN", "RECRUITER"}
        assert all(user.verified_email.endswith(".invalid") for user in db.scalars(select(User)))
        assert all(user.platform_roles == [] for user in db.scalars(select(User)))
        assert db.get(Candidate, seed_samples.identity("candidate-000001")) is not None
        assert db.get(Vacancy, seed_samples.identity("vacancy-000001")) is not None
        for model in (
            PairCycle,
            DecisionCard,
            Exposure,
            MutualMatch,
            EmploymentStart,
            MatchingObservation,
            MatchingModel,
        ):
            assert count(db, model) == 0


def test_sample_import_audits_root_aggregates_without_source_text(engine, source_tables, provenance):
    import_fixture(engine, source_tables, provenance)
    with Session(engine) as db:
        audits = list(db.scalars(select(AuditEvent)))
        events = list(db.scalars(select(OutboxEvent)))
        assert len(audits) == len(events) >= 9
        assert all(verify_audit_integrity(row) for row in audits)
        assert all(row.action == "sample.imported" for row in audits)
        assert all(row.kind == "sample.imported" for row in events)
        for model, source_key in ((Candidate, "resume_id"), (Vacancy, "job_id")):
            source_rows = source_tables["resumes" if model is Candidate else "jobs"]
            source_ids = {row[source_key] for row in source_rows}
            for root in db.scalars(select(model)):
                root_audits = [row for row in audits if row.entity_id == root.id]
                root_events = [row for row in events if row.aggregate_id == root.id]
                assert len(root_audits) == len(root_events) == 1
                payload = root_events[0].payload
                assert payload["entity_type"] == model.__tablename__
                assert payload["version"] == 1
                assert payload["synthetic"] is True
                assert payload["source_id"] in source_ids
                assert type(payload["replica"]) is int and payload["replica"] >= 0
                assert root_audits[0].after_hash == digest(payload)
        serialized_events = json.dumps([row.payload for row in events])
        for row in source_tables["resumes"]:
            assert row["summary"] not in serialized_events
            assert all(value not in serialized_events for value in row["experience_bullets"])
        for row in source_tables["jobs"]:
            assert row["description"] not in serialized_events
            assert all(value not in serialized_events for value in row["requirements"])
            assert all(value not in serialized_events for value in row["responsibilities"])


def test_imported_samples_serialize_through_api_and_keep_tenant_boundaries(engine, source_tables, provenance):
    import_fixture(engine, source_tables, provenance)
    settings = get_settings()
    with Session(engine) as db:
        users = {
            label: db.get(User, seed_samples.identity(label))
            for label in ("employer", "candidate-user-000001")
        }
        headers = {
            label: {
                "Authorization": "Bearer "
                + mint_dev_token(user.subject, email=user.verified_email, settings=settings)
            }
            for label, user in users.items()
        }
        before = snapshot(db)
    with TestClient(create_app(settings, engine)) as client:
        candidate_response = client.get("/v1/candidates/me", headers=headers["candidate-user-000001"])
        assert candidate_response.status_code == 200, candidate_response.text
        profile = candidate_response.json()["data"]
        assert profile["id"] == seed_samples.identity("candidate-000001")
        assert profile["state"] == "DRAFT" and profile["terms_accepted"] is False
        source = source_tables["resumes"][0]
        assert source["summary"] in profile["summary"]
        assert source["education"] in profile["summary"]
        assert source["industry"] in profile["summary"]
        assert all(value in profile["summary"] for value in source["experience_bullets"])
        # The source supplies no dates or institutions for typed history records.
        assert profile["experiences"] == profile["education"] == []
        vacancy_path = "/v1/vacancies/" + seed_samples.identity("vacancy-000001")
        employer_response = client.get(vacancy_path, headers=headers["employer"])
        assert employer_response.status_code == 200, employer_response.text
        assert employer_response.json()["data"]["state"] == "DRAFT"
        assert client.get(vacancy_path, headers=headers["candidate-user-000001"]).status_code == 403
        organization_path = "/v1/organizations/" + seed_samples.identity("org-000001") + "/vacancies"
        assert client.get(organization_path, headers=headers["candidate-user-000001"]).status_code == 403
    with Session(engine) as db:
        assert snapshot(db) == before
    assert "sample.imported" not in RECONCILE_EVENTS


def test_identical_import_replays_without_any_database_change(engine, source_tables, provenance):
    import_fixture(engine, source_tables, provenance)
    with Session(engine) as db:
        before = snapshot(db)
        receipt = db.get(
            IdempotencyRecord,
            (seed_samples.identity("importer"), "sample-import/v1", "initial-import"),
        )
        assert receipt is not None
    import_fixture(engine, source_tables, provenance)
    with Session(engine) as db:
        assert snapshot(db) == before


@pytest.mark.parametrize("change", ["count", "source_content", "provenance"])
def test_conflicting_import_refuses_without_database_changes(engine, source_tables, provenance, change):
    import_fixture(engine, source_tables, provenance)
    with Session(engine) as db:
        before = snapshot(db)
    tables, source = deepcopy(source_tables), deepcopy(provenance)
    options = {}
    if change == "count":
        options["candidates"] = 6
    elif change == "source_content":
        tables["resumes"][0]["summary"] += " Changed after original import."
    else:
        source["manifest_sha256"] = digest("different source manifest")
    with pytest.raises(ValueError):
        import_fixture(engine, tables, source, **options)
    with Session(engine) as db:
        assert snapshot(db) == before


@pytest.mark.parametrize("existing_model", [User, Skill])
def test_sample_import_refuses_populated_database(engine, source_tables, provenance, existing_model):
    with Session(engine) as db, db.begin():
        existing = (
            User(issuer="fictional-existing-user", subject="preserve-existing-data")
            if existing_model is User
            else Skill(name="existing-unrelated-taxonomy")
        )
        db.add(existing)
    with Session(engine) as db:
        before = snapshot(db)
    with pytest.raises(ValueError):
        import_fixture(engine, source_tables, provenance)
    with Session(engine) as db:
        assert snapshot(db) == before


def test_failed_outbox_write_rolls_back_profiles_events_and_receipt(engine, source_tables, provenance):
    observed = []

    def fail_outbox(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into") and "outbox_events" in statement.lower():
            observed.append(connection.scalar(select(func.count()).select_from(User)))
            raise RuntimeError("Injected sample outbox persistence failure")

    event.listen(engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="Injected sample outbox"):
            import_fixture(engine, source_tables, provenance)
    finally:
        event.remove(engine, "before_cursor_execute", fail_outbox)
    assert observed and observed[0] > 0
    with Session(engine) as db:
        assert all(
            db.scalar(select(func.count()).select_from(table)) == 0 for table in Base.metadata.tables.values()
        )
    # A failed transaction leaves no poisoned receipt and can be safely retried.
    import_fixture(engine, source_tables, provenance)
    with Session(engine) as db:
        assert count(db, Candidate) == 5 and count(db, Vacancy) == 4


def test_invalid_source_row_leaves_no_partial_import(engine, source_tables, provenance):
    tables = deepcopy(source_tables)
    tables["jobs"][-1]["must_have_skills"] = ["Python", 17]
    with pytest.raises(ValueError):
        import_fixture(engine, tables, provenance)
    with Session(engine) as db:
        assert all(
            db.scalar(select(func.count()).select_from(table)) == 0 for table in Base.metadata.tables.values()
        )


def local_settings(**changes):
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_mode="local",
        allow_dev_auth=True,
        dev_jwt_secret="fictional-sample-import-token-secret-32-characters",
        encryption_key=Fernet.generate_key().decode(),
        audit_hmac_key="fictional-sample-import-audit-secret-32-characters",
        database_url="postgresql+psycopg://fixture:fictional@127.0.0.1:55432/career_kitchen",
    )
    return settings.model_copy(update=changes)


def test_local_import_guard_selects_only_fixed_sample_database():
    target = seed_samples.require_local(local_settings())
    assert target.host == "127.0.0.1" and target.database == "career_kitchen_samples"


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "production"},
        {"environment": "staging"},
        {"auth_mode": "supabase"},
        {"allow_dev_auth": False},
        {"database_url": "postgresql+psycopg://fixture:fictional@remote.invalid/career_kitchen"},
        {
            "database_url": "postgresql+psycopg://fixture:fictional@127.0.0.1/career_kitchen?host=remote.invalid"
        },
        {"database_url": "postgresql+psycopg://fixture:fictional@127.0.0.1/career_kitchen?dbname=production"},
        {
            "database_url": "postgresql+psycopg://fixture:fictional@127.0.0.1/career_kitchen?options=-csearch_path%3Dpublic"
        },
    ],
)
def test_local_import_guard_rejects_hosted_and_ambiguous_targets(changes):
    with pytest.raises(LocalSetupError):
        seed_samples.require_local(local_settings(**changes))
