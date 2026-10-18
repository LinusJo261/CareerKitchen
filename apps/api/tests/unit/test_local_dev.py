from __future__ import annotations

from uuid import UUID

import jwt
import pytest
from app.core.auth import verify_access_token
from app.core.settings import Settings
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy.exc import OperationalError

from scripts import local_dev


def settings(**changes) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "environment": "test",
            "auth_mode": "local",
            "allow_dev_auth": True,
            "dev_jwt_secret": "local-setup-fictional-token-secret-32-characters",
            "encryption_key": Fernet.generate_key().decode(),
            "audit_hmac_key": "local-setup-fictional-audit-secret-32-characters",
            "database_url": "postgresql+psycopg://fixture:not-a-real-password@127.0.0.1:55432/career_kitchen",
            **changes,
        },
    )


def test_init_creates_independent_secrets_without_replacing_existing_file(tmp_path):
    target = tmp_path / ".env"
    local_dev.initialize(target)
    original = target.read_bytes()
    values = dotenv_values(target)
    secret_names = [
        "LOCAL_DATABASE_PASSWORD",
        "DEV_JWT_SECRET",
        "ENCRYPTION_KEY",
        "AUDIT_HMAC_KEY",
        "READINESS_TOKEN",
    ]
    assert all(len(values[name]) >= 32 for name in secret_names)
    assert len({values[name] for name in secret_names}) == len(secret_names)
    Fernet(values["ENCRYPTION_KEY"].encode())
    assert values["AUTH_MODE"] == "local"
    assert values["ALLOW_DEV_AUTH"] == "true"
    assert values["GEMINI_API_KEY"] == ""
    assert values["FEATURE_MODE"] == "LIVE"
    assert ":55432/career_kitchen" in values["DATABASE_URL"]
    with pytest.raises(local_dev.LocalSetupError, match="already exists"):
        local_dev.initialize(target)
    assert target.read_bytes() == original


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": "postgresql+psycopg://fixture:secret@remote.invalid/career_kitchen"},
        {"database_url": "postgresql+psycopg://fixture:secret@127.0.0.1/production"},
        {"database_url": "postgresql+psycopg://fixture:secret@127.0.0.1/career_kitchen?host=remote.invalid"},
        {"auth_mode": "supabase", "allow_dev_auth": False},
    ],
)
def test_mutating_helpers_refuse_remote_ambiguous_or_hosted_configuration(changes):
    configured = settings(**changes)
    with pytest.raises(local_dev.LocalSetupError, match="loopback"):
        local_dev.prepare(configured)
    with pytest.raises(local_dev.LocalSetupError):
        local_dev.local_token(configured)


def test_token_is_verified_short_lived_fictional_and_has_no_roles():
    configured = settings()
    token = local_dev.local_token(configured)
    identity = verify_access_token(token, configured)
    assert isinstance(identity.subject, UUID)
    assert identity.email == "chef-tester@fictional.example.invalid"
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] <= 1800
    assert "role" not in claims and "roles" not in claims and "app_metadata" not in claims


def test_diagnostics_never_outputs_credentials_or_calls_provider(monkeypatch, capsys):
    configured = settings(gemini_api_key="secret-provider-test-value")
    monkeypatch.setattr(local_dev, "check_database", lambda _: None)
    assert local_dev.diagnostics(configured)
    output = capsys.readouterr().out
    assert "configured (not contacted)" in output
    assert "secret-provider-test-value" not in output
    assert "not-a-real-password" not in output
    assert configured.dev_jwt_secret.get_secret_value() not in output


def test_main_redacts_database_errors(monkeypatch, capsys):
    monkeypatch.setattr(local_dev, "Settings", lambda: settings())
    monkeypatch.setattr(
        local_dev,
        "prepare",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OperationalError("SELECT secret-value", {}, Exception("secret-password"))
        ),
    )
    assert local_dev.main(["prepare"]) == 1
    output = capsys.readouterr()
    assert "database setup failed" in output.err
    assert "secret-value" not in output.err and "secret-password" not in output.err


@pytest.mark.parametrize(
    "changes", [{"encryption_key": ""}, {"audit_hmac_key": ""}, {"audit_hmac_key": "REPLACE_" + "X" * 32}]
)
def test_diagnostics_catches_missing_app_secrets_before_database_or_readiness(monkeypatch, changes):
    monkeypatch.setattr(local_dev, "check_database", lambda _: pytest.fail("must check secrets first"))
    with pytest.raises(local_dev.LocalSetupError, match="missing or placeholders"):
        local_dev.diagnostics(settings(**changes))
