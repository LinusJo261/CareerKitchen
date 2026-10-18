"""Prepare the marked local synthetic market for an interactive demonstration.

Only career_kitchen_samples is eligible. Simulated consent, confirmations and
company verification are explicitly fictional fixture state. No participant
choices, mutual matches, offers, starts or learning opt-ins are manufactured.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from app.core.settings import get_settings
from app.db.models import (
    AuditEvent,
    Candidate,
    CandidateSkill,
    IdempotencyRecord,
    Organization,
    OutboxEvent,
    Requirement,
    User,
    Vacancy,
)
from app.services import clearing
from app.services.common import Actor, digest, lock_scopes, utcnow
from sqlalchemy import create_engine, func, insert, select, update
from sqlalchemy.orm import Session

from app.api.demo import (
    DEMO_KEY,
    DEMO_MARKER,
    DEMO_ROUTE,
    VACANCY_LIMIT,
    require_sample_database,
    sample_identity,
)
from scripts.seed_samples import require_local

BATCH_SIZE = 500


def _audit(db: Session, actor: Actor, model: type, rows: list[dict], payloads: dict[str, dict]) -> None:
    """Bulk common.emit equivalent; one signed aggregate event per changed root."""
    key = get_settings().audit_hmac_key.get_secret_value()
    if len(key) < 32:
        raise ValueError("Sample demonstration requires the configured audit integrity key")
    audits, events = [], []
    for row in rows:
        payload = {
            "entity_id": row["id"],
            "entity_type": model.__tablename__,
            "version": row["version"],
            "synthetic": True,
            "demo_version": DEMO_MARKER,
            "fictional_eligibility_only": True,
            "learning_opt_in": False,
            **payloads.get(row["id"], {}),
        }
        org_id = row.get("org_id") if model is Vacancy else row["id"] if model is Organization else None
        after_hash = digest(payload)
        signed = digest(
            [
                actor.user_id,
                org_id,
                "sample.demo_prepared",
                model.__tablename__,
                row["id"],
                after_hash,
                actor.request_id,
            ]
        )
        audits.append(
            {
                "id": sample_identity(f"demo-audit-{model.__tablename__}-{row['id']}"),
                "version": 1,
                "actor_id": actor.user_id,
                "org_id": org_id,
                "action": "sample.demo_prepared",
                "entity_type": model.__tablename__,
                "entity_id": row["id"],
                "request_id": actor.request_id,
                "after_hash": after_hash,
                "integrity_hash": hmac.new(key.encode(), signed.encode(), hashlib.sha256).hexdigest(),
            }
        )
        events.append(
            {
                "id": sample_identity(f"demo-event-{model.__tablename__}-{row['id']}"),
                "version": 1,
                "aggregate_id": row["id"],
                "kind": "sample.demo_prepared",
                "payload": payload,
            }
        )
    if audits:
        db.execute(insert(AuditEvent.__table__), audits)
        db.execute(insert(OutboxEvent.__table__), events)


def _batches(db: Session, model: type):
    previous = ""
    while True:
        rows = list(
            db.execute(
                select(model.__table__)
                .where(model.id > previous)
                .order_by(model.id)
                .limit(BATCH_SIZE)
                .with_for_update()
            ).mappings()
        )
        if not rows:
            return
        if any(row["version"] != 1 for row in rows):
            raise ValueError("Sample fixture changed during preparation; no preparation was committed")
        previous = rows[-1]["id"]
        yield [dict(row) for row in rows]


def _preflight(db: Session, imported: dict) -> None:
    """Accept the untouched importer fixture only; refuse mixed or real records."""
    for model, key, label in (
        (Candidate, "candidates", "candidate"),
        (Vacancy, "vacancies", "vacancy"),
        (Organization, "organizations", "org"),
    ):
        rows = list(db.execute(select(model.id, model.version)).all())
        expected = {sample_identity(f"{label}-{index:06}") for index in range(1, imported[key] + 1)}
        if {row.id for row in rows} != expected or any(row.version != 1 for row in rows):
            raise ValueError("Sample preparation requires the unchanged synthetic import")
    if db.scalar(
        select(func.count()).select_from(User).where(~User.verified_email.like("%@samples.example.invalid"))
    ):
        raise ValueError("Sample database contains an unrelated identity")
    for model in (Candidate, Organization):
        if db.scalar(select(model.id).where(model.matching_learning_opt_in.is_(True)).limit(1)):
            raise ValueError("Fictional sample demonstration cannot carry learning consent")
    if db.scalar(select(Candidate.id).where(Candidate.state != "DRAFT").limit(1)) or db.scalar(
        select(Vacancy.id).where(Vacancy.state != "DRAFT").limit(1)
    ):
        raise ValueError("Sample preparation requires draft import state")


def activate_samples(db: Session, settings) -> dict:
    """Idempotent transactional primitive; database/marker checks always apply."""
    imported = require_sample_database(db, settings)
    lock_scopes(db, DEMO_MARKER)
    request_hash = digest([DEMO_MARKER, imported["request_hash"]])
    receipt = db.get(IdempotencyRecord, (sample_identity("importer"), DEMO_ROUTE, DEMO_KEY))
    if receipt:
        if receipt.request_hash != request_hash:
            raise ValueError("Sample demonstration receipt conflicts with this import")
        return json.loads(receipt.response_json)
    _preflight(db, imported)
    now = utcnow()
    actor = Actor(sample_identity("importer"), now, request_id=DEMO_MARKER)
    for rows in _batches(db, Organization):
        changes = []
        payloads = {}
        for row in rows:
            changes.append(
                {
                    "id": row["id"],
                    "version": row["version"] + 1,
                    "verification_state": "VERIFIED",
                    "verified_by": actor.user_id,
                    "verification_source_hash": digest([DEMO_MARKER, "FICTIONAL company verification"]),
                    "active_role_capacity": 100,
                }
            )
            payloads[row["id"]] = {"fictional_company_verification": True, "active_role_capacity": 100}
        db.execute(update(Organization), changes)
        _audit(db, actor, Organization, changes, payloads)
    for rows in _batches(db, Candidate):
        candidate_ids = [row["id"] for row in rows]
        skills = list(
            db.execute(
                select(CandidateSkill.__table__).where(CandidateSkill.candidate_id.in_(candidate_ids))
            ).mappings()
        )
        grouped = defaultdict(list)
        skill_changes = []
        for skill in skills:
            change = {"id": skill["id"], "version": skill["version"] + 1, "confirmed": True}
            skill_changes.append(change)
            grouped[skill["candidate_id"]].append(change)
        if skill_changes:
            db.execute(update(CandidateSkill), skill_changes)
        changes = [
            {
                "id": row["id"],
                "version": row["version"] + 1,
                "state": "ACTIVE",
                "terms_accepted": True,
                "privacy_accepted": True,
                "confirmed_at": now,
            }
            for row in rows
        ]
        db.execute(update(Candidate), changes)
        _audit(
            db,
            actor,
            Candidate,
            changes,
            {
                row["id"]: {
                    "fictional_participation_consent": True,
                    "fictional_profile_confirmation": True,
                    "fictional_skill_confirmation": True,
                    "candidate_skill_count": len(grouped[row["id"]]),
                    "candidate_skill_versions_sha256": digest(
                        sorted(grouped[row["id"]], key=lambda value: value["id"])
                    ),
                }
                for row in rows
            },
        )
    for rows in _batches(db, Vacancy):
        requirements = defaultdict(list)
        for requirement in db.scalars(
            select(Requirement)
            .where(Requirement.vacancy_id.in_([row["id"] for row in rows]))
            .order_by(Requirement.id)
        ):
            requirements[requirement.vacancy_id].append(
                (requirement.key, requirement.kind, requirement.description, requirement.version)
            )
        changes = []
        for row in rows:
            version = row["version"] + 1
            terms_hash = digest(
                {
                    "version": version,
                    "title": row["title"],
                    "description": row["description"],
                    "pay_min": str(row["pay_min"]),
                    "pay_max": str(row["pay_max"]),
                    "currency": row["currency"],
                    "compensation_period": row["compensation_period"],
                    "work_mode": row["work_mode"],
                    "location": row["location_region"],
                    "employment_type": row["employment_type"],
                    "start_from": row["start_from"],
                    "start_until": row["start_until"],
                    "requirements": requirements[row["id"]],
                }
            )
            changes.append(
                {
                    "id": row["id"],
                    "version": version,
                    "state": "ACTIVE",
                    "reviewed_by": sample_identity("employer"),
                    "terms_hash": terms_hash,
                }
            )
        db.execute(update(Vacancy), changes)
        _audit(
            db,
            actor,
            Vacancy,
            [{**change, "org_id": row["org_id"]} for row, change in zip(rows, changes, strict=True)],
            {row["id"]: {"fictional_vacancy_review": True} for row in rows},
        )
    db.expire_all()
    first_candidate = db.get(Candidate, sample_identity("candidate-000001"))
    first_org = sample_identity("org-000001")
    targets = list(
        db.scalars(
            select(Vacancy.id)
            .where(Vacancy.org_id == first_org, Vacancy.state == "ACTIVE")
            .order_by(Vacancy.id)
            .limit(VACANCY_LIMIT)
        )
    )
    candidate_targets = list(
        db.scalars(
            select(Vacancy.id)
            .where(
                Vacancy.org_id == first_org,
                Vacancy.state == "ACTIVE",
                Vacancy.role_family.in_(first_candidate.role_families),
            )
            .order_by(Vacancy.id)
            .limit(VACANCY_LIMIT)
        )
    )
    if not candidate_targets:
        candidate_targets = list(
            db.scalars(
                select(Vacancy.id)
                .where(Vacancy.state == "ACTIVE", Vacancy.role_family.in_(first_candidate.role_families))
                .order_by(Vacancy.id)
                .limit(VACANCY_LIMIT)
            )
        )
    if candidate_targets and all(db.get(Vacancy, item).org_id == first_org for item in candidate_targets):
        targets = candidate_targets
    # The default applicant receives actual executor-issued cards, never fabricated
    # decisions. Selecting one candidate avoids competition starving its demo inbox.
    issued = (
        clearing.reconcile(
            db, actor, vacancy_ids=candidate_targets, candidate_ids=[first_candidate.id], pool_limit=1
        )
        if candidate_targets
        else []
    )
    result = {
        "ready": True,
        "synthetic": True,
        "demo_version": DEMO_MARKER,
        "candidates": imported["candidates"],
        "vacancies": imported["vacancies"],
        "organizations": imported["organizations"],
        "organization_id": first_org,
        "candidate_user_id": first_candidate.user_id,
        "vacancy_ids": targets,
        "initial_decision_cards": len(issued),
        "learning_opt_in": False,
        "fictional_eligibility_only": True,
        "double_opt_in_required": True,
        "request_hash": request_hash,
    }
    db.add(
        IdempotencyRecord(
            actor_id=actor.user_id,
            route=DEMO_ROUTE,
            client_key=DEMO_KEY,
            request_hash=request_hash,
            response_json=json.dumps(result, sort_keys=True),
            status_code=201,
            expires_at=now + timedelta(days=36500),
        )
    )
    db.flush()
    return result


def prepare() -> dict:
    settings = get_settings()
    target_url = require_local(settings)
    target = create_engine(target_url, connect_args={"connect_timeout": 5})
    prepared_settings = settings.model_copy(
        update={"database_url": target_url.render_as_string(hide_password=False)}
    )
    try:
        with Session(target) as db, db.begin():
            return activate_samples(db, prepared_settings)
    finally:
        target.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path(".local/sample-demo-report.json"))
    options = parser.parse_args()
    try:
        result = prepare()
    except Exception as error:
        raise SystemExit(
            f"Sample demonstration preparation failed ({type(error).__name__}); no partial preparation committed."
        ) from None
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
