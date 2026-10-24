"""Send the rendered digest via Brevo SMTP (STARTTLS on port 587)."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

from .render import Rendered

log = logging.getLogger(__name__)

BREVO_HOST = "smtp-relay.brevo.com"
BREVO_PORT = 587


class EmailConfigError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise EmailConfigError(f"Missing required environment variable: {name}")
    return val


def send(rendered: Rendered) -> None:
    login = _require_env("BREVO_SMTP_LOGIN")
    key = _require_env("BREVO_SMTP_KEY")
    sender = _require_env("SENDER_EMAIL")
    recipient = _require_env("RECIPIENT_EMAIL")

    msg = EmailMessage()
    msg["Subject"] = (
        f"Daily Brief \u2014 {rendered.digest_date.isoformat()} "
        f"\u2014 {rendered.total_items} items"
    )
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(rendered.plain_text)
    msg.add_alternative(rendered.html, subtype="html")

    log.info("Sending digest to %s via Brevo SMTP", recipient)
    with smtplib.SMTP(BREVO_HOST, BREVO_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(login, key)
        smtp.send_message(msg)
    log.info("Email delivered.")
