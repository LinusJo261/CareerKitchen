"""Build a separate, deterministic, explicitly fictional development database."""

from __future__ import annotations

import argparse
from uuid import NAMESPACE_URL, uuid5

from alembic import command
from alembic.config import Config
from app.core.security import encrypt
from app.core.settings import get_settings
from app.db.models import (
    Candidate,
    CandidateSkill,
    Organization,
    OrgMember,
    Requirement,
    Skill,
    User,
    Vacancy,
    VacancyACL,
)
from app.services.common import digest, utcnow
from app.services.profiles import refresh_terms
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

DEMO_DATABASE = "career_kitchen_demo"
MARKER = "career-kitchen-fictional-v1"


def identity(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://career-kitchen.example.invalid/fictional/{label}"))


def seed(reset: bool = False) -> dict:
    settings = get_settings()
    source = make_url(settings.database_url)
    if (
        settings.environment not in {"development", "test"}
        or settings.auth_mode != "local"
        or source.host not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise RuntimeError(
            "Fictional demo is restricted to local PostgreSQL and explicit development authentication"
        )
    target = create_engine(source.set(database=DEMO_DATABASE))
    admin = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": DEMO_DATABASE}
            )
            if exists and reset:
                with target.connect() as current:
                    marked = current.scalar(text("SELECT marker FROM ck_demo_marker LIMIT 1"))
                    if marked != MARKER:
                        raise RuntimeError("Refusing to reset an unrecognized database")
                target.dispose()
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"
                    ),
                    {"name": DEMO_DATABASE},
                )
                conn.execute(text(f'DROP DATABASE "{DEMO_DATABASE}"'))
                exists = None
            if exists:
                raise RuntimeError("Demo already exists; use --reset to rebuild this fictional database")
            conn.execute(text(f'CREATE DATABASE "{DEMO_DATABASE}"'))
        config = Config("alembic.ini")
        with target.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            conn.execute(text("CREATE TABLE ck_demo_marker (marker text PRIMARY KEY)"))
            conn.execute(text("INSERT INTO ck_demo_marker(marker) VALUES (:marker)"), {"marker": MARKER})
        with Session(target, expire_on_commit=False) as db:
            users = []
            labels = ["employer", "verifier", "operations"] + [f"candidate-{i:02}" for i in range(1, 31)]
            for label in labels:
                user = User(
                    id=identity(label),
                    issuer=settings.jwt_issuer,
                    subject=identity(label),
                    verified_email=f"{label}@fictional.example.invalid",
                    platform_roles=["VERIFIER"]
                    if label == "verifier"
                    else ["OPERATIONS", "RESEARCH_ADMIN", "SUPPORT"]
                    if label == "operations"
                    else [],
                )
                db.add(user)
                users.append(user)
            db.flush()
            skills = []
            for name in ["python", "embedded_c", "robotics", "postgresql", "hardware"]:
                skill = Skill(id=identity("skill-" + name), name=name)
                db.add(skill)
                skills.append(skill)
            orgs = []
            for index, name in enumerate(["Cascade Robotics", "Rainier Systems", "Cedar Data"]):
                org = Organization(
                    id=identity(f"org-{index}"),
                    legal_name=name + " (fictional)",
                    display_name=name + " (fictional)",
                    domain=f"org-{index}.fictional.example.invalid",
                    created_by=users[0].id,
                    verification_state="VERIFIED",
                    verification_source_hash=digest("FICTIONAL FIXTURE, not real company verification"),
                    verified_by=users[1].id,
                    active_role_capacity=5,
                )
                db.add(org)
                orgs.append(org)
            db.flush()
            for org in orgs:
                for role in ["ORG_ADMIN", "RECRUITER", "AUTHORIZED_SIGNATORY"]:
                    db.add(
                        OrgMember(
                            id=identity(f"member-{org.id}-{role}"),
                            org_id=org.id,
                            user_id=users[0].id,
                            role=role,
                            approved_by=users[1].id,
                            source_hash=digest("Fictional authority fixture"),
                        )
                    )
            for index, user in enumerate(users[3:], 1):
                candidate = Candidate(
                    id=identity(f"profile-{index}"),
                    user_id=user.id,
                    headline=f"Fictional Candidate {index:02} — Engineering",
                    summary="Synthetic development profile. No real person, credentials or hiring outcome.",
                    region="Seattle",
                    state="ACTIVE" if index <= 27 else "PAUSED",
                    cap=2 + index % 4,
                    role_families=["ENGINEERING"],
                    employment_types=["FULL_TIME"],
                    work_modes=["REMOTE", "HYBRID"],
                    locations=["Seattle"],
                    compensation_floor_cipher=encrypt(str(65000 + index * 1000)),
                    currency="USD",
                    terms_accepted=True,
                    privacy_accepted=True,
                    confirmed_at=utcnow(),
                )
                db.add(candidate)
                db.flush()
                for skill in skills[: 1 + index % len(skills)]:
                    db.add(
                        CandidateSkill(
                            id=identity(f"assertion-{index}-{skill.name}"),
                            candidate_id=candidate.id,
                            skill_id=skill.id,
                            level=1 + index % 5,
                        )
                    )
            for index in range(10):
                vacancy = Vacancy(
                    id=identity(f"vacancy-{index}"),
                    org_id=orgs[index % 3].id,
                    owner_user_id=users[0].id,
                    title=["Robotics Hardware Engineer", "Embedded Systems Developer", "Backend Engineer"][
                        index % 3
                    ]
                    + f" — fictional team {index + 1}",
                    description="Fictional engineering responsibilities and compensation for development only. No real vacancy, application or employment promise.",
                    role_family="ENGINEERING",
                    employment_type="FULL_TIME",
                    work_mode="REMOTE",
                    location_region="Seattle",
                    pay_min=90000,
                    pay_max=125000,
                    currency="USD",
                    cap=2 + index % 3,
                    state="DRAFT" if index == 0 else "CLOSED" if index == 9 else "ACTIVE",
                    reviewed_by=users[0].id,
                )
                db.add(vacancy)
                db.flush()
                db.add(
                    VacancyACL(
                        id=identity(f"acl-{index}"),
                        vacancy_id=vacancy.id,
                        user_id=users[0].id,
                        can_review=True,
                        can_edit=True,
                        can_approve_policy=True,
                    )
                )
                db.add(
                    Requirement(
                        id=identity(f"requirement-{index}"),
                        vacancy_id=vacancy.id,
                        key=skills[index % 5].name,
                        description="Fictional preferred skill, human-reviewed fixture",
                        kind="PREFERENCE",
                        reviewed_by=users[0].id,
                    )
                )
                refresh_terms(db, vacancy)
            db.commit()
        summary = {
            "fictional": True,
            "database": DEMO_DATABASE,
            "candidates": 30,
            "organizations": 3,
            "vacancies": 10,
            "employer_id": identity("employer"),
            "candidate_id": identity("candidate-01"),
            "fixture_hash": digest([MARKER, labels, [identity(f"vacancy-{i}") for i in range(10)]]),
        }
        return summary
    finally:
        target.dispose()
        admin.dispose()


if __name__ == "__main__":
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="Reset only the recognized local fictional demo database"
    )
    print(json.dumps(seed(parser.parse_args().reset), indent=2))
