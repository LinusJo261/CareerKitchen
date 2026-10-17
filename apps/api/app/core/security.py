"""PII encryption and keyed pseudonyms. Application code never logs plaintext."""

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import AppError
from app.core.settings import get_settings


def encrypt(value: str | bytes) -> str:
    key = get_settings().encryption_key.get_secret_value()
    if not key:
        raise AppError(503, "ENCRYPTION_UNAVAILABLE", "Private data encryption is not configured")
    content = value.encode("utf-8") if isinstance(value, str) else value
    return Fernet(key.encode()).encrypt(content).decode("ascii")


def decrypt(value: str) -> bytes:
    key = get_settings().encryption_key.get_secret_value()
    if not key:
        raise AppError(503, "ENCRYPTION_UNAVAILABLE", "Private data encryption is not configured")
    try:
        return Fernet(key.encode()).decrypt(value.encode("ascii"))
    except InvalidToken as exc:
        raise AppError(503, "PRIVATE_DATA_UNAVAILABLE", "Private data could not be opened") from exc


def pseudonym(value: str) -> str:
    key = get_settings().audit_hmac_key.get_secret_value()
    if len(key) < 32:
        raise AppError(503, "AUDIT_KEY_UNAVAILABLE", "Audit pseudonymization is not configured")
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()
