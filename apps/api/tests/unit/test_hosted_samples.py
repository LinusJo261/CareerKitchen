"""Hosted samples retain database ownership, TLS and Supabase boundaries."""

import json
from types import SimpleNamespace

import pytest
from app.core.errors import AppError
from sqlalchemy.engine import make_url

from app.api.demo import IMPORT_MARKER, require_sample_database


def fixture(actual=None, configured=None):
    url = "postgresql+psycopg://sample:private@sample-db.internal:5432/career_kitchen_samples?sslmode=require"
    settings = SimpleNamespace(
        environment="production",
        auth_mode="supabase",
        sample_demo_enabled=True,
        allow_dev_auth=False,
        database_url=configured or url,
    )
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(engine=SimpleNamespace(url=make_url(actual or url))),
        scalar=lambda query: "career_kitchen_samples" if "current_database" in str(query) else True,
        scalars=lambda query: [IMPORT_MARKER],
        get=lambda *args: SimpleNamespace(
            response_json=json.dumps({"import_version": IMPORT_MARKER, "synthetic": True})
        ),
    )
    return db, settings


def test_hosted_guard_accepts_only_marked_dedicated_tls_database():
    db, settings = fixture()
    assert require_sample_database(db, settings)["synthetic"] is True
    db.scalars = lambda query: ["unrelated"]
    with pytest.raises(AppError):
        require_sample_database(db, settings)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://sample:private@sample-db.internal:5432/live?sslmode=require",
        "postgresql+psycopg://sample:private@sample-db.internal:5432/career_kitchen_samples",
        "postgresql+psycopg://sample:private@other.internal:5432/career_kitchen_samples?sslmode=require",
    ],
)
def test_hosted_guard_rejects_wrong_database_unencrypted_or_different_connection(url):
    db, settings = fixture(actual=url)
    with pytest.raises(AppError):
        require_sample_database(db, settings)


def test_hosted_demo_cannot_enable_development_auth():
    db, settings = fixture()
    settings.allow_dev_auth = True
    with pytest.raises(AppError):
        require_sample_database(db, settings)
