from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .mailer import send_mail
from .models import ABSENCE_TYPES, Absence, User, audit
from .permissions import (can_decide_absence, can_edit_entries, get_visible_user_or_404,
                          subordinate_ids, visible_users)
from .timecalc import count_workdays, vacation_summary
from .utils import now_local, parse_date, today_local

bp = Blueprint("absences", __name__, url_prefix="/absences")


def pending_for(user):
    """Offene Anträge, über die `user` entscheiden darf."""
    query = Absence.query.filter(Absence.status == "pending")
    if not user.is_admin:
        ids = subordinate_ids(user)
        if not ids:
            return []
        query = query.filter(Absence.user_id.in_(ids))
    return query.order_by(Absence.start_date).all()


def _approvers(target):
    if target.supervisor and target.supervisor.active:
        return [target.supervisor]
    return User.query.filter(User.role == "admin", User.active == db.true()).all()


def notify_request(absence, target):
    recipients = [u.email for u in _approvers(target) if u.email]
    send_mail(recipients, f"Neuer Abwesenheitsantrag von {target.full_name}",
              f"{target.full_name} hat folgenden Antrag gestellt:\n\n"
              f"  {_describe(absence)}\n"
              f"  Bemerkung: {absence.note or '-'}\n\n"
              f"Bitte in der Zeiterfassung genehmigen oder ablehnen:\n"
              f"{url_for('absences.index', _external=True)}\n")


def notify_decision(absence, target, decider):
    if target.email and target.id != decider.id:
        send_mail([target.email], f"Dein Antrag wurde {absence.status_label.lower()}",
                  f"Hallo {target.full_name},\n\n"
                  f"dein Antrag „{_describe(absence)}“ wurde von {decider.full_name} "
                  f"{absence.status_label.lower()}.\n")


def _describe(a):
    span = f"{a.start_date:%d.%m.%Y}" if a.start_date == a.end_date \
        else f"{a.start_date:%d.%m.%Y}–{a.end_date:%d.%m.%Y}"
    return f"{a.kind_label} {span}{' (halber Tag)' if a.half_day else ''}"


@bp.route("/")
@login_required
def index():
    year = request.args.get("year", type=int) or today_local().year
    target = get_visible_user_or_404(request.args.get("user_id", type=int) or current_user.id)
    own = (Absence.query.filter(Absence.user_id == target.id,
                                Absence.start_date <= date(year, 12, 31),
                                Absence.end_date >= date(year, 1, 1))
           .order_by(Absence.start_date.desc()).all())
    team_ids = [u.id for u in visible_users(current_user) if u.id != current_user.id]
    upcoming = []
    if team_ids:
        upcoming = (Absence.query.filter(Absence.user_id.in_(team_ids), Absence.status == "approved",
                                         Absence.end_date >= today_local())
                    .order_by(Absence.start_date).limit(50).all())
    workdays = {a.id: count_workdays(a.user, a.start_date, a.end_date) * (0.5 if a.half_day else 1)
                for a in own + upcoming + pending_for(current_user)}
    return render_template(
        "absences/list.html",
        target=target,
        year=year,
        absences=own,
        pending=pending_for(current_user),
        upcoming=upcoming,
        workdays=workdays,
        vacation=vacation_summary(target, year),
        types=ABSENCE_TYPES,
        users=visible_users(current_user, include_inactive=False),
        can_manage=lambda u: can_decide_absence(current_user, u),
    )


@bp.route("/new", methods=["POST"])
@login_required
def new():
    form = request.form
    target = get_visible_user_or_404(form.get("user_id", type=int) or current_user.id)
    if target.id != current_user.id and not can_edit_entries(current_user, target):
        abort(403)
    kind = form.get("kind")
    start = parse_date(form.get("start_date"))
    end = parse_date(form.get("end_date"), start)
    half_day = bool(form.get("half_day"))

    if kind not in ABSENCE_TYPES or not start:
        flash("Bitte Art und Zeitraum angeben.", "error")
        return redirect(url_for("absences.index", user_id=target.id))
    if end < start:
        start, end = end, start
    if half_day and start != end:
        flash("Ein halber Tag kann nur für einen einzelnen Tag beantragt werden.", "error")
        return redirect(url_for("absences.index", user_id=target.id))
    clash = (Absence.query.filter(Absence.user_id == target.id, Absence.status != "rejected",
                                  Absence.start_date <= end, Absence.end_date >= start).first())
    if clash:
        flash(f"Überschneidung mit bestehender Abwesenheit: {_describe(clash)}.", "error")
        return redirect(url_for("absences.index", user_id=target.id))

    absence = Absence(user_id=target.id, kind=kind, start_date=start, end_date=end,
                      half_day=half_day, note=(form.get("note") or "").strip()[:500] or None)
    needs_approval = ABSENCE_TYPES[kind][2]
    if not needs_approval or can_decide_absence(current_user, target):
        absence.status = "approved"
        absence.decided_by_id = current_user.id
        absence.decided_at = now_local()
    db.session.add(absence)
    audit(current_user, "Abwesenheit eingetragen", target, f"{_describe(absence)} – {absence.status_label}")
    db.session.commit()
    if absence.status == "pending":
        notify_request(absence, target)
    flash("Abwesenheit eingetragen." if absence.status == "approved"
          else "Antrag gestellt – er wartet jetzt auf Genehmigung.", "success")
    return redirect(url_for("absences.index", user_id=target.id, year=start.year))


@bp.route("/<int:absence_id>/<decision>", methods=["POST"])
@login_required
def decide(absence_id, decision):
    absence = db.session.get(Absence, absence_id) or abort(404)
    target = db.session.get(User, absence.user_id)
    back = request.form.get("back") or url_for("absences.index")
    if not back.startswith("/") or back.startswith("//"):
        back = url_for("absences.index")

    if decision == "cancel":
        own_pending = absence.user_id == current_user.id and absence.status == "pending"
        if not (own_pending or can_decide_absence(current_user, target)):
            abort(403)
        audit(current_user, "Abwesenheit gelöscht", target, _describe(absence))
        db.session.delete(absence)
        db.session.commit()
        flash("Abwesenheit gelöscht.", "success")
        return redirect(back)

    if decision not in ("approve", "reject") or not can_decide_absence(current_user, target):
        abort(403)
    absence.status = "approved" if decision == "approve" else "rejected"
    absence.decided_by_id = current_user.id
    absence.decided_at = now_local()
    audit(current_user, "Abwesenheit " + absence.status_label.lower(), target, _describe(absence))
    db.session.commit()
    notify_decision(absence, target, current_user)
    flash(f"Antrag {absence.status_label.lower()}.", "success")
    return redirect(back)
