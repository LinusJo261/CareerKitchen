"""Worker tests run in isolated schemas on the local PostgreSQL test database."""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from app.core.settings import get_settings
from app.db.base import Base
from app.db.models import Candidate, Organization, OrgMember, User, Vacancy, VacancyACL
from app.services.common import digest, utcnow
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def worker_engine():
    url = make_url(get_settings().database_url).set(database="career_kitchen_test")
    schema = "worker_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, connect_args={"connect_timeout": 5, "options": f"-c search_path={schema},public"}
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@dataclass
class WorkerMarket:
    factory: sessionmaker[Session]
    candidate_id: str
    candidate_user_id: str
    owner_id: str
    outsider_id: str
    vacancy_id: str


@pytest.fixture
def worker_market(worker_engine):
    factory = sessionmaker(bind=worker_engine, expire_on_commit=False, autoflush=False)
    with factory.begin() as db:
        users = [
            User(issuer="test", subject=uuid4().hex, verified_email=f"fictional-worker-{i}@example.test")
            for i in range(3)
        ]
        db.add_all(users)
        db.flush()
        candidate = Candidate(
            user_id=users[0].id,
            headline="Fictional worker test engineer",
            state="ACTIVE",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
        )
        org = Organization(
            legal_name="Fictional worker test company",
            display_name="Fictional company",
            domain="example.test",
            created_by=users[1].id,
            verification_state="VERIFIED",
        )
        db.add_all([candidate, org])
        db.flush()
        job = Vacancy(
            org_id=org.id,
            owner_user_id=users[1].id,
            title="Fictional test engineer",
            description="Fictional test responsibilities",
            role_family="ENGINEERING",
            employment_type="FULL_TIME",
            work_mode="REMOTE",
            pay_min=80000,
            pay_max=100000,
            currency="USD",
            state="ACTIVE",
            reviewed_by=users[1].id,
            terms_hash=digest("fictional-worker-terms"),
        )
        db.add(job)
        db.flush()
        db.add_all(
            [
                OrgMember(org_id=org.id, user_id=users[1].id, role="RECRUITER", status="ACTIVE"),
                VacancyACL(vacancy_id=job.id, user_id=users[1].id, can_review=True, can_edit=True),
            ]
        )
        market = WorkerMarket(factory, candidate.id, users[0].id, users[1].id, users[2].id, job.id)
    return market
