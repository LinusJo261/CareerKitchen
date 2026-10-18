"""Import a large, explicitly synthetic market into its own local PostgreSQL database.

No live consent, account verification, hiring interaction or outcome is manufactured.
The downloaded MIT source and all generated rows remain outside version control.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from datetime import timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from alembic import command
from alembic.config import Config
from app.core.settings import Settings, get_settings
from app.db.base import Base
from app.db.models import (
    AuditEvent,
    Candidate,
    CandidateSkill,
    IdempotencyRecord,
    Organization,
    OrgMember,
    OutboxEvent,
    Requirement,
    Skill,
    User,
    Vacancy,
    VacancyACL,
)
from app.services.common import digest, lock_scopes, utcnow
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from scripts.local_dev import require_local as require_local_configuration
from scripts.sample_dataset import DEFAULT_SOURCE, load_source, validate_job, validate_resume

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATABASE = "career_kitchen_samples"
MARKER = "career-kitchen-synthetic-samples-v1"
ROUTE = "sample-import/v1"
CLIENT_KEY = "initial-import"
LIMIT = 100_000


def identity(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://career-kitchen.example.invalid/samples/v1/{label}"))


def require_local(settings: Settings) -> URL:
    """Validate the configuration before substituting our fixed, separate target."""
    return require_local_configuration(settings).set(database=SAMPLE_DATABASE)


def _write(db: Session, model: type, rows: list[dict]) -> None:
    if rows:
        db.execute(insert(model.__table__), rows)


def _row(label: str, **values: object) -> dict:
    return {"id": identity(label), "version": 1, **values}


def _audit(
    db: Session, model: type, row: dict, payload: dict, *, related: dict[str, list[dict]] | None = None
) -> None:
    """Bulk equivalent of common.emit, signed using its exact integrity contract.

    Each event describes an aggregate creation, including every dependent row via
    counts and a content hash. No profile text or credentials enter the outbox.
    The caller inserts buffered events with the aggregate in the same transaction.
    """
    children = related or {}
    safe = {
        "entity_id": row["id"],
        "entity_type": model.__tablename__,
        "version": 1,
        "synthetic": True,
        "related_counts": {name: len(rows) for name, rows in children.items()},
        "records_sha256": digest({"root": row, "related": children}),
        **payload,
    }
    after_hash = digest(safe)
    org_id = row.get("org_id") if model is Vacancy else row["id"] if model is Organization else None
    integrity = digest(
        [identity("importer"), org_id, "sample.imported", model.__tablename__, row["id"], after_hash, MARKER]
    )
    key = get_settings().audit_hmac_key.get_secret_value()
    audit = _row(
        f"audit-{model.__tablename__}-{row['id']}",
        actor_id=identity("importer"),
        org_id=org_id,
        action="sample.imported",
        entity_type=model.__tablename__,
        entity_id=row["id"],
        request_id=MARKER,
        after_hash=after_hash,
        integrity_hash=hmac.new(key.encode(), integrity.encode(), hashlib.sha256).hexdigest(),
    )
    event = _row(
        f"outbox-{model.__tablename__}-{row['id']}",
        aggregate_id=row["id"],
        kind="sample.imported",
        payload=safe,
    )
    # Buffers are scoped to this Session/transaction, never global or committed early.
    db.info.setdefault("sample_audits", []).append(audit)
    db.info.setdefault("sample_events", []).append(event)


def _flush_events(db: Session) -> None:
    audits = db.info.pop("sample_audits", [])
    events = db.info.pop("sample_events", [])
    _write(db, AuditEvent, audits)
    _write(db, OutboxEvent, events)


def _family(role: str) -> str:
    lowered = role.lower()
    for words, family in [
        (("engineer", "developer"), "ENGINEERING"),
        (("data", "bi analyst", "business analyst"), "DATA"),
        (("marketing", "marketer", "content"), "MARKETING"),
        (("sales", "account executive", "business development"), "SALES"),
        (("product",), "PRODUCT"),
        (("support",), "SUPPORT"),
        (("financial", "accountant", "fp&a"), "FINANCE"),
    ]:
        if any(word in lowered for word in words):
            return family
    return "OPERATIONS"


def import_samples(
    db: Session,
    tables: dict[str, list[dict]],
    provenance: dict,
    *,
    candidates: int = 20_000,
    vacancies: int = 20_000,
    batch_size: int = 500,
) -> dict:
    """Create once, or replay an identical receipt, inside the caller's transaction.

    CLI ownership/host checks are outside this internal primitive so integration
    tests can use isolated PostgreSQL schemas. Never call this on a live market.
    """
    try:
        return _import_samples(
            db, tables, provenance, candidates=candidates, vacancies=vacancies, batch_size=batch_size
        )
    finally:
        db.info.pop("sample_audits", None)
        db.info.pop("sample_events", None)


def _import_samples(
    db: Session,
    tables: dict[str, list[dict]],
    provenance: dict,
    *,
    candidates: int,
    vacancies: int,
    batch_size: int,
) -> dict:
    if any(type(count) is not int or not 1 <= count <= LIMIT for count in (candidates, vacancies)):
        raise ValueError(f"Sample counts must each be in 1..{LIMIT}")
    if type(batch_size) is not int or not 1 <= batch_size <= 1000:
        raise ValueError("Batch size must be in 1..1000")
    if len(get_settings().audit_hmac_key.get_secret_value()) < 32:
        raise ValueError("Sample imports require a configured audit HMAC key")
    if set(tables) != {"resumes", "jobs"} or not tables["resumes"] or not tables["jobs"]:
        raise ValueError("Only nonempty synthetic resumes and jobs may be imported")
    tables = {
        "resumes": [validate_resume(row) for row in tables["resumes"]],
        "jobs": [validate_job(row) for row in tables["jobs"]],
    }
    for name in ("resumes", "jobs"):
        key = "resume_id" if name == "resumes" else "job_id"
        if len({row[key] for row in tables[name]}) != len(tables[name]):
            raise ValueError("Duplicate source record IDs are not allowed")
    request_hash = digest(
        {
            "schema": MARKER,
            "candidates": candidates,
            "vacancies": vacancies,
            "source": provenance,
            "tables": tables,
        }
    )
    lock_scopes(db, MARKER)
    receipt = db.get(IdempotencyRecord, (identity("importer"), ROUTE, CLIENT_KEY))
    if receipt:
        if receipt.request_hash != request_hash:
            raise ValueError("Sample database already contains a different import; use a fresh database")
        return json.loads(receipt.response_json)
    # Do not mix source fixtures with pre-existing identities or tenant state.
    if any(db.scalar(select(1).select_from(table).limit(1)) for table in Base.metadata.tables.values()):
        raise ValueError("Initial sample import requires an empty database")
    if any(db.info.get(key) for key in ("sample_audits", "sample_events")):
        raise ValueError("Sample event buffer must be empty")

    source_hash = provenance["manifest_sha256"]
    common_payload = {"source_manifest_sha256": source_hash, "import_version": MARKER}
    controls = [
        _row(
            label,
            issuer=get_settings().jwt_issuer,
            subject=identity(label),
            verified_email=f"{label}@samples.example.invalid",
            platform_roles=[],
            status="DEACTIVATED" if label == "importer" else "ACTIVE",
        )
        for label in ("importer", "employer")
    ]
    _write(db, User, controls)
    for control in controls:
        _audit(db, User, control, common_payload)

    source_skills = sorted(
        {skill.lower() for row in tables["resumes"] for skill in row["skills"]}
        | {
            skill.lower()
            for row in tables["jobs"]
            for skill in row["must_have_skills"] + row["nice_to_have_skills"]
        }
    )
    skill_rows = [
        _row(f"skill-{name}", name=name, aliases=[], ontology_version="synthetic-samples-v1")
        for name in source_skills
    ]
    _write(db, Skill, skill_rows)
    for skill in skill_rows:
        _audit(db, Skill, skill, common_payload)
    _flush_events(db)

    org_count = (vacancies + 99) // 100
    for start in range(0, org_count, batch_size):
        organizations, memberships = [], []
        for index in range(start + 1, min(start + batch_size, org_count) + 1):
            org = _row(
                f"org-{index:06}",
                legal_name=f"Synthetic Sample Company {index:06}",
                display_name=f"Synthetic Sample Company {index:06}",
                domain=f"company-{index:06}.samples.example.invalid",
                created_by=identity("employer"),
                verification_state="PENDING_VERIFICATION",
                active_role_capacity=3,
                matching_learning_opt_in=False,
                matching_learning_consent_version=1,
            )
            members = [
                _row(
                    f"member-{index:06}-{role}",
                    org_id=org["id"],
                    user_id=identity("employer"),
                    role=role,
                    status="ACTIVE",
                    source_hash=digest([MARKER, "synthetic membership"]),
                )
                for role in ("ORG_ADMIN", "RECRUITER")
            ]
            organizations.append(org)
            memberships.extend(members)
            _audit(db, Organization, org, common_payload, related={"org_members": members})
        _write(db, Organization, organizations)
        _write(db, OrgMember, memberships)
        _flush_events(db)

    for start in range(0, candidates, batch_size):
        users, profiles, assertions = [], [], []
        for index in range(start, min(start + batch_size, candidates)):
            source = tables["resumes"][index % len(tables["resumes"])]
            replica = index // len(tables["resumes"]) + 1
            ordinal = f"{index + 1:06}"
            user = _row(
                f"candidate-user-{ordinal}",
                issuer=get_settings().jwt_issuer,
                subject=identity(f"candidate-user-{ordinal}"),
                verified_email=f"candidate-{ordinal}@samples.example.invalid",
                platform_roles=[],
            )
            profile = _row(
                f"candidate-{ordinal}",
                user_id=user["id"],
                headline=f"[SYNTHETIC {ordinal}] {source['seniority']} {source['role']}",
                summary=(
                    f"SYNTHETIC SAMPLE. Source {source['resume_id']}; variant {replica}. "
                    "No real applicant, consent or outcome.\n"
                    + source["summary"]
                    + f"\nSynthetic source education: {source['education']}. "
                    + f"Industry: {source['industry']}. Years of experience: {source['years_experience']}.\n"
                    + "\n".join(source["experience_bullets"])
                ),
                region="Sample region",
                state="DRAFT",
                cap=3,
                role_families=[_family(source["role"])],
                employment_types=["FULL_TIME"],
                work_modes=["REMOTE"],
                locations=[],
                currency="USD",
                # The source has no dates or institutions for the structured API
                # history contract. Preserve its text in summary without inventing them.
                experiences=[],
                education=[],
                terms_accepted=False,
                privacy_accepted=False,
                matching_learning_opt_in=False,
                matching_learning_consent_version=1,
            )
            candidate_skills = [
                _row(
                    f"candidate-skill-{ordinal}-{name}",
                    candidate_id=profile["id"],
                    skill_id=identity(f"skill-{name}"),
                    level=1,
                    confirmed=False,
                )
                for name in sorted({skill.lower() for skill in source["skills"]})
            ]
            users.append(user)
            profiles.append(profile)
            assertions.extend(candidate_skills)
            _audit(
                db,
                Candidate,
                profile,
                {**common_payload, "source_id": source["resume_id"], "replica": replica},
                related={"users": [user], "candidate_skills": candidate_skills},
            )
        _write(db, User, users)
        _write(db, Candidate, profiles)
        _write(db, CandidateSkill, assertions)
        _flush_events(db)

    for start in range(0, vacancies, batch_size):
        jobs, requirements, acls = [], [], []
        for index in range(start, min(start + batch_size, vacancies)):
            source = tables["jobs"][index % len(tables["jobs"])]
            replica = index // len(tables["jobs"]) + 1
            ordinal = f"{index + 1:06}"
            job = _row(
                f"vacancy-{ordinal}",
                org_id=identity(f"org-{index // 100 + 1:06}"),
                owner_user_id=identity("employer"),
                title=f"[SYNTHETIC {ordinal}] {source['job_title']}",
                description=(
                    f"SYNTHETIC SAMPLE. Source {source['job_id']}; variant {replica}. "
                    "No real vacancy or employment promise. Pay and location are fixture values.\n"
                    + source["description"]
                    + "\nSynthetic source responsibilities:\n"
                    + "\n".join(source["responsibilities"])
                    + "\nUnreviewed source requirements:\n"
                    + "\n".join(source["requirements"])
                ),
                role_family=_family(source["job_title"]),
                employment_type="FULL_TIME",
                work_mode="REMOTE",
                location_region="Sample region",
                pay_min=0,
                pay_max=0,
                currency="USD",
                compensation_period="ANNUAL",
                openings_total=1,
                openings_remaining=1,
                cap=3,
                state="DRAFT",
            )
            # Dataset must-have labels do not establish a lawful essential requirement.
            reqs = [
                _row(
                    f"requirement-{ordinal}-{name}",
                    vacancy_id=job["id"],
                    key=name,
                    description="Unreviewed synthetic source skill; preference only",
                    kind="PREFERENCE",
                )
                for name in sorted(
                    {skill.lower() for skill in source["must_have_skills"] + source["nice_to_have_skills"]}
                )
            ]
            acl = _row(
                f"acl-{ordinal}",
                vacancy_id=job["id"],
                user_id=identity("employer"),
                can_review=True,
                can_edit=True,
                can_approve_policy=False,
            )
            # Match refresh_terms() exactly, including database Numeric string formatting.
            job["terms_hash"] = digest(
                {
                    "version": 1,
                    "title": job["title"],
                    "description": job["description"],
                    "pay_min": "0.00",
                    "pay_max": "0.00",
                    "currency": "USD",
                    "compensation_period": "ANNUAL",
                    "work_mode": "REMOTE",
                    "location": "Sample region",
                    "employment_type": "FULL_TIME",
                    "start_from": None,
                    "start_until": None,
                    "requirements": [
                        (r["key"], r["kind"], r["description"], 1)
                        for r in sorted(reqs, key=lambda r: r["id"])
                    ],
                }
            )
            jobs.append(job)
            requirements.extend(reqs)
            acls.append(acl)
            _audit(
                db,
                Vacancy,
                job,
                {**common_payload, "source_id": source["job_id"], "replica": replica},
                related={"vacancy_requirements": reqs, "vacancy_acl": [acl]},
            )
        _write(db, Vacancy, jobs)
        _write(db, Requirement, requirements)
        _write(db, VacancyACL, acls)
        _flush_events(db)

    result = {
        "synthetic": True,
        "database": SAMPLE_DATABASE,
        "import_version": MARKER,
        "candidates": candidates,
        "vacancies": vacancies,
        "organizations": org_count,
        "unique_source_resumes": min(candidates, len(tables["resumes"])),
        "unique_source_jobs": min(vacancies, len(tables["jobs"])),
        "additional_candidate_variants": max(0, candidates - len(tables["resumes"])),
        "additional_job_variants": max(0, vacancies - len(tables["jobs"])),
        "state": "DRAFT",
        "learning_opt_in": False,
        "source": provenance,
        "request_hash": request_hash,
        "employer_id": identity("employer"),
        "first_candidate_user_id": identity("candidate-user-000001"),
    }
    db.add(
        IdempotencyRecord(
            actor_id=identity("importer"),
            route=ROUTE,
            client_key=CLIENT_KEY,
            request_hash=request_hash,
            response_json=json.dumps(result, sort_keys=True),
            status_code=201,
            expires_at=utcnow() + timedelta(days=36500),
        )
    )
    db.flush()
    return result


def seed(source: Path = DEFAULT_SOURCE, *, candidates: int = 20_000, vacancies: int = 20_000) -> dict:
    settings = get_settings()
    target_url = require_local(settings)
    tables, provenance = load_source(source)
    target = create_engine(target_url, connect_args={"connect_timeout": 5})
    admin = create_engine(
        target_url.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5}
    )
    try:
        with admin.connect() as conn:
            # Serialize database creation separately from transaction-scoped import locking.
            conn.execute(text("SELECT pg_advisory_lock(2077110934)"))
            try:
                exists = conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": SAMPLE_DATABASE}
                )
                if not exists:
                    conn.execute(text(f'CREATE DATABASE "{SAMPLE_DATABASE}"'))
                    with target.begin() as setup:
                        setup.execute(text("CREATE TABLE ck_sample_marker (marker text PRIMARY KEY)"))
                        setup.execute(
                            text("INSERT INTO ck_sample_marker VALUES (:marker)"), {"marker": MARKER}
                        )
                with target.begin() as setup:
                    if not setup.scalar(text("SELECT to_regclass('public.ck_sample_marker')")):
                        raise ValueError("Refusing to modify a database without the sample ownership marker")
                    markers = list(setup.scalars(text("SELECT marker FROM ck_sample_marker")))
                    if markers != [MARKER]:
                        raise ValueError("Refusing to modify an unrecognized sample database")
                    config = Config(str(ROOT / "alembic.ini"))
                    config.attributes["connection"] = setup
                    command.upgrade(config, "head")
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(2077110934)"))
        with Session(target) as db, db.begin():
            return import_samples(db, tables, provenance, candidates=candidates, vacancies=vacancies)
    finally:
        target.dispose()
        admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--candidates", type=int, default=20_000)
    parser.add_argument("--vacancies", type=int, default=20_000)
    parser.add_argument("--report", type=Path, default=Path(".local/sample-import-report.json"))
    options = parser.parse_args()
    try:
        result = seed(options.source, candidates=options.candidates, vacancies=options.vacancies)
    except Exception as error:
        # SQLAlchemy exceptions can contain configured credentials/SQL parameters.
        raise SystemExit(
            f"Sample import failed ({type(error).__name__}); no partial import was committed."
        ) from None
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
