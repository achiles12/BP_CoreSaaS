"""B03 unit: email templates and message building (design B03 §3.5, §3.6)."""

import pytest

from app.config import Settings
from app.core import mail

S = Settings(app_env="test", app_name="Acme Cloud", smtp_from="no-reply@test.local")

CONTEXTS = {
    "verify_email": {"link": "http://fe/verify-email?token=T1", "full_name": "Ann"},
    "reset_password": {
        "link": "http://fe/reset-password?token=T2",
        "full_name": None,
        "expires_minutes": 60,
    },
    "invite_user": {
        "link": "http://fe/accept-invite?token=T3",
        "org_name": "Acme",
        "role_key": "staff",
        "inviter_name": "Bob",
    },
}


@pytest.mark.parametrize("name", mail.TEMPLATES)
def test_every_template_renders(name: str) -> None:
    r = mail.render(name, CONTEXTS[name], S)
    link = CONTEXTS[name]["link"]
    assert r.subject and "\n" not in r.subject
    assert link in r.text and link in r.html
    assert "Acme Cloud" in r.html
    assert r.html.lstrip().lower().startswith("<!doctype html>")


def test_missing_variable_fails_loudly() -> None:
    with pytest.raises(mail.TemplateError, match="link"):
        mail.render("verify_email", {"full_name": "x"}, S)


def test_unknown_template() -> None:
    with pytest.raises(mail.TemplateError):
        mail.render("nope", {}, S)


def test_html_is_escaped_text_is_not() -> None:
    ctx = {**CONTEXTS["invite_user"], "org_name": "<script>x</script>"}
    r = mail.render("invite_user", ctx, S)
    assert "<script>" not in r.html and "&lt;script&gt;" in r.html
    assert "<script>x</script>" in r.text


def test_build_message_is_multipart() -> None:
    r = mail.render("verify_email", CONTEXTS["verify_email"], S)
    msg = mail.build_message(S, "ann@x.test", r)
    assert msg["From"] == "no-reply@test.local" and msg["To"] == "ann@x.test"
    assert msg.get_content_type() == "multipart/alternative"
    types = [p.get_content_type() for p in msg.iter_parts()]
    assert types == ["text/plain", "text/html"]


async def test_queue_email_rejects_unknown_template() -> None:
    with pytest.raises(mail.TemplateError):
        await mail.queue_email(None, "nope", "a@b.c", {})  # type: ignore[arg-type]


async def test_queue_email_swallows_redis_errors() -> None:
    class Broken:
        async def enqueue_job(self, *a: object, **k: object) -> None:
            raise ConnectionError("redis down")

    assert await mail.queue_email(Broken(), "verify_email", "a@b.c", {}) is None  # type: ignore[arg-type]
