"""B03 integration: worker jobs send_email (J01) and cleanup_expired_tokens (J03).

SMTP is replaced by a fake for the retry schedule; real delivery to Mailpit is
checked by the live script (05_stage03/20261112_b03_test.sh).
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from arq import Retry
from sqlalchemy import select

from app.core import db, mail
from app.core.security import hash_password, new_token
from app.models.public import (
    EmailVerificationToken,
    Invitation,
    Organization,
    PasswordResetToken,
    RefreshToken,
    User,
)
from app.worker import jobs
from app.worker.settings import WorkerSettings

CTX = {"link": "http://fe/verify-email?token=abc", "full_name": "Ann"}


def audit_actions(audit_dir: Path) -> list[dict]:
    f = audit_dir / "audit.log"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


# --------------------------------------------------------------------------- #
# send_email (no containers needed)
# --------------------------------------------------------------------------- #
def test_worker_registration() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert {"ping", "send_email"} <= names
    send = next(f for f in WorkerSettings.functions if getattr(f, "name", "") == "send_email")
    assert send.max_tries == 4  # type: ignore[union-attr]
    cron = WorkerSettings.cron_jobs[0]
    assert cron.name == "cron:cleanup_expired_tokens"
    assert cron.hour == {3} and cron.minute == {0}


async def test_send_email_success(monkeypatch: pytest.MonkeyPatch, audit_log: Path) -> None:
    sent = []

    async def fake_send(settings, to, rendered) -> None:  # noqa: ANN001
        sent.append((to, rendered.subject))

    monkeypatch.setattr(mail, "send", fake_send)
    assert await jobs.send_email({"job_try": 1}, "verify_email", "a@x.test", CTX) == "sent"
    assert sent and sent[0][0] == "a@x.test"


@pytest.mark.parametrize(("job_try", "delay"), [(1, 30), (2, 120), (3, 600)])
async def test_send_email_retry_schedule(
    monkeypatch: pytest.MonkeyPatch, audit_log: Path, job_try: int, delay: int
) -> None:
    async def broken(*a: object) -> None:
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(mail, "send", broken)
    with pytest.raises(Retry) as exc:
        await jobs.send_email({"job_try": job_try}, "verify_email", "a@x.test", CTX)
    assert exc.value.defer_score == delay * 1000  # arq stores milliseconds


async def test_send_email_gives_up_and_audits(
    monkeypatch: pytest.MonkeyPatch, audit_log: Path
) -> None:
    async def broken(*a: object) -> None:
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(mail, "send", broken)
    result = await jobs.send_email(
        {"job_try": 4}, "reset_password", "b@x.test", {**CTX, "expires_minutes": 60}, "acme"
    )
    assert result == "failed"
    line = [x for x in audit_actions(audit_log.parent) if x["action"] == "email.failed"][-1]
    assert line["org"] == "acme" and line["result"] == "error"
    assert line["diff"]["tries"] == 4 and "smtp down" in line["diff"]["error"]


async def test_send_email_template_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, audit_log: Path
) -> None:
    async def never(*a: object) -> None:
        raise AssertionError("must not send")

    monkeypatch.setattr(mail, "send", never)
    # missing "link" -> render error on the FIRST try, no Retry raised
    assert await jobs.send_email({"job_try": 1}, "verify_email", "c@x.test", {}) == "failed"


# --------------------------------------------------------------------------- #
# cleanup_expired_tokens (Postgres)
# --------------------------------------------------------------------------- #
@pytest.fixture
async def b03_engine(b03_db_url: str, audit_log: Path) -> AsyncIterator[None]:
    db.init_engine(b03_db_url)
    yield
    await db.dispose_engine()


@pytest.mark.integration
async def test_cleanup_deletes_only_dead_rows(b03_engine: None) -> None:
    now = datetime.now(UTC)
    past, future = now - timedelta(hours=1), now + timedelta(hours=1)
    async with db.get_session_factory()() as s:
        user = User(
            email=f"cleanup-{uuid.uuid4().hex[:8]}@x.test",
            password_hash=hash_password("cleanup-pass-123"),
        )
        org_slug = f"cl_{uuid.uuid4().hex[:8]}"
        org = Organization(name=org_slug, slug=org_slug, schema_name=f"tenant_{org_slug}")
        s.add_all([user, org])
        await s.flush()

        def tok() -> str:
            return new_token()[1]

        keep, drop = [], []
        for model in (EmailVerificationToken, PasswordResetToken):
            live = model(user_id=user.id, token_hash=tok(), expires_at=future)
            expired = model(user_id=user.id, token_hash=tok(), expires_at=past)
            used = model(user_id=user.id, token_hash=tok(), expires_at=future, used_at=now)
            keep.append(live)
            drop += [expired, used]
        fam = uuid.uuid4()
        rt_live = RefreshToken(user_id=user.id, family_id=fam, token_hash=tok(), expires_at=future)
        # D11: revoked but not expired is KEPT (needed for reuse detection).
        rt_revoked = RefreshToken(
            user_id=user.id, family_id=fam, token_hash=tok(), expires_at=future, revoked_at=now
        )
        rt_expired = RefreshToken(user_id=user.id, family_id=fam, token_hash=tok(), expires_at=past)
        inv_open = Invitation(
            org_id=org.id, email="open@x.test", role_key="user", token_hash=tok(), expires_at=future
        )
        inv_expired = Invitation(
            org_id=org.id, email="old@x.test", role_key="user", token_hash=tok(), expires_at=past
        )
        inv_accepted = Invitation(
            org_id=org.id,
            email="acc@x.test",
            role_key="user",
            token_hash=tok(),
            expires_at=past,
            accepted_at=past,
        )
        keep += [rt_live, rt_revoked, inv_open, inv_accepted]
        drop += [rt_expired, inv_expired]
        s.add_all(keep + drop)
        await s.commit()
        keep_ids = {(type(x).__name__, x.id) for x in keep}
        drop_ids = {(type(x).__name__, x.id) for x in drop}

    counts = await jobs.cleanup_expired_tokens({"job_id": "t"})
    assert counts["email_verification_tokens"] >= 2 and counts["refresh_tokens"] >= 1

    async with db.get_session_factory()() as s:
        remaining = set()
        for model in (EmailVerificationToken, PasswordResetToken, RefreshToken, Invitation):
            ids = (await s.scalars(select(model.id))).all()
            remaining |= {(model.__name__, i) for i in ids}
    assert keep_ids <= remaining
    assert not (drop_ids & remaining)

    # Idempotent: a second run finds none of OUR rows to delete.
    await jobs.cleanup_expired_tokens({"job_id": "t2"})
    async with db.get_session_factory()() as s:
        for model in (EmailVerificationToken, PasswordResetToken, RefreshToken, Invitation):
            ids = set((await s.scalars(select(model.id))).all())
            assert {i for n, i in keep_ids if n == model.__name__} <= ids
