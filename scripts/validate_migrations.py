"""Round-trip migrations in a new temporary PostgreSQL database, never the configured DB."""

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app.core.settings import get_settings
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


def main() -> None:
    settings = get_settings()
    source = make_url(settings.migration_database_url or settings.database_url)
    name = "ck_migration_" + uuid4().hex
    administrator = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target = create_engine(source.set(database=name))
    browser_role = "ck_browser_probe_" + uuid4().hex
    group_existed = True
    try:
        with administrator.connect() as connection:
            group_existed = bool(
                connection.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='career_kitchen_backend')")
                )
            )
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        config = Config("alembic.ini")
        # Exercise the populated upgrade as well as a clean install.
        user_id, candidate_id = str(uuid4()), str(uuid4())
        with target.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0002_security_isolation")
            connection.execute(
                text("""
                INSERT INTO users
                (id, version, created_at, issuer, subject, verified_email, status, platform_roles)
                VALUES (:id, 1, now(), 'migration-fixture', :id, 'fictional@example.invalid', 'ACTIVE', '[]')
            """),
                {"id": user_id},
            )
            connection.execute(
                text("""
                INSERT INTO candidate_profiles
                (id, version, created_at, user_id, headline, summary, region, state, cap,
                 role_families, employment_types, work_modes, locations, currency, terms_accepted, privacy_accepted)
                VALUES (:id, 1, now(), :user_id, 'Fictional migration fixture', '', 'US', 'DRAFT', 1,
                        '["software"]', '["FULL_TIME"]', '["REMOTE"]', '[]', 'USD', true, true)
            """),
                {"id": candidate_id, "user_id": user_id},
            )
        with target.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with target.connect() as connection:
            tables = inspect(connection).get_table_names()
            assert "decision_cards" in tables and "pact_policy_versions" in tables
            assert all(
                row[1]
                for row in connection.execute(
                    text(
                        "SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public' AND tablename!='alembic_version'"
                    )
                )
            )
            migrated = connection.execute(
                text(
                    "SELECT compensation_period, experiences, education, display_name, professional_links FROM candidate_profiles WHERE id=:id"
                ),
                {"id": candidate_id},
            ).one()
            assert tuple(migrated) == ("ANNUAL", [], [], "", {})
        audit_id = str(uuid4())
        with target.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO audit_events
                (id, version, created_at, action, entity_type, entity_id, request_id, after_hash, integrity_hash)
                VALUES (:id, 1, now(), 'migration.test', 'test', :id, 'test', :hash, :hash)
            """),
                {"id": audit_id, "hash": "0" * 64},
            )
        for statement in (
            "UPDATE audit_events SET action='tampered' WHERE id=:id",
            "DELETE FROM audit_events WHERE id=:id",
        ):
            try:
                with target.begin() as connection:
                    connection.execute(text(statement), {"id": audit_id})
            except DBAPIError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "55000"
            else:
                raise AssertionError("Database permitted immutable audit mutation")
        # Exercise the exact deployed SQL, not an in-memory imitation of its policy.
        with target.begin() as connection:
            connection.execute(text("ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY"))
            driver = connection.connection.driver_connection
            assert driver is not None
            driver.execute(
                (Path(__file__).resolve().parents[1] / "infra/postgres/runtime-role.sql").read_text(
                    encoding="utf-8"
                )
            )
            owner = connection.scalar(text("SELECT current_user"))
            quoted_owner = connection.dialect.identifier_preparer.quote(owner)
            connection.execute(text(f"GRANT career_kitchen_backend TO {quoted_owner}"))
            connection.execute(
                text(
                    f'CREATE ROLE "{browser_role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
                )
            )
            connection.execute(text(f'GRANT "{browser_role}" TO {quoted_owner}'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{browser_role}"'))
            # Even an accidental browser SELECT grant remains blocked by default-deny RLS.
            connection.execute(text(f'GRANT SELECT ON TABLE public.users TO "{browser_role}"'))
            connection.execute(text(f'GRANT SELECT ON TABLE public.alembic_version TO "{browser_role}"'))
            connection.execute(text("CREATE SCHEMA compliance_private"))
            connection.execute(text("CREATE TABLE compliance_private.secrets (value text)"))
        runtime_audit_id = str(uuid4())
        with target.begin() as connection:
            connection.execute(text("SET LOCAL ROLE career_kitchen_backend"))
            assert connection.scalar(text("SELECT count(*) FROM users")) == 1
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0006_candidate_onboarding"
            )
            assert (
                connection.execute(
                    text(
                        "UPDATE candidate_profiles SET summary='Fictional runtime policy check' WHERE id=:id"
                    ),
                    {"id": candidate_id},
                ).rowcount
                == 1
            )
            connection.execute(
                text("""
                INSERT INTO audit_events
                (id, version, created_at, action, entity_type, entity_id, request_id, after_hash, integrity_hash)
                VALUES (:id, 1, now(), 'runtime.test', 'test', :id, 'test', :hash, :hash)
            """),
                {"id": runtime_audit_id, "hash": "0" * 64},
            )
        for statement in (
            "UPDATE audit_events SET action='forbidden'",
            "DELETE FROM audit_events",
            "TRUNCATE candidate_profiles",
            "ALTER TABLE users ADD COLUMN forbidden integer",
            "CREATE TABLE public.forbidden_runtime_ddl (id integer)",
            "UPDATE alembic_version SET version_num='forged'",
            "SELECT * FROM compliance_private.secrets",
        ):
            try:
                with target.begin() as connection:
                    connection.execute(text("SET LOCAL ROLE career_kitchen_backend"))
                    connection.execute(text(statement))
            except DBAPIError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "42501", statement
            else:
                raise AssertionError(f"Runtime role permitted forbidden operation: {statement}")
        with target.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{browser_role}"'))
            assert connection.scalar(text("SELECT count(*) FROM users")) == 0
            assert connection.scalar(text("SELECT count(*) FROM public.alembic_version")) == 0
        from app.check_schema import check_schema

        runtime_engine = create_engine(
            source.set(database=name), connect_args={"options": "-c role=career_kitchen_backend"}
        )
        try:
            check_schema(runtime_engine)
        finally:
            runtime_engine.dispose()
        with target.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        with target.connect() as connection:
            assert inspect(connection).get_table_names() == ["alembic_version"]
        with target.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        print(
            f"PASS: PostgreSQL upgrade -> downgrade -> upgrade; {len(tables) - 1} application tables; runtime RLS/DML and DDL/audit/browser/private-schema denial"
        )
    finally:
        target.dispose()
        with administrator.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{browser_role}"'))
            if not group_existed:
                connection.execute(text("DROP ROLE IF EXISTS career_kitchen_backend"))
        administrator.dispose()


if __name__ == "__main__":
    main()
