"""Alembic uses configured PostgreSQL; connection URLs are never logged."""

import os
from logging.config import fileConfig

from alembic import context
from app.core.settings import get_settings
from app.db import models, pact_models  # noqa: F401 -- register immutable schema metadata
from app.db.base import Base
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def migration_url() -> str:
    # Release jobs need only their own database credential, not application/storage secrets.
    direct = os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not direct:
        settings = get_settings()
        direct = settings.migration_database_url or settings.database_url
    url = make_url(direct)
    if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("Migrations require a PostgreSQL owner connection")
    if os.getenv("ENVIRONMENT", "development") in {"staging", "production"} and url.query.get(
        "sslmode"
    ) not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise ValueError("Hosted migration connections must enforce TLS")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(migration_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
