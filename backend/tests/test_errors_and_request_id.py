"""T2 errors, T3 request id, T4 logging (design B01 §3.2, §3.3).

The app is used WITHOUT its lifespan (TestClient not entered as a context
manager), so no database or audit dir is needed.
"""

import json
import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config import Settings
from app.core import errors
from app.main import create_app

probe = APIRouter(prefix="/probe")


class Body(BaseModel):
    name: str
    password: str


@probe.get("/raise/{kind}")
async def raise_kind(kind: str) -> dict[str, str]:
    cls = {
        "bad_request": errors.BadRequest,
        "unauthenticated": errors.Unauthenticated,
        "permission_denied": errors.PermissionDenied,
        "not_found": errors.NotFound,
        "conflict": errors.Conflict,
        "rate_limited": errors.RateLimited,
        "service_unavailable": errors.ServiceUnavailable,
    }[kind]
    raise cls("custom message")


@probe.get("/boom")
async def boom() -> None:
    raise RuntimeError("secret internal detail")


@probe.post("/validate")
async def validate(body: Body) -> dict[str, str]:
    return {"ok": body.name}


@pytest.fixture
def app(unit_settings: Settings) -> FastAPI:
    a = create_app(unit_settings)
    a.include_router(probe)
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False: we want the real 500 response, as a browser sees it.
    return TestClient(app, raise_server_exceptions=False)


def assert_error_shape(resp, status: int, code: str) -> dict:  # noqa: ANN001
    assert resp.status_code == status
    body = resp.json()
    assert set(body) == {"error"}
    err = body["error"]
    assert err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    # Same id in body and header, so a user's screenshot can be matched to logs.
    assert err["request_id"] == resp.headers["X-Request-ID"]
    return err


# ---------------------------------- T2 ------------------------------------- #
@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("bad_request", 400),
        ("unauthenticated", 401),
        ("permission_denied", 403),
        ("not_found", 404),
        ("conflict", 409),
        ("rate_limited", 429),
        ("service_unavailable", 503),
    ],
)
def test_app_errors_map_to_status_and_code(client: TestClient, kind: str, status: int) -> None:
    err = assert_error_shape(client.get(f"/probe/raise/{kind}"), status, kind)
    assert err["message"] == "custom message"


def test_unknown_route_is_standard_404(client: TestClient) -> None:
    assert_error_shape(client.get("/does-not-exist"), 404, "not_found")


def test_wrong_method_is_standard_405(client: TestClient) -> None:
    assert_error_shape(client.post("/health/live"), 405, "method_not_allowed")


def test_validation_error_has_fields_and_no_input_echo(client: TestClient) -> None:
    resp = client.post("/probe/validate", json={"password": "hunter2-secret"})
    err = assert_error_shape(resp, 422, "validation_error")
    assert err["fields"][0]["loc"] == ["body", "name"]
    assert set(err["fields"][0]) == {"loc", "msg", "type"}
    assert "hunter2-secret" not in resp.text


def test_unhandled_exception_is_500_without_details(client: TestClient) -> None:
    resp = client.get("/probe/boom")
    err = assert_error_shape(resp, 500, "internal_error")
    assert err["message"] == "Unexpected error"
    assert "secret internal detail" not in resp.text
    assert "Traceback" not in resp.text


# ---------------------------------- T3 ------------------------------------- #
def test_request_id_generated_when_missing(client: TestClient) -> None:
    rid = client.get("/health/live").headers["X-Request-ID"]
    assert uuid.UUID(rid).version == 4


def test_valid_request_id_is_echoed(client: TestClient) -> None:
    resp = client.get("/health/live", headers={"X-Request-ID": "abc-123_X.y"})
    assert resp.headers["X-Request-ID"] == "abc-123_X.y"


@pytest.mark.parametrize(
    "bad", ["a" * 65, "evil\tinjected", 'quote"s', "spa ce", "semi;colon", "slash/x"]
)
def test_hostile_request_id_is_replaced(client: TestClient, bad: str) -> None:
    rid = client.get("/health/live", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
    assert rid != bad
    assert uuid.UUID(rid).version == 4


def test_request_ids_are_unique_per_request(client: TestClient) -> None:
    ids = {client.get("/health/live").headers["X-Request-ID"] for _ in range(20)}
    assert len(ids) == 20


# ---------------------------------- T4 ------------------------------------- #
def _json_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            out.append(json.loads(line))
    return out


def test_access_log_line_is_json_with_context(
    unit_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    # Build the app inside the test so the log handler binds to captured stdout.
    app = create_app(unit_settings)
    app.include_router(probe)
    c = TestClient(app, raise_server_exceptions=False)
    resp = c.get("/probe/raise/conflict", headers={"X-Request-ID": "log-test-1"})
    lines = _json_lines(capsys.readouterr().out)
    done = [entry for entry in lines if entry.get("event") == "request.done"]
    assert len(done) == 1
    entry = done[0]
    assert entry["request_id"] == "log-test-1" == resp.headers["X-Request-ID"]
    assert entry["status"] == 409
    assert entry["method"] == "GET" and entry["path"] == "/probe/raise/conflict"
    assert isinstance(entry["duration_ms"], float)
    assert entry["level"] == "info"
    # The error line of the same request carries the same request id.
    assert any(e.get("event") == "request.error" and e["request_id"] == "log-test-1" for e in lines)


def test_health_access_lines_are_quiet_at_info(
    unit_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    c = TestClient(create_app(unit_settings))
    c.get("/health/live")
    done = [e for e in _json_lines(capsys.readouterr().out) if e.get("event") == "request.done"]
    assert done == []  # D10: logged at DEBUG, hidden at INFO


def test_unhandled_exception_logs_traceback(
    unit_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    app = create_app(unit_settings)
    app.include_router(probe)
    TestClient(app, raise_server_exceptions=False).get("/probe/boom")
    lines = _json_lines(capsys.readouterr().out)
    exc_lines = [e for e in lines if e.get("event") == "request.unhandled_exception"]
    assert exc_lines and "secret internal detail" in exc_lines[0]["exception"]
    assert exc_lines[0]["level"] == "error"
