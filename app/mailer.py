"""Optionaler E-Mail-Versand (nur aktiv, wenn SMTP_HOST gesetzt ist)."""
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage

from flask import current_app


def mail_enabled():
    return bool(os.environ.get("SMTP_HOST"))


def _send(msg):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    security = os.environ.get("SMTP_SECURITY", "starttls").lower()  # starttls | ssl | none
    context = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
        if security == "starttls":
            server.starttls(context=context)
    with server:
        if user:
            server.login(user, password or "")
        server.send_message(msg)


def send_mail(recipients, subject, body):
    recipients = [r for r in recipients if r]
    from . import modules
    if not recipients or not mail_enabled() or not modules.enabled("email"):
        return
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "zeiterfassung@localhost"
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"[{current_app.config['COMPANY_NAME']}] {subject}"
    msg.set_content(body)
    logger = current_app.logger

    def worker():
        try:
            _send(msg)
        except Exception:  # noqa: BLE001 – Mailfehler dürfen die App nicht stören
            logger.exception("E-Mail-Versand fehlgeschlagen")

    threading.Thread(target=worker, daemon=True).start()
