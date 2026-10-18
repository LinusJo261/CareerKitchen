"""Exercise pg_dump/pg_restore using fictional local data and a disposable database."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from app.core.settings import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def run(pg_bin: str | None = None) -> None:
    settings = get_settings()
    source = make_url(settings.database_url)
    if settings.environment not in {"development", "test"} or source.host not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise RuntimeError("Restore drill is restricted to the local fictional demo")
    portable = Path(".local/postgresql/pgsql/bin")
    suffix = ".exe" if os.name == "nt" else ""
    directory = Path(pg_bin) if pg_bin else portable
    dump_tool = directory / f"pg_dump{suffix}"
    restore_tool = directory / f"pg_restore{suffix}"
    if not dump_tool.is_file():
        dump_tool = Path(shutil.which("pg_dump") or "not-found")
    if not restore_tool.is_file():
        restore_tool = Path(shutil.which("pg_restore") or "not-found")
    if not dump_tool.is_file() or not restore_tool.is_file():
        raise RuntimeError("Matching PostgreSQL pg_dump and pg_restore tools are required")
    name = "ck_restore_" + uuid4().hex
    assert name.startswith("ck_restore_") and len(name) == len("ck_restore_") + 32
    directory = Path(".local/backup-drills")
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"{name}.dump"
    admin = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    restored = create_engine(source.set(database=name))
    original = create_engine(source.set(database="career_kitchen_demo"))
    pg_env = {**os.environ, "PGPASSWORD": source.password or ""}
    connection = [
        "--host",
        source.host,
        "--port",
        str(source.port or 5432),
        "--username",
        source.username or "postgres",
    ]
    try:
        with original.connect() as conn:
            assert conn.scalar(text("SELECT marker FROM ck_demo_marker")) == "career-kitchen-fictional-v1"
            expected = tuple(
                conn.scalar(text(f"SELECT count(*) FROM {table}"))
                for table in ["users", "candidate_profiles", "organizations", "vacancies"]
            )
        dumped = subprocess.run(
            [
                str(dump_tool.resolve()),
                *connection,
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(archive.resolve()),
                "career_kitchen_demo",
            ],
            env=pg_env,
            capture_output=True,
        )
        if dumped.returncode:
            raise RuntimeError("Local fictional pg_dump failed")
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        loaded = subprocess.run(
            [
                str(restore_tool.resolve()),
                *connection,
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--dbname",
                name,
                str(archive.resolve()),
            ],
            env=pg_env,
            capture_output=True,
        )
        if loaded.returncode:
            raise RuntimeError("Local fictional pg_restore failed")
        with restored.connect() as conn:
            actual = tuple(
                conn.scalar(text(f"SELECT count(*) FROM {table}"))
                for table in ["users", "candidate_profiles", "organizations", "vacancies"]
            )
            assert actual == expected
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0006_matching_learning"
            assert (
                conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname='reject_event_mutation'")) == 3
            )
            assert conn.scalar(text("SELECT relrowsecurity FROM pg_class WHERE relname='candidate_profiles'"))
        print(
            f"PASS: real PostgreSQL dump -> isolated restore; fixture row counts {actual}; migration, RLS and immutable triggers preserved"
        )
    finally:
        original.dispose()
        restored.dispose()
        with admin.connect() as conn:
            conn.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin")
    run(parser.parse_args().pg_bin)
