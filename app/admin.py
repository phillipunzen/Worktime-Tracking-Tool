import re
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .auth import MIN_PASSWORD_LENGTH
from .extensions import db
from .models import ROLES, WEEKDAYS, Absence, AuditLog, Holiday, User, audit
from .permissions import admin_required, subordinate_ids
from .utils import parse_date, parse_hours, today_local

bp = Blueprint("admin", __name__, url_prefix="/admin")

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}$")

STATES = {
    "": "nur bundesweite Feiertage",
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg", "HB": "Bremen",
    "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz", "SL": "Saarland", "SN": "Sachsen",
    "ST": "Sachsen-Anhalt", "SH": "Schleswig-Holstein", "TH": "Thüringen",
}


@bp.before_request
@login_required
@admin_required
def _guard():
    pass


# ---------------------------------------------------------------- Benutzer

@bp.route("/users")
def users():
    show_inactive = request.args.get("inactive") == "1"
    query = User.query
    if not show_inactive:
        query = query.filter(User.active == db.true())
    return render_template("admin/users.html", users=query.order_by(User.full_name).all(),
                           show_inactive=show_inactive)


def _supervisor_options(user):
    query = User.query.filter(User.role.in_(("supervisor", "admin")), User.active == db.true())
    if user.id:
        query = query.filter(~User.id.in_({user.id} | subordinate_ids(user)))
    return query.order_by(User.full_name).all()


def _apply_form(user, is_new):
    form = request.form
    username = form.get("username", "").strip()
    full_name = form.get("full_name", "").strip()
    role = form.get("role", "employee")
    supervisor_id = form.get("supervisor_id", type=int)
    password = form.get("password", "")
    work_days = ",".join(str(i) for i in range(7) if form.get(f"wd{i}"))

    errors = []
    if not USERNAME_RE.match(username):
        errors.append("Benutzername: 2–64 Zeichen, nur Buchstaben, Ziffern, Punkt, Minus, Unterstrich.")
    elif User.query.filter(User.username == username, User.id != (user.id or 0)).first():
        errors.append("Dieser Benutzername ist bereits vergeben.")
    if not full_name:
        errors.append("Bitte einen Namen angeben.")
    if role not in ROLES:
        errors.append("Ungültige Rolle.")
    if is_new and len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben.")
    if not is_new and password and len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Das neue Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben.")
    if supervisor_id:
        if supervisor_id == user.id or (user.id and supervisor_id in subordinate_ids(user)):
            errors.append("Ungültiger Vorgesetzter (Zirkelbezug).")
        elif not db.session.get(User, supervisor_id):
            errors.append("Vorgesetzter nicht gefunden.")
    if user.id == current_user.id and (role != "admin" or not form.get("active")):
        errors.append("Du kannst dir selbst nicht die Admin-Rechte entziehen oder dich deaktivieren.")
    weekly = parse_hours(form.get("weekly_hours"), None)
    if weekly is None or not 0 <= weekly <= 80:
        errors.append("Wochenstunden müssen zwischen 0 und 80 liegen.")
    vacation = parse_hours(form.get("vacation_days"), None)
    if vacation is None or not 0 <= vacation <= 366:
        errors.append("Ungültige Anzahl Urlaubstage.")
    if errors:
        for e in errors:
            flash(e, "error")
        return False

    user.username = username
    user.full_name = full_name
    user.email = form.get("email", "").strip() or None
    user.role = role
    user.supervisor_id = supervisor_id or None
    user.weekly_hours = weekly
    user.work_days = work_days
    user.vacation_days = vacation
    user.tracking_start = parse_date(form.get("tracking_start"), user.tracking_start or today_local())
    user.initial_balance_minutes = round(parse_hours(form.get("initial_balance"), 0) * 60)
    user.active = bool(form.get("active"))
    user.must_change_password = bool(form.get("must_change_password"))
    if password:
        user.set_password(password)
        user.failed_logins = 0
        user.locked_until = None
    return True


@bp.route("/users/new", methods=["GET", "POST"])
def user_new():
    user = User(role="employee", weekly_hours=40, work_days="0,1,2,3,4", vacation_days=30,
                tracking_start=today_local(), initial_balance_minutes=0, active=True,
                must_change_password=True)
    if request.method == "POST":
        if _apply_form(user, is_new=True):
            db.session.add(user)
            db.session.flush()
            audit(current_user, "Benutzer angelegt", user, f"Rolle: {user.role_label}")
            db.session.commit()
            flash(f"Benutzer „{user.full_name}“ angelegt.", "success")
            return redirect(url_for("admin.users"))
        db.session.rollback()
    return render_template("admin/user_form.html", user=user, is_new=True, roles=ROLES,
                           weekdays=WEEKDAYS, supervisors=_supervisor_options(user),
                           min_len=MIN_PASSWORD_LENGTH)


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
def user_edit(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if request.method == "POST":
        if _apply_form(user, is_new=False):
            audit(current_user, "Benutzer geändert", user,
                  "inkl. Passwort" if request.form.get("password") else "")
            db.session.commit()
            flash("Benutzer gespeichert.", "success")
            return redirect(url_for("admin.users"))
        db.session.rollback()
        user = db.session.get(User, user_id)
    return render_template("admin/user_form.html", user=user, is_new=False, roles=ROLES,
                           weekdays=WEEKDAYS, supervisors=_supervisor_options(user),
                           min_len=MIN_PASSWORD_LENGTH)


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
def user_delete(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("Du kannst dich nicht selbst löschen.", "error")
        return redirect(url_for("admin.users"))
    if request.form.get("confirm") != user.username:
        flash("Zum Löschen bitte den Benutzernamen zur Bestätigung eingeben.", "error")
        return redirect(url_for("admin.user_edit", user_id=user.id))
    User.query.filter_by(supervisor_id=user.id).update({"supervisor_id": None})
    Absence.query.filter_by(decided_by_id=user.id).update({"decided_by_id": None})
    audit(current_user, "Benutzer gelöscht", user, "inkl. aller Zeiten und Abwesenheiten")
    db.session.delete(user)
    db.session.commit()
    flash("Benutzer und alle zugehörigen Daten gelöscht.", "success")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------- Feiertage

@bp.route("/holidays", methods=["GET", "POST"])
def holidays():
    year = request.args.get("year", type=int) or today_local().year
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            day = parse_date(request.form.get("date"))
            name = request.form.get("name", "").strip()
            factor = 0.5 if request.form.get("half") else 1.0
            if not day or not name:
                flash("Bitte Datum und Bezeichnung angeben.", "error")
            elif Holiday.query.filter_by(holiday_date=day).first():
                flash("Für dieses Datum existiert bereits ein Feiertag.", "error")
            else:
                db.session.add(Holiday(holiday_date=day, name=name[:128], factor=factor))
                audit(current_user, "Feiertag angelegt", None, f"{day:%d.%m.%Y} {name}")
                db.session.commit()
                flash("Feiertag angelegt.", "success")
            year = day.year if day else year
        elif action == "import":
            year = request.form.get("year", type=int) or year
            state = request.form.get("state", "")
            added = import_holidays(year, state if state in STATES else "",
                                    include_half=bool(request.form.get("half_days")))
            audit(current_user, "Feiertage importiert", None, f"{year} {state or 'bundesweit'}: {added}")
            db.session.commit()
            flash(f"{added} Feiertag(e) für {year} importiert.", "success")
        elif action == "delete":
            holiday = db.session.get(Holiday, request.form.get("id", type=int))
            if holiday:
                year = holiday.holiday_date.year
                audit(current_user, "Feiertag gelöscht", None, f"{holiday.holiday_date:%d.%m.%Y} {holiday.name}")
                db.session.delete(holiday)
                db.session.commit()
                flash("Feiertag gelöscht.", "success")
        return redirect(url_for("admin.holidays", year=year))

    rows = (Holiday.query.filter(Holiday.holiday_date >= date(year, 1, 1),
                                 Holiday.holiday_date <= date(year, 12, 31))
            .order_by(Holiday.holiday_date).all())
    return render_template("admin/holidays.html", holidays=rows, year=year, states=STATES)


def import_holidays(year, state="", include_half=False):
    import holidays as holidays_lib

    calendar = holidays_lib.country_holidays("DE", subdiv=state or None, years=year, language="de")
    items = dict(calendar)
    if include_half:
        items.setdefault(date(year, 12, 24), "Heiligabend (halber Tag)")
        items.setdefault(date(year, 12, 31), "Silvester (halber Tag)")
    added = 0
    for day, name in sorted(items.items()):
        if Holiday.query.filter_by(holiday_date=day).first():
            continue
        factor = 0.5 if "halber Tag" in name else 1.0
        db.session.add(Holiday(holiday_date=day, name=str(name)[:128], factor=factor))
        added += 1
    return added


# ---------------------------------------------------------------- Protokoll

@bp.route("/audit")
def audit_log():
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = 100
    query = AuditLog.query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    rows = query.offset((page - 1) * per_page).limit(per_page + 1).all()
    return render_template("admin/audit.html", rows=rows[:per_page], page=page,
                           has_next=len(rows) > per_page)
