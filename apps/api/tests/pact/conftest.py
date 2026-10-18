"""PACT integration fixtures use their own PostgreSQL schema; never customer tables."""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from app.core.security import encrypt
from app.core.settings import get_settings
from app.db.base import Base
from app.db.models import Candidate, Organization, OrgMember, Requirement, User, Vacancy, VacancyACL
from app.db.pact_models import EvidenceClaim  # noqa: F401
from app.services.common import Actor, digest, utcnow
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def pact_engine():
    url = make_url(get_settings().database_url).set(database="career_kitchen_test")
    schema = "pact_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@dataclass
class PactMarket:
    db: Session
    candidate: Candidate
    candidate_actor: Actor
    signatory_actor: Actor
    verifier_actor: Actor
    outsider_actor: Actor
    vacancy: Vacancy
    other_vacancy: Vacancy
    essential: Requirement
    ambiguous: Requirement
    member: OrgMember


@pytest.fixture
def pact_market(pact_engine):
    with Session(pact_engine, expire_on_commit=False) as db:
        users = [
            User(
                id=str(uuid4()),
                issuer="test",
                subject=str(uuid4()),
                verified_email=f"fictional-{i}@example.test",
                platform_roles=["VERIFIER"] if i == 2 else [],
            )
            for i in range(4)
        ]
        db.add_all(users)
        db.flush()
        candidate = Candidate(
            user_id=users[0].id,
            headline="Fictional engineer",
            state="ACTIVE",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            compensation_floor_cipher=encrypt("70000"),
            currency="USD",
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
        )
        organization = Organization(
            legal_name="Fictional PACT Company",
            display_name="Fictional Company",
            domain="example.test",
            created_by=users[1].id,
            verification_state="VERIFIED",
        )
        db.add_all([candidate, organization])
        db.flush()
        member = OrgMember(
            user_id=users[1].id, org_id=organization.id, role="AUTHORIZED_SIGNATORY", status="ACTIVE"
        )
        db.add(member)
        vacancies = [
            Vacancy(
                org_id=organization.id,
                owner_user_id=users[1].id,
                title="Fictional Engineer",
                description="Fictional engineering responsibilities for API tests.",
                role_family="ENGINEERING",
                employment_type="FULL_TIME",
                work_mode="REMOTE",
                pay_min=80000,
                pay_max=100000,
                currency="USD",
                state="ACTIVE",
                reviewed_by=users[1].id,
                terms_hash=digest(["fictional-terms", i]),
            )
            for i in range(2)
        ]
        db.add_all(vacancies)
        db.flush()
        db.add_all(
            [
                VacancyACL(
                    vacancy_id=v.id,
                    user_id=users[1].id,
                    can_review=True,
                    can_edit=True,
                    can_approve_policy=True,
                )
                for v in vacancies
            ]
        )
        essential = Requirement(
            vacancy_id=vacancies[0].id,
            key="engineering_license",
            description="License",
            kind="ESSENTIAL",
            lawful_reason="Job-related licensed practice",
            reviewed_by=users[1].id,
        )
        ambiguous = Requirement(
            vacancy_id=vacancies[1].id,
            key="degree_preference",
            description="Degree preference",
            kind="AMBIGUOUS",
            reviewed_by=users[1].id,
        )
        db.add_all([essential, ambiguous])
        db.flush()
        actors = [Actor(u.id, utcnow(), tuple(u.platform_roles)) for u in users]
        yield PactMarket(db, candidate, *actors, vacancies[0], vacancies[1], essential, ambiguous, member)
