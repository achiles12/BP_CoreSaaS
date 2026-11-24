"""Append-only JSON-lines audit writer (design B01 §3.5, object S05).

One line per event in AUDIT_LOG_DIR/audit.log, e.g.
  {"ts":"2026-11-11T10:15:02.123Z","org":"acme","actor":"7f3c…","action":"files.delete",
   "entity":"file","entity_id":"a1b2…","diff":{"status":["active","deleted"]},
   "ip":"172.18.0.1","request_id":"c9d1…","result":"ok"}

- Written through a dedicated stdlib logger with a WatchedFileHandler, so host
  logrotate can move the file and the next write reopens it (no copytruncate).
- `ip` and `request_id` are taken from the request context automatically.
- Values of sensitive keys are redacted at any depth before writing.
- Writes are synchronous: a ~1 KB append is cheaper than a thread hop (D9).
"""

import io
import json
import logging
import os
from datetime import UTC, datetime
from logging.handlers import WatchedFileHandler
from pathlib import Path
from typing import Any, cast

import structlog

from app.core.errors import AppError
from app.core.logging import get_client_ip, get_request_id

log = structlog.get_logger("app.audit")

AUDIT_FILE_NAME = "audit.log"
AUDIT_FILE_MODE = 0o640  # owner rw, group r (read over SFTP by the ops group)
# Any dict key CONTAINING one of these (case-insensitive) is redacted, so
# "new_password", "refresh_token", "client_secret" are all covered.
SENSITIVE_KEYS = ("password", "token", "secret", "authorization")
REDACTED = "[redacted]"

_audit_logger = logging.getLogger("audit")
_audit_logger.propagate = False  # never duplicate audit lines into app logs
_audit_logger.setLevel(logging.INFO)

# Set by init_audit(); False until then so record() can fail clearly.
_fail_closed = True


class AuditWriteError(AppError):
    """Raised for sensitive actions when the audit line cannot be written (D2)."""

    status, code, default_message = 500, "internal_error", "Audit trail unavailable"


class _OwnerOnlyWatchedFileHandler(WatchedFileHandler):
    """WatchedFileHandler that creates (and re-creates after rotation) the file as 0640."""

    def _open(self) -> io.TextIOWrapper:
        # os.open with an explicit mode; umask cannot widen it, only narrow.
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT, AUDIT_FILE_MODE)
        return cast(io.TextIOWrapper, os.fdopen(fd, self.mode, encoding=self.encoding))

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 (logging API)
        # logging normally prints and SWALLOWS write errors (full disk, removed
        # dir). Re-raise so record() can detect them and apply fail-closed.
        raise  # re-raises the exception currently being handled inside emit()


def init_audit(directory: str, *, fail_closed: bool = True) -> Path:
    """Attach the file handler. Fails fast if the directory is not writable (D4).

    Returns the audit file path. Calling again replaces the handler (tests).
    """
    global _fail_closed
    path = Path(directory)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        log.error("audit.dir_not_writable", directory=str(path), error=str(exc))
        raise RuntimeError(f"audit directory {path} is not writable: {exc}") from exc

    close_audit()
    handler = _OwnerOnlyWatchedFileHandler(path / AUDIT_FILE_NAME, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))  # the message IS the JSON line
    _audit_logger.addHandler(handler)
    _fail_closed = fail_closed
    log.info("audit.ready", file=str(path / AUDIT_FILE_NAME), fail_closed=fail_closed)
    return path / AUDIT_FILE_NAME


def close_audit() -> None:
    """Detach the file handler and restore the fail-closed default.

    Resetting matters: without it, a writer that was once initialised with
    fail_closed=False would keep swallowing sensitive-write failures after
    being closed (found by test_record_before_init_fails_closed_for_sensitive).
    """
    global _fail_closed
    for h in list(_audit_logger.handlers):
        _audit_logger.removeHandler(h)
        h.close()
    _fail_closed = True


def redact(value: Any) -> Any:
    """Return a copy with values of sensitive keys replaced, at any nesting depth."""
    if isinstance(value, dict):
        return {
            k: REDACTED
            if isinstance(k, str) and any(s in k.lower() for s in SENSITIVE_KEYS)
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_line(
    action: str,
    *,
    entity: str | None = None,
    entity_id: str | None = None,
    org: str | None = None,
    actor: str | None = None,
    diff: dict[str, Any] | None = None,
    result: str = "ok",
) -> str:
    """Serialise one audit event (all 10 fields always present, null if unknown)."""
    line = {
        "ts": _utc_now(),
        "org": org,
        "actor": actor,
        "action": action,
        "entity": entity,
        "entity_id": None if entity_id is None else str(entity_id),
        "diff": redact(diff) if diff is not None else None,
        "ip": get_client_ip(),
        "request_id": get_request_id(),
        "result": result,
    }
    # default=str: UUIDs/datetimes in diffs serialise instead of crashing the write.
    return json.dumps(line, ensure_ascii=False, separators=(",", ":"), default=str)


def record(
    action: str,
    *,
    entity: str | None = None,
    entity_id: str | None = None,
    org: str | None = None,
    actor: str | None = None,
    diff: dict[str, Any] | None = None,
    result: str = "ok",
    sensitive: bool = False,
) -> None:
    """Append one audit line.

    action: "<module>.<verb>", e.g. "files.delete", "auth.login".
    sensitive: True for security-relevant actions; with AUDIT_FAIL_CLOSED a
        write failure raises AuditWriteError (-> 500) instead of being swallowed.
    """
    try:
        if not _audit_logger.handlers:
            raise RuntimeError("audit writer not initialised")
        payload = build_line(
            action,
            entity=entity,
            entity_id=entity_id,
            org=org,
            actor=actor,
            diff=diff,
            result=result,
        )
        _audit_logger.info(payload)  # handler errors propagate (see handleError)
    except Exception as exc:
        log.error("audit.write_failed", action=action, error=str(exc), sensitive=sensitive)
        if sensitive and _fail_closed:
            raise AuditWriteError() from exc
