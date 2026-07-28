"""Invite emails — optional.

If SMTP settings are configured (SMTP_HOST etc. in .env), an invite email is
sent. If not, sending is skipped and the caller shows the credentials to the
admin to share manually. This keeps the invite flow working out of the box and
lets real email be switched on later with zero code changes.
"""

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

log = logging.getLogger("backend.email")


def smtp_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_username and s.smtp_password)


def send_invite(to_email: str, full_name: str, temp_password: str, invite_link: str) -> bool:
    """Send an invite. Returns True if an email actually went out, False if SMTP
    isn't configured (or sending failed) — the caller then shares credentials
    manually. Never raises, so a mail hiccup can't fail user creation."""
    if not smtp_configured():
        return False

    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = "You've been invited to Cloudera Ops Monitoring"
    msg["From"] = s.smtp_from
    msg["To"] = to_email
    msg.set_content(
        f"Hello {full_name or ''},\n\n"
        f"An account has been created for you on Cloudera Ops Monitoring.\n\n"
        f"Sign in here: {invite_link}\n"
        f"Email: {to_email}\n"
        f"Temporary password: {temp_password}\n\n"
        f"You'll be asked to set a new password on first sign-in.\n\n"
        f"— Blutech Consulting"
    )
    return _send(msg, to_email, "Invite")


def send_password_reset(to_email: str, full_name: str, temp_password: str, login_link: str) -> bool:
    """Send a password-reset email with a temporary password. Returns True if an
    email actually went out, False if SMTP isn't configured (or sending failed).
    Never raises — a mail hiccup must not fail an admin reset or the
    forgot-password flow."""
    if not smtp_configured():
        return False

    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = "Your Cloudera Ops Monitoring password was reset"
    msg["From"] = s.smtp_from
    msg["To"] = to_email
    msg.set_content(
        f"Hello {full_name or ''},\n\n"
        f"Your password for Cloudera Ops Monitoring has been reset.\n\n"
        f"Sign in here: {login_link}\n"
        f"Email: {to_email}\n"
        f"Temporary password: {temp_password}\n\n"
        f"For your security, you'll be asked to set a new password on your next sign-in.\n"
        f"If you didn't request this, contact your administrator.\n\n"
        f"— Blutech Consulting"
    )
    return _send(msg, to_email, "Password-reset")


def _send(msg: EmailMessage, to_email: str, kind: str) -> bool:
    """Deliver a prepared message over SMTP. Shared by the invite and
    password-reset senders. Never raises — returns False on any failure so the
    caller can fall back to showing credentials on screen."""
    s = get_settings()
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
            if s.smtp_use_tls:
                server.starttls()
            server.login(s.smtp_username, s.smtp_password)
            server.send_message(msg)
        log.info("%s email sent to %s", kind, to_email)
        return True
    except Exception as exc:  # noqa: BLE001 — never let email break the flow
        log.warning("%s email to %s failed (%s); credentials shown to admin instead", kind, to_email, exc)
        return False
