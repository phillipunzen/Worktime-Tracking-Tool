from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import TimeEntry, audit
from .permissions import can_edit_entries, get_visible_user_or_404, visible_users
from .utils import day_bounds, parse_date, parse_time, period_range, today_local

bp = Blueprint("entries", __name__, url_prefix="/entries")


def _describe(entry):
    end = entry.end_time.strftime("%H:%M") if entry.end_time else "offen"
    return f"{entry.start_time:%d.%m.%Y %H:%M}–{end}, Pause {entry.break_minutes} min"


def _week_url(target, day):
    start, end = period_range("week", day)
    return url_for("entries.index", user_id=target.id,
                   **{"from": start.isoformat(), "to": end.isoformat()})


@bp.route("/")
@login_required
def index():
    target = get_visible_user_or_404(request.args.get("user_id", type=int) or current_user.id)
    today = today_local()
    start, end = period_range("week", today)
    start = parse_date(request.args.get("from"), start)
    end = parse_date(request.args.get("to"), end)
    if end < start:
        start, end = end, start
    lo, hi = day_bounds(start, end)
    entries = (TimeEntry.query.filter(TimeEntry.user_id == target.id,
                                      TimeEntry.start_time >= lo, TimeEntry.start_time < hi)
               .order_by(TimeEntry.start_time.desc()).all())
    return render_template("entries/list.html", target=target, entries=entries, start=start, end=end,
                           users=visible_users(current_user),
                           can_edit=can_edit_entries(current_user, target))


def _form_to_times(form):
    day = parse_date(form.get("date"))
    start_t = parse_time(form.get("start"))
    end_t = parse_time(form.get("end"))
    if not day or not start_t:
        return None, None, "Bitte Datum und Beginn angeben."
    start = datetime.combine(day, start_t)
    end = None
    if end_t:
        end = datetime.combine(day, end_t)
        if end <= start:  # über Mitternacht
            end += timedelta(days=1)
        if end - start > timedelta(hours=24):
            return None, None, "Ein Eintrag darf maximal 24 Stunden lang sein."
    return start, end, None


def _overlaps(user_id, start, end, exclude_id=None):
    far_future = start + timedelta(days=2)
    query = TimeEntry.query.filter(TimeEntry.user_id == user_id,
                                   TimeEntry.start_time < (end or far_future))
    if exclude_id:
        query = query.filter(TimeEntry.id != exclude_id)
    for other in query.filter(TimeEntry.start_time >= start - timedelta(days=2)).all():
        other_end = other.end_time or far_future
        if other.start_time < (end or far_future) and start < other_end:
            return other
    return None


def _save(entry, target, is_new):
    form = request.form
    start, end, error = _form_to_times(form)
    breaks = form.get("break_minutes", type=int) or 0
    if not error and breaks < 0:
        error = "Die Pause darf nicht negativ sein."
    if not error and end and breaks >= (end - start).total_seconds() / 60:
        error = "Die Pause ist länger als die Arbeitszeit."
    if not error:
        if end is None:
            open_other = TimeEntry.query.filter(TimeEntry.user_id == target.id,
                                                TimeEntry.end_time.is_(None),
                                                TimeEntry.id != (entry.id or 0)).first()
            if open_other:
                error = "Es gibt bereits einen offenen Eintrag. Bitte zuerst dort ein Ende eintragen."
    if not error:
        clash = _overlaps(target.id, start, end, exclude_id=entry.id)
        if clash:
            error = f"Überschneidung mit bestehendem Eintrag ({_describe(clash)})."
    if error:
        flash(error, "error")
        return False

    before = None if is_new else _describe(entry)
    entry.user_id = target.id
    entry.start_time = start
    entry.end_time = end
    entry.break_minutes = breaks
    entry.note = (form.get("note") or "").strip()[:500] or None
    entry.source = "manual"
    if end and not entry.end_reason:
        entry.end_reason = "out"
    if is_new:
        db.session.add(entry)
        audit(current_user, "Zeiteintrag angelegt", target, _describe(entry))
    else:
        audit(current_user, "Zeiteintrag geändert", target, f"{before} → {_describe(entry)}")
    db.session.commit()
    flash("Eintrag gespeichert.", "success")
    return True


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    target = get_visible_user_or_404(request.values.get("user_id", type=int) or current_user.id)
    if not can_edit_entries(current_user, target):
        abort(403)
    entry = TimeEntry(break_minutes=0)
    if request.method == "POST" and _save(entry, target, is_new=True):
        return redirect(_week_url(target, entry.start_time.date()))
    return render_template("entries/form.html", entry=entry, target=target,
                           default_date=parse_date(request.args.get("date"), today_local()))


@bp.route("/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def edit(entry_id):
    entry = db.session.get(TimeEntry, entry_id) or abort(404)
    target = entry.user
    if not can_edit_entries(current_user, target):
        abort(403)
    if request.method == "POST" and _save(entry, target, is_new=False):
        return redirect(_week_url(target, entry.start_time.date()))
    return render_template("entries/form.html", entry=entry, target=target,
                           default_date=entry.start_time.date())


@bp.route("/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete(entry_id):
    entry = db.session.get(TimeEntry, entry_id) or abort(404)
    target = entry.user
    if not can_edit_entries(current_user, target):
        abort(403)
    audit(current_user, "Zeiteintrag gelöscht", target, _describe(entry))
    day = entry.start_time.date()
    db.session.delete(entry)
    db.session.commit()
    flash("Eintrag gelöscht.", "success")
    return redirect(_week_url(target, day))
