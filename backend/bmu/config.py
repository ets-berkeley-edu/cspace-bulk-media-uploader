"""Settings, read from environment variables prefixed with BMU_ (see .env.example)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BMU_", env_file=".env", extra="ignore")

    # CollectionSpace server (without /cspace-services), e.g. https://pahma.qa.collectionspace.org
    cspace_url: str = "http://localhost:8180"
    cspace_timeout_seconds: float = 300.0
    tenant: str = "pahma"

    # AWS (or local stand-ins: DynamoDB Local / moto, MinIO)
    aws_region: str = "us-west-2"
    dynamodb_endpoint: str | None = None
    s3_endpoint: str | None = None
    # Endpoint the browser uses for presigned uploads (differs from s3_endpoint inside Docker)
    s3_public_endpoint: str | None = None
    s3_bucket: str = "bmu-staging"
    table_prefix: str = "bmu"
    create_tables: bool = False  # local development only

    # Credential encryption: "local" uses keys from the environment, "kms" uses AWS KMS envelope encryption
    crypto_mode: Literal["local", "kms"] = "local"
    session_key_b64: str | None = None
    job_key_b64: str | None = None
    kms_session_key_id: str | None = None
    kms_job_key_id: str | None = None

    session_hours: float = 8.0
    credential_hours: float = 72.0
    cookie_secure: bool = True
    max_file_bytes: int = 2 * 1024**3
    max_rows: int = 1000

    worker_poll_seconds: float = 2.0
    worker_lock_seconds: int = 120
    static_dir: str | None = None  # serve the built Vue app from here, if set


@lru_cache
def get_settings() -> Settings:
    return Settings()
