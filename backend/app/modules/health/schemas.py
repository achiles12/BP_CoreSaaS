"""Response models for the health module (shape documented in OpenAPI)."""

from typing import Literal

from pydantic import BaseModel


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class CheckResult(BaseModel):
    """Outcome of one dependency check."""

    ok: bool
    ms: float  # wall time of the check, milliseconds
    error: str | None = None  # short reason when ok is False


class ReadyResponse(BaseModel):
    status: Literal["ok", "fail"]
    checks: dict[str, CheckResult]  # keys: postgres, redis, storage
