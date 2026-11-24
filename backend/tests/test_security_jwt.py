"""B03 unit: JWT access tokens and auth cookies (design B03 §3.2, D4, D15)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Response

from app.config import Settings
from app.core.errors import Unauthenticated
from app.core.security import (
    ACCESS_COOKIE,
    JWT_ALGORITHM,
    REFRESH_COOKIE,
    clear_auth_cookies,
    create_access_token,
    decode_access_token,
    set_auth_cookies,
)

S = Settings(app_env="test", secret_key="unit-test-secret-key-0123456789abcdef")


def test_round_trip() -> None:
    uid, fam = uuid.uuid4(), uuid.uuid4()
    claims = decode_access_token(create_access_token(uid, fam, S), S)
    assert claims.user_id == uid
    assert claims.family_id == fam
    remaining = claims.expires_at - datetime.now(UTC)
    assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)


def _forge(**overrides: object) -> str:
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": str(uuid.uuid4()),
        "fam": str(uuid.uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + 60,
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, S.secret_key, algorithm=JWT_ALGORITHM)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _forge(exp=int(datetime.now(UTC).timestamp()) - 60), id="expired"),
        pytest.param(lambda: _forge(type="refresh"), id="wrong-type"),
        pytest.param(lambda: _forge(fam=None), id="missing-fam"),
        pytest.param(lambda: _forge(sub="not-a-uuid"), id="bad-sub"),
        pytest.param(
            lambda: jwt.encode({"sub": "x"}, "another-secret-key-0123456789abcdef", "HS256"),
            id="wrong-key",
        ),
        pytest.param(lambda: _forge() + "x", id="tampered"),
        pytest.param(lambda: "garbage", id="garbage"),
        pytest.param(
            lambda: jwt.encode(
                {"sub": str(uuid.uuid4()), "fam": str(uuid.uuid4()), "type": "access", "exp": 9e9},
                None,
                algorithm="none",
            ),
            id="alg-none",
        ),
    ],
)
def test_rejected_tokens(token) -> None:  # noqa: ANN001
    with pytest.raises(Unauthenticated):
        decode_access_token(token(), S)


def _set_cookie_headers(resp: Response) -> dict[str, str]:
    out = {}
    for k, v in resp.raw_headers:
        if k == b"set-cookie":
            text = v.decode()
            out[text.split("=", 1)[0]] = text.lower()
    return out


def test_cookie_attributes_dev() -> None:
    resp = Response()
    set_auth_cookies(resp, "AAA", "RRR", S)
    c = _set_cookie_headers(resp)
    assert "httponly" in c[ACCESS_COOKIE] and "samesite=lax" in c[ACCESS_COOKIE]
    assert "path=/;" in c[ACCESS_COOKIE] or c[ACCESS_COOKIE].endswith("path=/")
    assert "max-age=900" in c[ACCESS_COOKIE]
    assert "path=/api/auth" in c[REFRESH_COOKIE]
    assert f"max-age={14 * 86400}" in c[REFRESH_COOKIE]
    assert "secure" not in c[ACCESS_COOKIE]  # dev over plain http (D4)


def test_cookie_secure_and_custom_path() -> None:
    s = Settings(app_env="test", cookie_secure=True, refresh_cookie_path="/auth")
    resp = Response()
    set_auth_cookies(resp, "AAA", "RRR", s)
    c = _set_cookie_headers(resp)
    assert "secure" in c[ACCESS_COOKIE] and "secure" in c[REFRESH_COOKIE]
    assert "path=/auth" in c[REFRESH_COOKIE]


def test_clear_cookies_matches_paths() -> None:
    resp = Response()
    clear_auth_cookies(resp, S)
    c = _set_cookie_headers(resp)
    assert "max-age=0" in c[ACCESS_COOKIE] and "path=/api/auth" in c[REFRESH_COOKIE]


def test_prod_requires_secure_cookie() -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(app_env="prod", secret_key="x" * 40, cookie_secure=False)
