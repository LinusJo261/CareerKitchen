import io
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from app.core import auth, security
from app.core.errors import AppError
from app.core.settings import Settings
from app.integrations import storage
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError


def local_settings(**overrides):
    return Settings(
        _env_file=None,
        environment="test",
        auth_mode="local",
        allow_dev_auth=True,
        dev_jwt_secret="test-only-random-secret-at-least-32-characters",
        **overrides,
    )


def token_claims(settings):
    now = datetime.now(UTC)
    return {
        "sub": str(uuid4()),
        "session_id": str(uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.supabase_jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "email_verified": True,
        "email": "fictional@example.invalid",
        "auth_time": int(now.timestamp()),
    }


def sign_local(claims, settings):
    return jwt.encode(claims, settings.dev_jwt_secret.get_secret_value(), algorithm="HS256")


def test_explicit_local_auth_roundtrip_ignores_privileged_claims():
    settings = local_settings()
    claims = token_claims(settings) | {
        "role": "superuser",
        "org_id": str(uuid4()),
        "platform_roles": ["admin"],
    }
    identity = auth.verify_access_token(sign_local(claims, settings), settings)
    assert str(identity.subject) == claims["sub"]
    assert identity.email_verified
    assert not hasattr(identity, "role")
    assert not hasattr(identity, "org_id")
    assert not hasattr(identity, "platform_roles")


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://attacker.invalid/auth/v1"},
        {"aud": "some-other-service"},
        {"exp": 1},
        {"iat": 4102444800},
        {"sub": "invalid-user"},
        {"session_id": "invalid-session"},
    ],
)
def test_invalid_identity_lifetime_audience_issuer_rejected(change):
    settings = local_settings()
    with pytest.raises(AppError) as failure:
        auth.verify_access_token(sign_local(token_claims(settings) | change, settings), settings)
    assert failure.value.status == 401


@pytest.mark.parametrize("missing", ["exp", "iat", "iss", "aud", "sub", "session_id"])
def test_missing_security_claim_rejected(missing):
    settings = local_settings()
    claims = token_claims(settings)
    del claims[missing]
    with pytest.raises(AppError, match="not valid"):
        auth.verify_access_token(sign_local(claims, settings), settings)


def test_unverified_email_rejected():
    settings = local_settings()
    claims = token_claims(settings) | {"email_verified": False}
    with pytest.raises(AppError) as failure:
        auth.verify_access_token(sign_local(claims, settings), settings)
    assert failure.value.code == "EMAIL_UNVERIFIED"


def test_unsigned_token_and_remote_key_url_rejected():
    settings = local_settings()
    for token in [
        jwt.encode(token_claims(settings), "", algorithm="none"),
        jwt.encode(
            token_claims(settings),
            settings.dev_jwt_secret.get_secret_value(),
            algorithm="HS256",
            headers={"jku": "https://attacker.invalid/key"},
        ),
    ]:
        with pytest.raises(AppError) as failure:
            auth.verify_access_token(token, settings)
        assert failure.value.status == 401


def test_supabase_asymmetric_verification_and_provider_email(monkeypatch):
    settings = Settings(
        _env_file=None,
        auth_mode="supabase",
        supabase_url="https://project.supabase.co",
        supabase_publishable_key="test-publishable",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = token_claims(settings)
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
    client = SimpleNamespace(
        get_signing_key_from_jwt=lambda raw: SimpleNamespace(key=private_key.public_key())
    )
    monkeypatch.setattr(auth, "_jwk_client", lambda url: client)
    monkeypatch.setattr(
        auth,
        "_supabase_user",
        lambda raw, cfg, sub: {
            "id": str(sub),
            "email": "confirmed@example.invalid",
            "email_confirmed_at": "2026-01-01T00:00:00Z",
            "user_metadata": {"role": "admin"},
        },
    )
    identity = auth.verify_access_token(token, settings)
    assert identity.email == "confirmed@example.invalid"
    # User-editable metadata can never make an unconfirmed address verified.
    monkeypatch.setattr(
        auth,
        "_supabase_user",
        lambda raw, cfg, sub: {
            "id": str(sub),
            "email": "unconfirmed@example.invalid",
            "email_confirmed_at": None,
            "user_metadata": {"email_verified": True},
        },
    )
    with pytest.raises(AppError) as failure:
        auth.verify_access_token(token, settings)
    assert failure.value.code == "EMAIL_UNVERIFIED"
    # The real asymmetric public key cannot become an HMAC production verifier.
    with pytest.raises(AppError):
        auth.verify_access_token(
            jwt.encode(claims, "attacker-secret-that-is-long-enough-32", algorithm="HS256"), settings
        )


def test_provider_error_fails_closed(monkeypatch):
    settings = Settings(
        _env_file=None,
        auth_mode="supabase",
        supabase_url="https://project.supabase.co",
        supabase_publishable_key="test-publishable",
    )

    class FailingClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=503)

    monkeypatch.setattr(auth.httpx, "Client", FailingClient)
    with pytest.raises(AppError) as failure:
        auth._supabase_user("unused", settings, uuid4())
    assert failure.value.status == 503


def test_production_settings_reject_insecure_configuration():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            auth_mode="local",
            allow_dev_auth=True,
            dev_jwt_secret="test-secret-that-is-long-enough-32",
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=["*"])
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///pretend-production.db")


def test_encrypted_private_storage_and_traversal_defense(tmp_path, monkeypatch):
    settings = local_settings(
        encryption_key=Fernet.generate_key().decode(),
        storage_backend="local",
        local_storage_dir=tmp_path,
        audit_hmac_key="a" * 40,
    )
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    body = b"Fictional Candidate\nPython and PostgreSQL\n"
    stored = storage.store_resume(body, "text/plain", uuid4())
    assert stored.text == body.decode()
    assert body not in (tmp_path / stored.object_key).read_bytes()
    assert storage.read_private(stored.object_key) == body
    assert security.pseudonym("sensitive") != "sensitive"
    for key in ("../secret", "/etc/passwd", "file://secret", "../../.env"):
        with pytest.raises(AppError):
            storage.read_private(key)
    storage.delete_private(stored.object_key)
    with pytest.raises(AppError) as failure:
        storage.read_private(stored.object_key)
    assert failure.value.status == 404


def test_binary_scan_absence_and_mime_spoofing_fail_closed(monkeypatch):
    settings = local_settings(clamav_host="")
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    with pytest.raises(AppError) as absent:
        storage.validate_resume(b"%PDF-1.4\nplain\n%%EOF", "application/pdf")
    assert absent.value.code == "SCANNER_UNAVAILABLE"
    with pytest.raises(AppError):
        storage.validate_resume(b"executable bytes", "application/pdf")
    with pytest.raises(AppError):
        storage.validate_resume(b"%PDF-1.4\n/JavaScript bad\n%%EOF", "application/pdf")
    with pytest.raises(AppError):
        storage.validate_resume(b"MZ\x00binary", "text/plain")
    with pytest.raises(AppError):
        storage.validate_resume(b"<script>bad</script>", "text/html")


def test_external_docx_relationship_rejected_regardless_of_xml_quoting(monkeypatch):
    settings = local_settings(clamav_host="")
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    for relationship in (
        b"<Relationships><Relationship TargetMode='External'/></Relationships>",
        b'<Relationships><Relationship TargetMode="external"/></Relationships>',
    ):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as document:
            document.writestr("word/document.xml", "<document/>")
            document.writestr("word/_rels/document.xml.rels", relationship)
        with pytest.raises(AppError) as failure:
            storage.validate_resume(
                content.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        assert failure.value.code == "UNSAFE_DOCUMENT"


@pytest.mark.parametrize(
    "response,expected",
    [
        (b"stream: Eicar-Signature FOUND\0", "UNSAFE_DOCUMENT"),
        (b"stream: size limit ERROR\0", "SCANNER_UNAVAILABLE"),
        (b"", "SCANNER_UNAVAILABLE"),
    ],
)
def test_real_scan_must_report_clean_before_acceptance(monkeypatch, response, expected):
    settings = local_settings(clamav_host="scanner.internal")
    monkeypatch.setattr(storage, "get_settings", lambda: settings)

    class Scanner:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def sendall(self, content):
            pass

        def recv(self, limit):
            return response

    monkeypatch.setattr(storage.socket, "create_connection", lambda *args, **kwargs: Scanner())
    with pytest.raises(AppError) as failure:
        storage.validate_resume(b"%PDF-1.4\nplain\n%%EOF", "application/pdf")
    assert failure.value.code == expected
