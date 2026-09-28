"""Stempelterminal: gemeinsames Gerät, Anmeldung per Personalnummer (+ PIN), ohne Login-Sitzung.

Erreichbar unter /terminal/<token>. Mit APP_MODE=terminal liefert ein Container ausschließlich
diese Seiten aus (z. B. als eigener Port nur im Firmennetz).
"""
from datetime import timedelta

from flask import Blueprint, abort, current_app, render_template, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import modules
from .extensions import db
from .main import current_status, perform_stamp
from .models import Terminal, TerminalCredential, User
from .timecalc import compute_report
from .utils import now_local, period_range

bp = Blueprint("terminal", __name__, url_prefix="/terminal")

MAX_PIN_ATTEMPTS = 5
PIN_LOCK_MINUTES = 5
SESSION_SECONDS = 60  # so lange ist die Aktionsauswahl nach der Anmeldung gültig
TERMINAL_ENDPOINTS = ("terminal.index", "terminal.stamp", "terminal.info", "static", "health")


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="terminal-stamp")


def _get_terminal(token):
    if not modules.enabled("terminal"):
        abort(404)
    terminal = Terminal.query.filter_by(token=token).first()
    if terminal is None or not terminal.active:
        abort(404)
    return terminal


def _identify(terminal, badge, pin):
    """-> (User, None) oder (None, Fehlermeldung)"""
    generic = "Unbekannte Nummer oder falsche PIN." if terminal.require_pin else "Unbekannte Nummer."
    cred = TerminalCredential.query.filter_by(badge_number=badge).first() if badge else None
    if cred is None or not cred.user.active:
        return None, generic
    now = now_local()
    if cred.locked_until and cred.locked_until > now:
        return None, "Zu viele Fehlversuche – bitte in ein paar Minuten erneut versuchen."
    if terminal.require_pin and not cred.check_pin(pin or ""):
        cred.failed_attempts = (cred.failed_attempts or 0) + 1
        if cred.failed_attempts >= MAX_PIN_ATTEMPTS:
            cred.locked_until = now + timedelta(minutes=PIN_LOCK_MINUTES)
            cred.failed_attempts = 0
        db.session.commit()
        if terminal.require_pin and not cred.pin_hash:
            return None, "Für diese Nummer ist noch keine PIN hinterlegt."
        return None, generic
    if cred.failed_attempts or cred.locked_until:
        cred.failed_attempts = 0
        cred.locked_until = None
        db.session.commit()
    return cred.user, None


def _summary(user):
    now = now_local()
    start, end = period_range("week", now.date())
    week = compute_report(user, start, end, now)
    today = next(d for d in week.days if d.day == now.date())
    status, entry = current_status(user, now)
    return {"status": status, "entry": entry, "today": today, "week": week, "now": now}


@bp.route("/<token>", methods=["GET", "POST"])
def index(token):
    terminal = _get_terminal(token)
    error = None
    if request.method == "POST":
        user, error = _identify(terminal, request.form.get("badge", "").strip(), request.form.get("pin", ""))
        if user:
            ticket = _serializer().dumps({"u": user.id, "t": terminal.id})
            return render_template("terminal/choose.html", terminal=terminal, user=user, ticket=ticket,
                                   timeout=SESSION_SECONDS, **_summary(user))
    return render_template("terminal/index.html", terminal=terminal, error=error, now=now_local())


@bp.route("/<token>/stamp", methods=["POST"])
def stamp(token):
    terminal = _get_terminal(token)
    try:
        data = _serializer().loads(request.form.get("ticket", ""), max_age=SESSION_SECONDS)
    except SignatureExpired:
        return render_template("terminal/index.html", terminal=terminal, now=now_local(),
                               error="Zeit abgelaufen – bitte erneut anmelden.")
    except BadSignature:
        abort(400)
    user = db.session.get(User, data.get("u"))
    if data.get("t") != terminal.id or user is None or not user.active:
        abort(400)

    ok, message = perform_stamp(user, request.form.get("action"), source="terminal")
    if ok:
        terminal.last_used_at = now_local()
        db.session.commit()
    return render_template("terminal/done.html", terminal=terminal, user=user, ok=ok, message=message,
                           **_summary(user))


@bp.route("/")
def info():
    """Hinweisseite, wenn jemand das Terminal ohne gültigen Link aufruft."""
    return render_template("terminal/info.html"), 404


def restrict_to_terminal(app):
    """APP_MODE=terminal: alle anderen Seiten (Login, Verwaltung …) sind gesperrt."""
    @app.before_request
    def _only_terminal():
        if request.endpoint not in TERMINAL_ENDPOINTS:
            if request.path == "/":
                return render_template("terminal/info.html"), 404
            abort(404)


def terminal_url(terminal):
    base = current_app.config.get("TERMINAL_BASE_URL")
    path = url_for("terminal.index", token=terminal.token)
    return base.rstrip("/") + path if base else url_for("terminal.index", token=terminal.token, _external=True)
