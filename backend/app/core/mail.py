"""Email: template rendering, SMTP sending, queueing (design B03 §3.5, object S06).

Flow (system_design §6): application code calls `queue_email(...)`, which only
enqueues the arq job `send_email`; the worker calls `render()` then `send()`
with retry (app/worker/jobs.py). The API process never talks SMTP itself, so a
slow or broken mail server cannot slow down requests.

Templates live in app/templates/email as three files per email:
    <name>.subject.txt   one line, plain text
    <name>.txt           plain-text body
    <name>.html          HTML body (autoescaped)
"""

from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path
from typing import Any

import aiosmtplib
import structlog
from arq.connections import ArqRedis
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.config import Settings

log = structlog.get_logger("app.mail")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
TEMPLATES = ("verify_email", "reset_password", "invite_user")
SEND_EMAIL_JOB = "send_email"  # arq function name, see worker/jobs.py
SMTP_TIMEOUT_S = 15


class TemplateError(ValueError):
    """Unknown template or missing variable: a programming error, never retried."""


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


@lru_cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        # Escape only the HTML bodies; subject/text are plain text.
        autoescape=select_autoescape(enabled_extensions=("html",), default=False),
        undefined=StrictUndefined,  # a missing variable fails loudly instead of rendering ""
        keep_trailing_newline=True,
    )


def render(template: str, context: dict[str, Any], settings: Settings) -> RenderedEmail:
    """Render subject, text and html for `template`. Raises TemplateError."""
    if template not in TEMPLATES:
        raise TemplateError(f"unknown email template {template!r}")
    ctx = {"app_name": settings.app_name, "frontend_url": settings.frontend_url, **context}
    try:
        env = _env()
        subject = env.get_template(f"{template}.subject.txt").render(ctx).strip()
        text = env.get_template(f"{template}.txt").render(ctx)
        html = env.get_template(f"{template}.html").render(ctx)
    except Exception as exc:  # jinja2 UndefinedError, TemplateNotFound, syntax errors
        raise TemplateError(f"cannot render {template!r}: {exc}") from exc
    # Header injection guard: a subject must be a single line.
    subject = " ".join(subject.splitlines())
    return RenderedEmail(subject=subject, text=text, html=html)


def build_message(settings: Settings, to: str, rendered: RenderedEmail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = rendered.subject
    msg.set_content(rendered.text)
    msg.add_alternative(rendered.html, subtype="html")  # multipart/alternative
    return msg


async def send(settings: Settings, to: str, rendered: RenderedEmail) -> None:
    """Deliver one message over SMTP. Raises on any SMTP/network error.

    Dev (Mailpit): no auth, no TLS. When SMTP_USER is set (a real relay later),
    STARTTLS is required and login is used.
    """
    use_auth = bool(settings.smtp_user)
    await aiosmtplib.send(
        build_message(settings, to, rendered),
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=use_auth,
        timeout=SMTP_TIMEOUT_S,
    )
    log.info("mail.sent", to=to, subject=rendered.subject)


async def queue_email(
    redis: ArqRedis,
    template: str,
    to: str,
    context: dict[str, Any],
    *,
    org_slug: str | None = None,
) -> str | None:
    """Enqueue the `send_email` job. Returns the job id, or None if Redis failed.

    Never raises: the caller decides whether a lost email is fatal (resend
    verification -> 503) or must stay invisible (forgot-password -> 202, D8).
    NOTE: `context` travels through Redis and may contain a one-time link;
    Redis is internal-only and jobs are deleted after completion.
    """
    if template not in TEMPLATES:
        # Fail fast in the API rather than in the worker 30 s later.
        raise TemplateError(f"unknown email template {template!r}")
    try:
        job = await redis.enqueue_job(SEND_EMAIL_JOB, template, to, context, org_slug)
    except Exception as exc:
        log.error("mail.queue_failed", template=template, to=to, error=str(exc))
        return None
    job_id = job.job_id if job else None
    log.info("mail.queued", template=template, to=to, job_id=job_id)
    return job_id
