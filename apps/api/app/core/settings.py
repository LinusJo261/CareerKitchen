"""Explicit production settings. Secrets are never included in repr output."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = Field(
        default="postgresql+psycopg://career_kitchen:development-only@127.0.0.1:55432/career_kitchen",
        repr=False,
    )
    migration_database_url: str | None = Field(default=None, repr=False)
    auth_mode: Literal["supabase", "local"] = "supabase"
    allow_dev_auth: bool = False
    dev_jwt_secret: SecretStr = SecretStr("")
    dev_jwt_issuer: str = "http://127.0.0.1:8000/dev-auth"
    supabase_url: str = ""
    supabase_publishable_key: SecretStr = SecretStr("")
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_jwt_audience: str = "authenticated"
    jwt_clock_skew_seconds: int = Field(default=15, ge=0, le=60)
    jwt_max_lifetime_seconds: int = Field(default=3600, ge=60, le=86400)
    encryption_key: SecretStr = SecretStr("")
    audit_hmac_key: SecretStr = SecretStr("")
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    trusted_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "testserver"]
    feature_mode: Literal["BASELINE", "SHADOW"] = "SHADOW"
    storage_backend: Literal["local", "supabase"] = "local"
    storage_bucket: str = "career-kitchen-private"
    local_storage_dir: Path = Path(".local/storage")
    max_resume_bytes: int = Field(default=5_000_000, ge=1024, le=10_000_000)
    clamav_host: str = ""
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    market_price_window_seconds: int = Field(default=900, ge=60, le=86400)
    market_price_max: float = Field(default=10.0, ge=0, le=100)
    congestion_price_max: float = Field(default=10.0, ge=0, le=100)
    decision_ttl_hours: int = Field(default=72, ge=1, le=168)
    rate_limit_per_minute: int = Field(default=120, ge=1, le=10000)
    readiness_token: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="gemini-2.5-flash", pattern=r"^gemini-[a-z0-9.-]+$")
    gemini_timeout_seconds: float = Field(default=20, ge=1, le=60)

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def split_lists(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def postgres_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql+psycopg://", 1)
        elif value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+psycopg://", 1)
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use PostgreSQL with psycopg")
        return value

    @field_validator("migration_database_url", mode="before")
    @classmethod
    def optional_migration_url(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def check_security(self) -> "Settings":
        if "*" in self.cors_origins or "*" in self.trusted_hosts:
            raise ValueError("Explicit CORS origins and trusted hosts are required")
        if self.auth_mode == "local":
            if self.environment not in {"development", "test"} or not self.allow_dev_auth:
                raise ValueError("Local authentication requires development/test and ALLOW_DEV_AUTH=true")
            if len(self.dev_jwt_secret.get_secret_value()) < 32:
                raise ValueError(
                    "Local authentication requires a random DEV_JWT_SECRET of at least 32 characters"
                )
            if urlsplit(self.dev_jwt_issuer).hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Local issuer must be loopback")
        if self.environment in {"staging", "production"}:
            if self.auth_mode != "supabase" or not self.supabase_url.startswith("https://"):
                raise ValueError("Hosted environments require HTTPS Supabase authentication")
            if not self.supabase_publishable_key.get_secret_value():
                raise ValueError(
                    "Hosted environments require the Supabase publishable key for confirmed-email checks"
                )
            if self.storage_backend != "supabase" or not self.supabase_service_role_key.get_secret_value():
                raise ValueError("Hosted environments require private Supabase storage credentials")
            from urllib.parse import parse_qs

            for database_url in (self.database_url, self.migration_database_url):
                if database_url and parse_qs(urlsplit(database_url).query).get("sslmode", [""])[0] not in {
                    "require",
                    "verify-ca",
                    "verify-full",
                }:
                    raise ValueError("Hosted database connections must enforce TLS")
            if not self.encryption_key.get_secret_value() or len(self.audit_hmac_key.get_secret_value()) < 32:
                raise ValueError("Hosted environments require encryption and audit HMAC keys")
            if len(self.readiness_token.get_secret_value()) < 32:
                raise ValueError("Hosted environments require a private readiness token")
            if not self.cors_origins or any(
                not origin.startswith("https://") for origin in self.cors_origins
            ):
                raise ValueError("Hosted CORS origins must explicitly use HTTPS")
            if {"localhost", "127.0.0.1", "testserver"}.intersection(self.trusted_hosts):
                raise ValueError("Hosted trusted hosts must be explicitly configured")
        if self.encryption_key.get_secret_value():
            from cryptography.fernet import Fernet

            Fernet(self.encryption_key.get_secret_value().encode())
        return self

    @property
    def jwt_issuer(self) -> str:
        if self.auth_mode == "local":
            return self.dev_jwt_issuer
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.jwt_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
