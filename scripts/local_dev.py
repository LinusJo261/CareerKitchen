"""Explicit, loopback-only setup and diagnostics for testing Career Chef in Swagger.

Run from the repository root. No command overwrites an existing environment file,
drops a database, assigns application roles, or calls Gemini to check a key.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.auth import mint_dev_token
from app.core.settings import Settings
from app.schemas.navigation import NavigationChatIn, NavigationChatOut
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATABASES = frozenset({"career_kitchen", "career_kitchen_test"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class LocalSetupError(RuntimeError):
    """An actionable diagnostic containing no credentials or provider payloads."""


def initialize(path: Path, port: int = 55432) -> None:
    """Create a development config exclusively, with independent random secrets."""
    password = secrets.token_urlsafe(32)
    values = {
        "ENVIRONMENT": "development",
        "DATABASE_URL": f"postgresql+psycopg://career_kitchen:{password}@127.0.0.1:{port}/career_kitchen",
        "LOCAL_DATABASE_PASSWORD": password,
        "AUTH_MODE": "local",
        "ALLOW_DEV_AUTH": "true",
        "DEV_JWT_SECRET": secrets.token_urlsafe(48),
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "AUDIT_HMAC_KEY": secrets.token_urlsafe(48),
        "READINESS_TOKEN": secrets.token_urlsafe(48),
        "CORS_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000",
        "TRUSTED_HOSTS": "localhost,127.0.0.1,testserver",
        "FEATURE_MODE": "SHADOW",
        "STORAGE_BACKEND": "local",
        "GEMINI_API_KEY": "",
        "GEMINI_MODEL": Settings.model_fields["gemini_model"].default,
        "GEMINI_TIMEOUT_SECONDS": "20",
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise LocalSetupError(".env already exists; it was preserved. Edit it explicitly instead.") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Local fictional testing only. Do not commit or deploy these credentials.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())


def require_local(settings: Settings) -> URL:
    """Fail closed before local setup mutates any configured database."""
    url = make_url(settings.database_url)
    if (
        settings.environment not in {"development", "test"}
        or settings.auth_mode != "local"
        or not settings.allow_dev_auth
        or url.host not in LOOPBACK_HOSTS
        or url.database not in LOCAL_DATABASES
        or set(url.query) - {"sslmode"}
    ):
        raise LocalSetupError(
            "Local helpers require development/test, AUTH_MODE=local, ALLOW_DEV_AUTH=true, "
            "and a loopback career_kitchen or career_kitchen_test database. "
            "Use the normal Supabase workflow for hosted environments."
        )
    return url


def check_database(settings: Settings) -> None:
    url = require_local(settings)
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            migrated = bool(connection.scalar(text("SELECT to_regclass('public.alembic_version')")))
            if not migrated:
                raise LocalSetupError("PostgreSQL is reachable, but migrations are missing. Run prepare.")
            revisions = set(connection.scalars(text("SELECT version_num FROM alembic_version")))
            expected = set(ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads())
            if revisions != expected:
                raise LocalSetupError("PostgreSQL migrations are out of date. Run prepare.")
    except SQLAlchemyError as exc:
        raise LocalSetupError(
            "PostgreSQL is unavailable or access was denied. Start your local database, "
            "verify DATABASE_URL/LOCAL_DATABASE_PASSWORD, then run prepare."
        ) from exc
    finally:
        engine.dispose()


def prepare(settings: Settings, *, include_test_database: bool = False) -> None:
    """Create missing named local databases and migrate; never reset existing data."""
    url = require_local(settings)
    administrator = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    databases = [url.database]
    if include_test_database and "career_kitchen_test" not in databases:
        databases.append("career_kitchen_test")
    try:
        with administrator.connect() as connection:
            for database in databases:
                if not connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database}
                ):
                    # Names are fixed above and validated by require_local, never user SQL.
                    connection.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        administrator.dispose()
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.begin() as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def local_token(settings: Settings) -> str:
    require_local(settings)
    subject = uuid5(NAMESPACE_URL, "https://career-kitchen.example.invalid/fictional/chef-tester")
    return mint_dev_token(
        subject,
        email="chef-tester@fictional.example.invalid",
        lifetime_seconds=1800,
        settings=settings,
    )


def ask(settings: Settings, message: str, key: str | None = None) -> None:
    """Send an explicitly consented message to the actual local API, without printing credentials."""
    require_local(settings)
    if not settings.gemini_api_key.get_secret_value().strip():
        raise LocalSetupError("Set GEMINI_API_KEY in .env, restart the API, then retry.")
    try:
        body = NavigationChatIn(message=message, consent_to_gemini=True)
    except ValidationError as exc:
        raise LocalSetupError("The message must contain 1-2000 nonblank characters.") from exc
    request_key = key or str(uuid4())
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", request_key):
        raise LocalSetupError(
            "--key must contain 8-128 letters, digits, dots, underscores, colons or hyphens."
        )
    print(f"Idempotency-Key: {request_key}", flush=True)
    try:
        with httpx.Client(
            timeout=settings.gemini_timeout_seconds + 10, follow_redirects=False, trust_env=False
        ) as client:
            response = client.post(
                "http://127.0.0.1:8000/v1/navigation/chat",
                headers={
                    "Authorization": "Bearer " + local_token(settings),
                    "Idempotency-Key": request_key,
                    "Origin": "http://127.0.0.1:8000",
                },
                json=body.model_dump(mode="json"),
            )
    except httpx.HTTPError as exc:
        raise LocalSetupError(
            "The local API could not be reached. Start it, then retry with the same --key."
        ) from exc
    if response.status_code != 200:
        raise LocalSetupError(
            f"Career Chef returned HTTP {response.status_code}. Inspect the response in Swagger; "
            "check key configuration, authentication, origin and PostgreSQL."
        )
    try:
        result = NavigationChatOut.model_validate(response.json()["data"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LocalSetupError(
            "The local API returned an unexpected response. Restart it with the current code."
        ) from exc
    print(result.reply)
    for link in result.links:
        print(f"{link.label}: {link.path}")


def verify_portable_database(settings: Settings, data: Path) -> None:
    """Confirm the running server is this cluster and accepts connections only on loopback."""
    engine = create_engine(
        make_url(settings.database_url).set(database="postgres"), connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as connection:
            address, port, directory = connection.execute(
                text(
                    "SELECT current_setting('listen_addresses'), current_setting('port'), current_setting('data_directory')"
                )
            ).one()
        if (
            not {value.strip() for value in str(address).split(",")}.issubset(LOOPBACK_HOSTS)
            or str(port) != "55432"
            or Path(str(directory)).resolve() != data.resolve()
        ):
            raise LocalSetupError(
                "The running database is not the expected loopback cluster; it was preserved."
            )
    except SQLAlchemyError as exc:
        raise LocalSetupError(
            "The portable database identity or connection could not be verified; it was preserved."
        ) from exc
    finally:
        engine.dispose()


def start_database(settings: Settings) -> None:
    """Start only the already provisioned Windows cluster in this ignored workspace."""
    url = require_local(settings)
    if sys.platform != "win32" or url.port != 55432:
        raise LocalSetupError("Portable startup supports the provisioned Windows cluster on port 55432 only.")
    local = (ROOT / ".local").resolve()
    executable = (local / "postgres/pgsql/bin/pg_ctl.exe").resolve()
    data = (local / "postgres-data").resolve()
    if not local.is_relative_to(ROOT) or any(not path.is_relative_to(local) for path in (executable, data)):
        raise LocalSetupError(
            "Portable PostgreSQL paths must remain within this workspace's .local directory."
        )
    if not executable.is_file() or not (data / "PG_VERSION").is_file():
        raise LocalSetupError(
            "Portable PostgreSQL is not provisioned here. Use docker compose up -d postgres."
        )
    if (data / "PG_VERSION").read_text(encoding="utf-8").strip() != "17":
        raise LocalSetupError("Portable startup requires the recognized PostgreSQL 17 cluster.")
    for name in ("postgresql.conf", "postgresql.auto.conf"):
        config = data / name
        if config.exists():
            for raw in config.read_text(encoding="utf-8").splitlines():
                line = raw.partition("#")[0].strip().lower()
                if line and (line.startswith("include") or line.startswith("hba_file")):
                    raise LocalSetupError(
                        "Portable startup refuses alternate/included authentication configuration."
                    )
    hba = data / "pg_hba.conf"
    if not hba.is_file():
        raise LocalSetupError("Portable cluster authentication configuration is missing.")
    for raw in hba.read_text(encoding="utf-8").splitlines():
        fields = raw.partition("#")[0].split()
        if not fields:
            continue
        valid = (
            len(fields) == 4
            and fields[0] == "local"
            and fields[-1] == "scram-sha-256"
            or len(fields) == 5
            and fields[0] == "host"
            and fields[3] in {"127.0.0.1/32", "::1/128"}
            and fields[-1] == "scram-sha-256"
        )
        if not valid:
            raise LocalSetupError("Portable startup requires loopback-only SCRAM authentication.")
    status = subprocess.run(
        [str(executable), "-D", str(data), "status"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=10,
    )
    if status.returncode == 0:
        verify_portable_database(settings, data)
        print("Portable PostgreSQL is already running; its process was preserved.")
        return
    if status.returncode != 3:
        raise LocalSetupError("Portable PostgreSQL status could not be verified; no new process was started.")
    result = subprocess.run(
        [
            str(executable),
            "-D",
            str(data),
            "-l",
            str(local / "postgres.log"),
            "-o",
            "-h 127.0.0.1 -p 55432",
            "-w",
            "-t",
            "15",
            "start",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise LocalSetupError("Portable PostgreSQL did not start. Inspect .local/postgres.log locally.")
    verify_portable_database(settings, data)
    print("Portable PostgreSQL started on 127.0.0.1:55432.")


def diagnostics(settings: Settings) -> bool:
    """Print configuration state only; never print credentials or contact Google."""
    require_local(settings)
    if (
        not settings.encryption_key.get_secret_value()
        or len(settings.audit_hmac_key.get_secret_value()) < 32
        or any(
            value.startswith("REPLACE_")
            for value in (
                settings.dev_jwt_secret.get_secret_value(),
                settings.audit_hmac_key.get_secret_value(),
            )
        )
    ):
        raise LocalSetupError(
            "Local encryption/audit/signing secrets are missing or placeholders. "
            "Use init for a new .env, or replace its placeholders with independent random secrets."
        )
    print("Authentication: explicit local fictional identity, loopback only")
    configured = bool(settings.gemini_api_key.get_secret_value().strip())
    print(
        f"Gemini key: {'configured (not contacted)' if configured else 'missing; set GEMINI_API_KEY in .env'}"
    )
    check_database(settings)
    print("PostgreSQL: reachable; migrations current")
    print("Swagger: http://127.0.0.1:8000/docs (start with serve)")
    return configured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    init_parser = commands.add_parser("init", help="Create .env with random local-only secrets; no overwrite")
    init_parser.add_argument(
        "--database-port", type=int, choices=range(1, 65536), default=55432, metavar="PORT"
    )
    commands.add_parser("check", help="Check local configuration and migrations; no Gemini request")
    prepare_parser = commands.add_parser(
        "prepare", help="Create missing local database(s) and apply migrations"
    )
    prepare_parser.add_argument("--include-test-database", action="store_true")
    commands.add_parser("token", help="Explicitly print a short-lived fictional local Swagger token")
    commands.add_parser("start-db", help="Start the already provisioned, loopback-only Windows PostgreSQL")
    ask_parser = commands.add_parser(
        "ask", help="Send a message to the running local API and print Career Chef's reply"
    )
    ask_parser.add_argument("message")
    ask_parser.add_argument(
        "--consent-to-gemini",
        action="store_true",
        required=True,
        help="Consent to send this message to Google Gemini; avoid personal or sensitive data",
    )
    ask_parser.add_argument("--key", help="Reuse the key for an exact retry; omit it for a new message")
    commands.add_parser("serve", help="Preflight configuration, then serve on 127.0.0.1:8000")
    options = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        print("Run this command from the CareerKitchen repository root.", file=sys.stderr)
        return 1
    try:
        if options.action == "init":
            initialize(ROOT / ".env", options.database_port)
            print("Created ignored .env with random local-only credentials. Add your Gemini key there.")
            print("Start PostgreSQL with docker compose up -d postgres, then run prepare.")
            return 0
        settings = Settings()
        if options.action == "prepare":
            prepare(settings, include_test_database=options.include_test_database)
            print("Local databases prepared; existing data preserved.")
        elif options.action == "start-db":
            start_database(settings)
        elif options.action == "ask":
            ask(settings, options.message, options.key)
        elif options.action == "token":
            print(local_token(settings))
        elif options.action == "check":
            return 0 if diagnostics(settings) else 1
        elif options.action == "serve":
            if not diagnostics(settings):
                raise LocalSetupError("Set GEMINI_API_KEY in .env, then rerun serve.")
            import uvicorn

            uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
        return 0
    except LocalSetupError as exc:
        print(str(exc), file=sys.stderr)
    except ValidationError:
        print(
            "Configuration is invalid. Check .env against .env.example; secrets are not displayed.",
            file=sys.stderr,
        )
    except SQLAlchemyError:
        print(
            "Local database setup failed. Check the database is running and the local user can create databases.",
            file=sys.stderr,
        )
    except OSError:
        print(
            "Local setup could not access a required file or port. Existing files were preserved.",
            file=sys.stderr,
        )
    except subprocess.TimeoutExpired:
        print("Portable PostgreSQL startup timed out. Inspect .local/postgres.log locally.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
