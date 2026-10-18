"""Initialize a dedicated hosted synthetic database; never accepts a live database name."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from app.core.settings import get_settings
from app.db.models import User
from app.services.common import Actor, emit, lock_scopes, utcnow
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.api.demo import IMPORT_MARKER, SAMPLE_DATABASE, sample_identity
from scripts.prepare_sample_demo import activate_samples
from scripts.sample_dataset import DEFAULT_SOURCE, load_source
from scripts.seed_samples import import_samples


def bootstrap() -> None:
    settings = get_settings()
    url = make_url(settings.migration_database_url or settings.database_url)
    if not (
        settings.sample_demo_enabled
        and settings.auth_mode == "supabase"
        and settings.environment in {"production", "staging"}
        and url.database == SAMPLE_DATABASE
    ):
        raise ValueError("Explicit hosted sample configuration is required")
    tables, provenance = load_source(DEFAULT_SOURCE)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target = create_engine(url)
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(2077110934)"))
            try:
                if not connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": SAMPLE_DATABASE}
                ):
                    connection.execute(text('CREATE DATABASE "career_kitchen_samples"'))
                with target.begin() as setup:
                    names = inspect(setup).get_table_names()
                    if names and "ck_sample_marker" not in names:
                        raise ValueError("Refusing to touch an unmarked nonempty database")
                    if not names:
                        setup.execute(text("CREATE TABLE ck_sample_marker (marker text PRIMARY KEY)"))
                        setup.execute(
                            text("INSERT INTO ck_sample_marker VALUES (:marker)"), {"marker": IMPORT_MARKER}
                        )
                    if list(setup.scalars(text("SELECT marker FROM ck_sample_marker"))) != [IMPORT_MARKER]:
                        raise ValueError("Unrecognized synthetic database marker")
                    config = Config("alembic.ini")
                    config.attributes["connection"] = setup
                    command.upgrade(config, "head")
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(2077110934)"))
        print("Hosted sample setup: importing synthetic market", flush=True)
        with Session(target) as db, db.begin():
            import_samples(db, tables, provenance)
        print("Hosted sample setup: preparing fictional eligibility", flush=True)
        with Session(target) as db, db.begin():
            activate_samples(db, settings)
        print("Hosted sample setup: binding confirmed fixture accounts", flush=True)
        provider_headers = {
            "apikey": settings.supabase_service_role_key.get_secret_value(),
            "Authorization": "Bearer " + settings.supabase_service_role_key.get_secret_value(),
        }
        with httpx.Client(base_url=settings.supabase_url, headers=provider_headers, timeout=20) as client:
            for account, label, password_key in (
                ("employer", "employer", "SAMPLE_EMPLOYER_PASSWORD"),
                ("candidate-000001", "candidate-user-000001", "SAMPLE_CANDIDATE_PASSWORD"),
            ):
                password = os.environ[password_key]
                if len(password) < 32:
                    raise ValueError("Random sample passwords of at least 32 characters are required")
                email = account + "@samples.example.invalid"
                existing = client.get("/auth/v1/admin/users", params={"page": 1, "per_page": 1000})
                existing.raise_for_status()
                user = next((item for item in existing.json()["users"] if item.get("email") == email), None)
                if user is None:
                    created = client.post(
                        "/auth/v1/admin/users",
                        json={
                            "email": email,
                            "password": password,
                            "email_confirm": True,
                            "app_metadata": {"sample_fixture": IMPORT_MARKER},
                        },
                    )
                    created.raise_for_status()
                    user = created.json()
                elif user.get("app_metadata", {}).get("sample_fixture") != IMPORT_MARKER:
                    raise ValueError("Existing provider identity is not this sample fixture")
                login = client.post(
                    "/auth/v1/token",
                    params={"grant_type": "password"},
                    json={"email": email, "password": password},
                )
                login.raise_for_status()
                with Session(target) as db, db.begin():
                    lock_scopes(db, "sample.identity:" + label)
                    fixture = db.get(User, sample_identity(label))
                    if fixture is None:
                        raise ValueError("Imported fixture identity is missing")
                    if fixture.subject != user["id"] or fixture.issuer != settings.jwt_issuer:
                        fixture.subject = user["id"]
                        fixture.issuer = settings.jwt_issuer
                        fixture.version += 1
                        emit(
                            db,
                            Actor(
                                sample_identity("importer"), utcnow(), request_id="hosted-sample-binding-v1"
                            ),
                            "sample.identity_bound",
                            fixture,
                            payload={"synthetic": True, "fixture": account},
                        )
        print("Hosted sample setup: configuring restricted runtime role", flush=True)
        runtime_password = os.environ["SAMPLE_RUNTIME_PASSWORD"]
        if len(runtime_password) < 32:
            raise ValueError("A random runtime database password is required")
        import psycopg.sql

        with target.begin() as connection:
            connection.exec_driver_sql(Path("infra/postgres/runtime-role.sql").read_text())
            exists = connection.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname='career_kitchen_samples_app'")
            )
            password_literal = psycopg.sql.Literal(runtime_password).as_string(
                connection.connection.driver_connection
            )
            if not exists:
                connection.exec_driver_sql(
                    "CREATE ROLE career_kitchen_samples_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD "
                    + password_literal
                )
            connection.exec_driver_sql("GRANT career_kitchen_backend TO career_kitchen_samples_app")
            connection.exec_driver_sql("ALTER ROLE career_kitchen_samples_app INHERIT")
            connection.exec_driver_sql("GRANT SELECT ON ck_sample_marker TO career_kitchen_backend")
        print(
            "Hosted synthetic market ready: 20000 applicants, 20000 jobs, two confirmed Supabase fixture identities"
        )
    finally:
        target.dispose()
        admin.dispose()


if __name__ == "__main__":
    try:
        bootstrap()
    except Exception as error:
        original = getattr(error, "orig", None)
        state = getattr(original, "sqlstate", None)
        # SQLSTATE and a fixed stage identify operational failures without URLs,
        # credentials, SQL parameters, provider response bodies or profile data.
        print("Hosted sample failure SQLSTATE=" + str(state), flush=True)
        raise SystemExit(
            "Hosted sample setup failed ("
            + type(error).__name__
            + "); credentials and provider details are withheld"
        ) from None
