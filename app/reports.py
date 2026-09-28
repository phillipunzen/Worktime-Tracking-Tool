import csv
import io

from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required

from . import modules
from .modules import require_module
from .pdf import render_pdf
from .permissions import get_visible_user_or_404, has_team, visible_users
from .timecalc import balance_minutes, compute_report
from .utils import (PERIODS, WEEKDAY_SHORT, fmt_minutes, now_local, parse_date, period_label,
                    period_range, shift_ref)

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _params():
    args = request.args
    period = args.get("period", "month")
    if period not in PERIODS:
        period = "month"
    today = now_local().date()
    ref = parse_date(args.get("ref"), today)
    start, end = period_range(period, ref, parse_date(args.get("from")), parse_date(args.get("to")))

    selection = args.get("user", str(current_user.id))
    if selection == "team":
        if not has_team(current_user):
            abort(403)
        users = [u for u in visible_users(current_user, include_inactive=False)]
    else:
        try:
            users = [get_visible_user_or_404(int(selection))]
        except ValueError:
            abort(404)
    return {"period": period, "ref": ref, "start": start, "end": end, "selection": selection,
            "users": users, "label": period_label(period, start, end),
            "hide_empty": args.get("hide_empty", "1") == "1"}


def _build(params):
    now = now_local()
    reports = [compute_report(u, params["start"], params["end"], now) for u in params["users"]]
    if modules.enabled("overtime"):
        balances = {r.user.id: balance_minutes(r.user) for r in reports}
    else:
        balances = {r.user.id: None for r in reports}
    return reports, balances


def _nav(params, direction):
    ref = shift_ref(params["period"], params["ref"], direction)
    return {"period": params["period"], "ref": ref.isoformat(), "user": params["selection"]}


@bp.route("/")
@login_required
def index():
    params = _params()
    reports, balances = _build(params)
    query = {"period": params["period"], "ref": params["ref"].isoformat(), "user": params["selection"],
             "from": params["start"].isoformat(), "to": params["end"].isoformat(),
             "hide_empty": "1" if params["hide_empty"] else "0"}
    return render_template(
        "reports/index.html",
        p=params,
        reports=reports,
        balances=balances,
        periods=PERIODS,
        users=visible_users(current_user),
        show_team_option=has_team(current_user),
        prev_args=_nav(params, -1),
        next_args=_nav(params, 1),
        query=query,
    )


@bp.route("/pdf")
@login_required
@require_module("pdf_export")
def pdf():
    params = _params()
    reports, balances = _build(params)
    data = render_pdf(reports, balances, params["label"], hide_empty=params["hide_empty"],
                      generated_by=current_user.full_name)
    name = _filename(params, "pdf")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.route("/csv")
@login_required
@require_module("csv_export")
def export_csv():
    params = _params()
    reports, _ = _build(params)
    out = io.StringIO()
    out.write("﻿")  # BOM, damit Excel UTF-8 erkennt
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["Mitarbeiter", "Datum", "Tag", "Beginn", "Ende", "Pause", "Arbeitszeit",
                     "Soll", "Gutschrift", "Differenz", "Abwesenheit/Feiertag", "Hinweise", "Bemerkungen"])
    for rep in reports:
        for d in rep.days:
            if params["hide_empty"] and d.is_empty:
                continue
            info = " / ".join(x for x in (d.holiday, d.absence.kind_label if d.absence else None) if x)
            notes = " | ".join(e.note for e in d.entries if e.note)
            writer.writerow([
                rep.user.full_name, d.day.strftime("%d.%m.%Y"), WEEKDAY_SHORT[d.day.weekday()],
                d.first_start.strftime("%H:%M") if d.first_start else "",
                d.last_end.strftime("%H:%M") if d.last_end else "",
                fmt_minutes(d.pause_minutes), fmt_minutes(d.work_minutes),
                fmt_minutes(d.target_minutes), fmt_minutes(d.credit_minutes),
                fmt_minutes(d.diff_minutes, signed=True), info, ", ".join(d.warnings), notes,
            ])
        writer.writerow([rep.user.full_name, "Summe", "", "", "", fmt_minutes(rep.pause_minutes),
                         fmt_minutes(rep.work_minutes), fmt_minutes(rep.target_minutes),
                         fmt_minutes(rep.credit_minutes), fmt_minutes(rep.diff_minutes, signed=True),
                         "", "", ""])
    name = _filename(params, "csv")
    return Response(out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _filename(params, ext):
    who = "Team" if params["selection"] == "team" else params["users"][0].username
    return f"Zeitbericht_{who}_{params['start']:%Y-%m-%d}_{params['end']:%Y-%m-%d}.{ext}"
