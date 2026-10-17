from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from app.core.auth import mint_dev_token
from app.core.security import encrypt
from app.core.settings import get_settings
from app.db import pact_models  # noqa: F401
from app.db.base import Base
from app.db.models import Candidate, Organization, OrgMember, User, Vacancy, VacancyACL
from app.main import create_app
from app.services.common import Actor, utcnow
from app.services.profiles import refresh_terms
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def engine():
    url = make_url(get_settings().database_url).set(database="career_kitchen_test")
    schema = "core_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    value = create_engine(
        url, connect_args={"options": f"-c search_path={schema},public"}, pool_size=20, max_overflow=40
    )
    Base.metadata.create_all(value)
    yield value
    value.dispose()
    with admin.connect() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@dataclass
class Market:
    engine: object
    users: list[User]
    candidate: Candidate
    org: Organization
    vacancy: Vacancy
    client: TestClient

    def actor(self, index):
        user = self.users[index]
        return Actor(user.id, utcnow(), tuple(user.platform_roles))

    def call(self, index, method, path, payload=None, key=None, **kwargs):
        user = self.users[index]
        headers = {
            "Authorization": "Bearer " + mint_dev_token(user.id, email=user.verified_email),
            "Idempotency-Key": key or str(uuid4()),
            **kwargs.pop("headers", {}),
        }
        return self.client.request(method, "/v1" + path, json=payload, headers=headers, **kwargs)


@pytest.fixture
def market(engine):
    settings = get_settings()
    with Session(engine, expire_on_commit=False) as db:
        users = [
            User(
                id=str(uuid4()),
                issuer=settings.jwt_issuer,
                subject="",
                verified_email=f"fictional-{i}@example.invalid",
                platform_roles=(["VERIFIER", "OPERATIONS", "RESEARCH_ADMIN", "SUPPORT"] if i == 2 else []),
            )
            for i in range(5)
        ]
        for user in users:
            user.subject = user.id
        db.add_all(users)
        db.flush()
        candidate = Candidate(
            user_id=users[0].id,
            headline="Fictional engineering candidate",
            region="Seattle",
            role_families=["ENGINEERING"],
            employment_types=["FULL_TIME"],
            work_modes=["REMOTE"],
            locations=[],
            currency="USD",
            state="ACTIVE",
            cap=3,
            compensation_floor_cipher=encrypt("70000"),
            terms_accepted=True,
            privacy_accepted=True,
            confirmed_at=utcnow(),
        )
        org = Organization(
            legal_name="Fictional Cascade Robotics",
            display_name="Cascade Robotics (fictional)",
            domain="cascade.example.invalid",
            created_by=users[1].id,
            verification_state="VERIFIED",
        )
        db.add_all([candidate, org])
        db.flush()
        for role in ["ORG_ADMIN", "RECRUITER", "AUTHORIZED_SIGNATORY"]:
            db.add(OrgMember(org_id=org.id, user_id=users[1].id, role=role))
        vacancy = Vacancy(
            org_id=org.id,
            owner_user_id=users[1].id,
            title="Fictional Embedded Engineer",
            description="A fictional embedded engineering role used only for automated tests.",
            role_family="ENGINEERING",
            employment_type="FULL_TIME",
            work_mode="REMOTE",
            pay_min=80000,
            pay_max=120000,
            currency="USD",
            state="ACTIVE",
            cap=2,
            reviewed_by=users[1].id,
        )
        db.add(vacancy)
        db.flush()
        db.add(
            VacancyACL(
                vacancy_id=vacancy.id,
                user_id=users[1].id,
                can_review=True,
                can_edit=True,
                can_approve_policy=True,
            )
        )
        refresh_terms(db, vacancy)
        db.commit()
    with TestClient(create_app(settings, engine)) as client:
        yield Market(engine, users, candidate, org, vacancy, client)
