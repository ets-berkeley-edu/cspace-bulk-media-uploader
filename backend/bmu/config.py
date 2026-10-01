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

    # AWS (or local stand-ins: DynamoDB Local, moto)
    aws_region: str = "us-west-2"
    dynamodb_endpoint: str | None = None
    s3_endpoint: str | None = None
    # Endpoint the browser uses for presigned uploads (differs from s3_endpoint inside Docker)
    s3_public_endpoint: str | None = None
    s3_bucket: str = "bmu-staging"
    s3_kms_key_id: str | None = None  # SSE-KMS key for staged files (AWS); uploads must use it
    upload_url_seconds: int = 900  # a presigned upload is good for about 15 minutes
    abandoned_upload_hours: float = 24  # staged files no document refers to are deleted after about a day
    table_prefix: str = "bmu"
    create_tables: bool = False  # local development only

    # Credential encryption: "local" uses keys from the environment, "kms" uses AWS KMS envelope encryption
    crypto_mode: Literal["local", "kms"] = "local"
    session_key_b64: str | None = None
    job_key_b64: str | None = None
    kms_session_key_id: str | None = None
    kms_job_key_id: str | None = None

    session_hours: float = 8.0  # absolute session timeout
    session_idle_minutes: int = 30  # signed out after this long without activity
    draft_days: int = 30  # a draft that has never run is deleted (a fix is reverted) this long after it was last saved
    completed_days: int = 30  # a Completed job is removed this long after it finished
    protected_draft_days: int = 7  # a draft with a protected file expires this long after it was last saved
    protected_staged_days: int = 7  # a protected file's staged upload is removed this long after its job stopped
    credential_hours: float = 72.0
    cookie_secure: bool = True
    # The session cookie's name. Environments that share a host name (two local stacks on different ports) need
    # different names: browsers send a host's cookies to every port, so one would otherwise sign the other out.
    cookie_name: str = "bmu_session"
    # Which environment this is, shown on the sign-in page and in the header (e.g. "Local · PAHMA QA"); empty: none.
    env_label: str = ""
    max_file_bytes: int = 2 * 1024**3
    max_rows: int = 1000

    # Development only (design: Job scheduling): every moment counts as run time, so a queued job without its own
    # run time is due at once, as before scheduling existed. Pause and hold still apply. Env BMU_ALWAYS_RUN_TIME.
    always_run_time: bool = False
    # Demo builds only: the Demo tools pane's endpoints (/api/_demo/...), which slow the browser's uploads, control the
    # simulated CollectionSpace and delete every job in the tenant. Off (404) unless BMU_DEMO=true; never in production.
    demo: bool = False

    worker_poll_seconds: float = 2.0
    worker_lock_seconds: int = 120
    heartbeat_seconds: float = 30.0  # a running job's heartbeat is renewed this often
    heartbeat_stale_seconds: float = 300.0  # a Running job whose heartbeat is older stops as "worker_stopped"
    static_dir: str | None = None  # serve the built Vue app from here, if set

    def draft_days_for(self, job: dict | None) -> int:
        """A draft's expiry period: 7 days if any of its documents is a protected file (excluded ones too), 30
        otherwise (design: Drafts, Expiry)."""
        return self.protected_draft_days if (job or {}).get("protectedCount") else self.draft_days


@lru_cache
def get_settings() -> Settings:
    return Settings()
