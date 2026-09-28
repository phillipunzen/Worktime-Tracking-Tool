from datetime import timedelta
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db
from .models import User, audit
from .utils import now_local

bp = Blueprint("auth", __name__)

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 10
MIN_PASSWORD_LENGTH = 8


def _safe_next(target):
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        now = now_local()

        if user and user.locked_until and user.locked_until > now:
            flash("Zu viele Fehlversuche. Bitte in ein paar Minuten erneut versuchen.", "error")
        elif user and user.active and user.check_password(password):
            user.failed_logins = 0
            user.locked_until = None
            db.session.commit()
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(_safe_next(request.args.get("next")) or url_for("main.dashboard"))
        else:
            if user:
                user.failed_logins = (user.failed_logins or 0) + 1
                if user.failed_logins >= MAX_FAILED_LOGINS:
                    user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                    user.failed_logins = 0
                db.session.commit()
            flash("Benutzername oder Passwort ist falsch.", "error")

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Du wurdest abgemeldet.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            current_user.full_name = request.form.get("full_name", "").strip() or current_user.full_name
            current_user.email = request.form.get("email", "").strip() or None
            db.session.commit()
            flash("Profil gespeichert.", "success")
        elif action == "password":
            old = request.form.get("old_password", "")
            new = request.form.get("new_password", "")
            repeat = request.form.get("new_password2", "")
            if not current_user.check_password(old):
                flash("Das aktuelle Passwort ist falsch.", "error")
            elif len(new) < MIN_PASSWORD_LENGTH:
                flash(f"Das neue Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben.", "error")
            elif new != repeat:
                flash("Die Passwörter stimmen nicht überein.", "error")
            elif new == old:
                flash("Das neue Passwort muss sich vom alten unterscheiden.", "error")
            else:
                current_user.set_password(new)
                current_user.must_change_password = False
                audit(current_user, "Passwort geändert", current_user)
                db.session.commit()
                flash("Passwort geändert.", "success")
                return redirect(url_for("main.dashboard"))
        return redirect(url_for("auth.account"))

    return render_template("account.html", min_len=MIN_PASSWORD_LENGTH)
