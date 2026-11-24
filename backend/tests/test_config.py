"""T1: configuration (design B01 §3.1, D8)."""

import pytest
from pydantic import ValidationError

from app.config import DEV_SECRET_KEY, Settings
from app.core.security import access_cookie, refresh_cookie

STRONG_KEY = "x" * 40


def test_defaults_load() -> None:
    s = Settings()
    assert s.app_env == "dev"
    assert s.access_token_minutes == 15
    assert s.audit_fail_closed is True
    assert s.cors_origins == ["http://localhost:3200"]


def test_env_overrides_and_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_MINUTES", "30")
    monkeypatch.setenv("log_level", "debug")
    s = Settings()
    assert s.access_token_minutes == 30
    assert s.log_level == "DEBUG"


def test_cors_origins_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a:3200, http://b:3200 ,")
    assert Settings().cors_origins == ["http://a:3200", "http://b:3200"]


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_bad_int_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_MINUTES", value)
    with pytest.raises(ValidationError):
        Settings()


def test_bad_env_name_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="staging")  # pyright: ignore[reportArgumentType]


def test_prod_refuses_dev_secret_and_insecure_cookie() -> None:
    with pytest.raises(ValidationError) as ei:
        Settings(app_env="prod", secret_key=DEV_SECRET_KEY, cookie_secure=False)
    msg = str(ei.value)
    # Both problems reported at once, not one per restart.
    assert "SECRET_KEY is the dev default" in msg
    assert "COOKIE_SECURE must be true" in msg


def test_prod_refuses_short_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(app_env="prod", secret_key="short", cookie_secure=True)


def test_prod_accepts_safe_settings() -> None:
    s = Settings(
        app_env="prod",
        secret_key=STRONG_KEY,
        cookie_secure=True,
        database_url="postgresql+asyncpg://app:not-the-default@postgres:5432/app",
        s3_access_key="prod-access",
        s3_secret_key="prod-secret-value",
    )
    assert s.is_prod


def test_prod_refuses_default_db_and_storage_credentials() -> None:
    """B13 D10."""
    with pytest.raises(ValidationError) as ei:
        Settings(app_env="prod", secret_key=STRONG_KEY, cookie_secure=True)
    msg = str(ei.value)
    assert "database password is the dev default" in msg
    assert "S3_ACCESS_KEY is the dev default" in msg
    assert "S3_SECRET_KEY is the dev default" in msg


@pytest.mark.parametrize("bad", ["a b", "a;b", "a=b", "a,b"])
def test_cookie_prefix_rejects_unsafe_characters(bad: str) -> None:
    with pytest.raises(ValidationError):
        Settings(cookie_prefix=bad)


def test_cookie_names_follow_the_prefix() -> None:
    """B13 D6: clones on one host must not share cookies."""
    s = Settings(cookie_prefix="acme_")
    assert (access_cookie(s), refresh_cookie(s)) == ("acme_access_token", "acme_refresh_token")
    assert access_cookie(Settings()) == "access_token"


def test_export_settings_defaults_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """B07 D2: retention days >= 0 (0 = keep), cleanup time is a valid hour/minute."""
    s = Settings()
    assert (s.export_retention_days, s.export_cleanup_hour, s.export_cleanup_minute) == (7, 3, 45)
    monkeypatch.setenv("EXPORT_RETENTION_DAYS", "0")
    assert Settings().export_retention_days == 0
    for name, bad in (
        ("EXPORT_RETENTION_DAYS", "-1"),
        ("EXPORT_CLEANUP_HOUR", "24"),
        ("EXPORT_CLEANUP_MINUTE", "60"),
    ):
        monkeypatch.setenv(name, bad)
        with pytest.raises(ValidationError):
            Settings()
        monkeypatch.delenv(name)
