"""Typed application settings, read from environment variables.

This is the ONLY module that reads the environment (design B01 §3.1). Every
other module receives values through `get_settings()`, which keeps
configuration testable and documented in one place. Each key maps 1:1 to an
entry in `.env.example`; pydantic-settings matches env names case-insensitively
(`DATABASE_URL` -> `database_url`).
"""

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_VERSION = "0.1.0"

# The literal default shipped in .env.example / docker-compose.yml. Prod must
# never run with it (D8), so it is compared by value.
DEV_SECRET_KEY = "dev-only-change-me"  # noqa: S105 (documented dev default, refused in prod)
MIN_PROD_SECRET_LEN = 32
# Dev defaults of docker-compose.yml, refused in prod (B13 D10).
DEV_DB_PASSWORD = "app"  # noqa: S105 (dev default)
DEV_S3_ACCESS_KEY = "devaccesskey"
DEV_S3_SECRET_KEY = "devsecretkey-change-me"  # noqa: S105 (dev default)

# B05 D4: documents, images, text/CSV, zip and the Office formats (new and old).
DEFAULT_ALLOWED_MIME_TYPES: tuple[str, ...] = (
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/csv",
    "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
)

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """All runtime configuration. Defaults are safe DEV values matching compose."""

    model_config = SettingsConfigDict(
        env_file=None,  # compose injects env; tests pass values explicitly
        case_sensitive=False,
        extra="ignore",  # the container env has many unrelated variables
    )

    # --- application ---
    app_env: Literal["dev", "test", "prod"] = "dev"
    secret_key: str = DEV_SECRET_KEY
    frontend_url: str = "http://localhost:3200"
    # NoDecode: read the raw string and split on commas ourselves; the default
    # pydantic-settings behaviour would demand JSON ('["a","b"]').
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3200"]
    )
    tenant_header: str = "X-Tenant"
    app_name: str = "Core SaaS"  # product name shown in emails (B03 D14)
    log_level: LogLevel = "INFO"

    # --- auth ---
    access_token_minutes: int = Field(default=15, gt=0)
    refresh_token_days: int = Field(default=14, gt=0)
    cookie_secure: bool = False
    # B13 D6: browsers share cookies between ports of one host, so every clone
    # needs its own names. Empty = the plain names ("access_token", ...).
    cookie_prefix: str = Field(default="", pattern=r"^[A-Za-z0-9_-]*$")
    # B13 D8: `cli init` creates the demo org and users (only when APP_ENV=dev).
    seed_demo: bool = False
    # B03 D4: the browser reaches the backend as /api/auth/* once Next.js
    # proxies (B08); the refresh cookie is only sent to that path.
    refresh_cookie_path: str = "/api/auth"
    require_email_verification: bool = True
    # B03 D7: per IP+email, fixed 60 s window, on login/forgot/reset/resend/change.
    auth_rate_limit_per_minute: int = Field(default=5, gt=0)

    # --- infrastructure ---
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/app"
    redis_url: str = "redis://redis:6379/0"

    # --- email ---
    smtp_host: str = "mailpit"
    smtp_port: int = Field(default=1025, gt=0, lt=65536)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@app.local"

    # --- object storage (RustFS; path-style addressing, B00 D11) ---
    s3_endpoint: str = "http://rustfs:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = DEV_S3_ACCESS_KEY
    s3_secret_key: str = DEV_S3_SECRET_KEY
    s3_bucket: str = "app-files"
    s3_region: str = "us-east-1"  # RustFS ignores it, but boto requires one

    # --- limits ---
    max_upload_mb: int = Field(default=50, gt=0)
    # B05 D4: MIME types accepted by POST /files/presign-upload (comma-separated in env).
    allowed_mime_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_MIME_TYPES)
    )
    export_max_rows: int = Field(default=100_000, gt=0)
    # B07 D2: export files older than this are deleted by the daily cleanup and
    # the job is marked `expired`. 0 = keep export files forever.
    export_retention_days: int = Field(default=7, ge=0)
    # When the export cleanup cron runs (UTC; default 03:45, after J04 at 03:30).
    export_cleanup_hour: int = Field(default=3, ge=0, le=23)
    export_cleanup_minute: int = Field(default=45, ge=0, le=59)

    # --- audit ---
    audit_log_dir: str = "/var/log/app/audit"
    # D2: when an audit line for a sensitive action cannot be written, fail the
    # request (500) instead of letting it proceed unaudited.
    audit_fail_closed: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept 'a, b' from env as well as a real list from code/tests."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("allowed_mime_types", mode="before")
    @classmethod
    def _split_mime_types(cls, v: object) -> object:
        """'a/b, c/d' from env -> lower-cased list; a real list passes through."""
        if isinstance(v, str):
            items = [m.strip().lower() for m in v.split(",") if m.strip()]
            # compose passes "" when the key is unset: fall back to the default list
            return items or list(DEFAULT_ALLOWED_MIME_TYPES)
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_level(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _prod_guards(self) -> "Settings":
        """D8: refuse unsafe settings in prod. Reports every problem at once."""
        if self.app_env != "prod":
            return self
        problems: list[str] = []
        if self.secret_key == DEV_SECRET_KEY:
            problems.append("SECRET_KEY is the dev default")
        elif len(self.secret_key) < MIN_PROD_SECRET_LEN:
            problems.append(f"SECRET_KEY must be at least {MIN_PROD_SECRET_LEN} characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        if urlsplit(self.database_url).password == DEV_DB_PASSWORD:
            problems.append("the database password is the dev default")
        if self.s3_access_key == DEV_S3_ACCESS_KEY:
            problems.append("S3_ACCESS_KEY is the dev default")
        if self.s3_secret_key == DEV_S3_SECRET_KEY:
            problems.append("S3_SECRET_KEY is the dev default")
        if problems:
            raise ValueError("unsafe production settings: " + "; ".join(problems))
        return self

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so env is parsed once. Tests either pass a Settings instance to
    `create_app(settings=...)` or call `get_settings.cache_clear()`.
    """
    return Settings()
