"""Read-only release gate. A separately credentialed job owns schema changes."""

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

EXPECTED_REVISION = "0007_merge_demo_onboarding"


def check_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM public.alembic_version"))
        if revision != EXPECTED_REVISION:
            raise ValueError("Database migration revision does not match this release")
        # The durable queue must be present and readable by the runtime role.
        connection.execute(text("SELECT id FROM public.outbox_events LIMIT 0"))


def main() -> None:
    from app.db.session import get_engine

    engine = get_engine()
    try:
        check_schema(engine)
    except (SQLAlchemyError, ValueError):
        raise SystemExit("Schema is not ready; run approved owner migrations before deploying") from None
    finally:
        engine.dispose()
    print(f"Schema ready: {EXPECTED_REVISION}")


if __name__ == "__main__":
    main()
