"""T5 audit writer, T8 startup fail-fast (design B01 §3.5, D2, D4)."""

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import audit
from app.main import create_app

FIELDS = {
    "ts",
    "org",
    "actor",
    "action",
    "entity",
    "entity_id",
    "diff",
    "ip",
    "request_id",
    "result",
}


@pytest.fixture
def audit_file(audit_dir: Path) -> Iterator[Path]:
    path = audit.init_audit(str(audit_dir), fail_closed=True)
    yield path
    audit.close_audit()


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_line_has_all_fields_and_context(audit_file: Path) -> None:
    structlog.contextvars.bind_contextvars(request_id="rid-1", client_ip="10.0.0.9")
    try:
        audit.record(
            "files.delete",
            entity="file",
            entity_id="f1",
            org="acme",
            actor="u1",
            diff={"status": ["active", "deleted"]},
        )
    finally:
        structlog.contextvars.clear_contextvars()
    (line,) = read_lines(audit_file)
    assert set(line) == FIELDS
    assert line["action"] == "files.delete"
    assert line["request_id"] == "rid-1" and line["ip"] == "10.0.0.9"
    assert line["result"] == "ok"
    assert line["ts"].endswith("Z")


def test_outside_request_context_fields_are_null(audit_file: Path) -> None:
    audit.record("cli.selftest", actor="cli:niko")
    (line,) = read_lines(audit_file)
    assert line["request_id"] is None and line["ip"] is None and line["diff"] is None


def test_sensitive_keys_redacted_at_any_depth(audit_file: Path) -> None:
    audit.record(
        "users.update",
        diff={
            "password": "p1",
            "New_Password": "p2",
            "profile": {"refresh_token": "t", "name": "Ann"},
            "items": [{"client_secret": "s"}, {"ok": 1}],
            "Authorization": "Bearer x",
        },
    )
    (line,) = read_lines(audit_file)
    d = line["diff"]
    assert d["password"] == d["New_Password"] == d["Authorization"] == "[redacted]"
    assert d["profile"] == {"refresh_token": "[redacted]", "name": "Ann"}
    assert d["items"] == [{"client_secret": "[redacted]"}, {"ok": 1}]
    raw = audit_file.read_text()
    for secret in ("p1", "p2", '"t"', '"s"', "Bearer x"):
        assert secret not in raw


def test_file_mode_is_0640(audit_file: Path) -> None:
    audit.record("x.y")
    assert stat.S_IMODE(os.stat(audit_file).st_mode) == 0o640


def test_appends_one_line_per_event(audit_file: Path) -> None:
    for i in range(5):
        audit.record("x.n", entity_id=str(i))
    assert [entry["entity_id"] for entry in read_lines(audit_file)] == ["0", "1", "2", "3", "4"]


def test_survives_logrotate_rename(audit_file: Path) -> None:
    audit.record("before.rotate")
    rotated = audit_file.with_name("audit.log.1")
    audit_file.rename(rotated)  # what logrotate does (no copytruncate)
    audit.record("after.rotate")
    assert [e["action"] for e in read_lines(rotated)] == ["before.rotate"]
    assert [e["action"] for e in read_lines(audit_file)] == ["after.rotate"]
    assert stat.S_IMODE(os.stat(audit_file).st_mode) == 0o640  # recreated file also 0640


def test_non_json_values_serialise(audit_file: Path) -> None:
    import uuid
    from datetime import UTC, datetime

    uid = uuid.uuid4()
    audit.record("x.y", entity_id=uid, diff={"at": datetime(2026, 1, 1, tzinfo=UTC)})  # pyright: ignore[reportArgumentType]
    (line,) = read_lines(audit_file)
    assert line["entity_id"] == str(uid)
    assert line["diff"]["at"].startswith("2026-01-01")


def _break_audit_dir(audit_file: Path) -> None:
    """Make the next write fail: remove the file and make the dir read-only."""
    audit_file.unlink(missing_ok=True)
    audit_file.parent.chmod(0o500)


def test_sensitive_write_failure_raises_when_fail_closed(audit_file: Path) -> None:
    _break_audit_dir(audit_file)
    try:
        with pytest.raises(audit.AuditWriteError):
            audit.record("auth.password_reset", sensitive=True)
    finally:
        audit_file.parent.chmod(0o700)


def test_non_sensitive_write_failure_is_swallowed_and_logged(
    audit_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.logging import configure_logging

    configure_logging("INFO")
    _break_audit_dir(audit_file)
    try:
        audit.record("files.view")  # must not raise
    finally:
        audit_file.parent.chmod(0o700)
    assert '"audit.write_failed"' in capsys.readouterr().out


def test_sensitive_failure_swallowed_when_fail_open(audit_dir: Path) -> None:
    path = audit.init_audit(str(audit_dir), fail_closed=False)
    try:
        _break_audit_dir(path)
        audit.record("auth.login", sensitive=True)  # AUDIT_FAIL_CLOSED=false: no raise
    finally:
        audit_dir.chmod(0o700)
        audit.close_audit()


def test_record_before_init_fails_closed_for_sensitive() -> None:
    audit.close_audit()
    with pytest.raises(audit.AuditWriteError):
        audit.record("auth.login", sensitive=True)


def test_init_rejects_unwritable_dir(tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    try:
        with pytest.raises(RuntimeError, match="not writable"):
            audit.init_audit(str(ro))
    finally:
        ro.chmod(0o700)


# ---------------------------------- T8 ------------------------------------- #
def test_startup_aborts_on_unwritable_audit_dir(tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    try:
        app = create_app(Settings(app_env="test", audit_log_dir=str(ro)))
        with pytest.raises(RuntimeError, match="not writable"), TestClient(app):
            pass  # entering the client runs the lifespan
    finally:
        ro.chmod(0o700)
