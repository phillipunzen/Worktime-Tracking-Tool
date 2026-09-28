from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import modules
from .extensions import db
from .modules import require_module
from .models import Absence, TimeEntry
from .permissions import has_team, visible_users
from .timecalc import balance_minutes, compute_report, vacation_summary
from .utils import now_local, period_range

bp = Blueprint("main", __name__)


def current_status(user, now=None):
    """-> (status, entry) mit status in working / pause / off"""
    now = now or now_local()
    open_entry = (TimeEntry.query.filter_by(user_id=user.id, end_time=None)
                  .order_by(TimeEntry.start_time.desc()).first())
    if open_entry:
        return "working", open_entry
    last = (TimeEntry.query.filter(TimeEntry.user_id == user.id)
            .order_by(TimeEntry.end_time.desc()).first())
    if last and last.end_reason == "pause" and last.end_time and last.end_time.date() == now.date():
        return "pause", last
    return "off", None


def todays_absence(user, day):
    return (Absence.query.filter(Absence.user_id == user.id, Absence.status == "approved",
                                 Absence.start_date <= day, Absence.end_date >= day).first())


@bp.route("/")
@login_required
def dashboard():
    now = now_local()
    today = now.date()
    status, entry = current_status(current_user, now)
    week_start, week_end = period_range("week", today)
    week = compute_report(current_user, week_start, week_end, now)
    today_result = next(d for d in week.days if d.day == today)
    # Soll/Ist der Woche nur bis heute vergleichen
    week_target_so_far = sum(d.target_minutes for d in week.days if d.day <= today)
    week_diff_so_far = week.diff_minutes

    stale_entry = entry if status == "working" and entry.start_time.date() < today else None
    today_closed = today_result.work_minutes
    if status == "working" and not stale_entry:
        # laufendes Segment rechnet die Live-Uhr im Browser selbst hoch
        today_closed -= int((now - entry.start_time).total_seconds() // 60)

    return render_template(
        "dashboard.html",
        status=status,
        entry=entry,
        stale_entry=stale_entry,
        today_closed=max(0, today_closed),
        today=today_result,
        week=week,
        week_target_so_far=week_target_so_far,
        week_diff_so_far=week_diff_so_far,
        balance=balance_minutes(current_user) if modules.enabled("overtime") else None,
        vacation=vacation_summary(current_user, today.year) if modules.enabled("absences") else None,
        absence_today=todays_absence(current_user, today),
        now=now,
    )


@bp.route("/stamp", methods=["POST"])
@login_required
def stamp():
    action = request.form.get("action")
    now = now_local()
    status, entry = current_status(current_user, now)
    note = None
    if modules.enabled("stamp_notes"):
        note = (request.form.get("note") or "").strip()[:500] or None
    if action == "pause" and not modules.enabled("pause_button"):
        action = None

    if action in ("in", "resume") and status != "working":
        db.session.add(TimeEntry(user_id=current_user.id, start_time=now, source="stamp", note=note))
        flash("Pause beendet – weiter geht's!" if status == "pause" else "Eingestempelt. Guten Start!",
              "success")
    elif action in ("pause", "out") and status == "working":
        if now < entry.start_time:
            now = entry.start_time
        entry.end_time = now
        entry.end_reason = action
        if note:
            entry.note = f"{entry.note} / {note}" if entry.note else note
        flash("Pause gestartet." if action == "pause" else "Ausgestempelt. Schönen Feierabend!", "success")
    else:
        flash("Diese Aktion ist im aktuellen Status nicht möglich.", "error")
        return redirect(url_for("main.dashboard"))

    db.session.commit()
    return redirect(url_for("main.dashboard"))


@bp.route("/team")
@login_required
@require_module("team")
def team():
    if not has_team(current_user):
        abort(403)
    now = now_local()
    today = now.date()
    week_start, week_end = period_range("week", today)
    rows = []
    show_balance = modules.enabled("overtime")
    for user in visible_users(current_user, include_inactive=False):
        if user.id == current_user.id and not current_user.is_admin:
            continue
        status, entry = current_status(user, now)
        week = compute_report(user, week_start, week_end, now)
        day = next(d for d in week.days if d.day == today)
        rows.append({
            "user": user,
            "status": status,
            "entry": entry,
            "today": day,
            "week_work": week.work_minutes,
            "week_target": week.target_minutes,
            "absence": todays_absence(user, today),
            "balance": balance_minutes(user) if show_balance else None,
            "warnings": sum(len(d.warnings) for d in week.days),
        })
    counts = {
        "working": sum(1 for r in rows if r["status"] == "working"),
        "pause": sum(1 for r in rows if r["status"] == "pause"),
        "absent": sum(1 for r in rows if r["absence"]),
    }
    return render_template("team.html", rows=rows, counts=counts, now=now)


@bp.route("/manifest.webmanifest")
def manifest():
    from flask import current_app, jsonify
    return jsonify({
        "name": current_app.config["COMPANY_NAME"],
        "short_name": "Zeiterfassung",
        "start_url": url_for("main.dashboard"),
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#2563eb",
        "icons": [
            {"src": url_for("static", filename="icon.svg"), "sizes": "any", "type": "image/svg+xml"},
            {"src": url_for("static", filename="icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="icon-512.png"), "sizes": "512x512", "type": "image/png"},
        ],
    })

