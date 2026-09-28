"""PDF-Export der Zeitberichte (ReportLab)."""
import io
from xml.sax.saxutils import escape

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .utils import WEEKDAY_SHORT, fmt_minutes, now_local

PRIMARY = colors.HexColor("#1d4ed8")
LIGHT = colors.HexColor("#eef2ff")
GRID = colors.HexColor("#cbd5e1")
WEEKEND = colors.HexColor("#f8fafc")
NEG = colors.HexColor("#b91c1c")
POS = colors.HexColor("#15803d")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=18, alignment=0,
                                textColor=PRIMARY, spaceAfter=2 * mm),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, spaceBefore=2 * mm,
                             spaceAfter=2 * mm),
        "normal": ParagraphStyle("normal", parent=base["Normal"], fontSize=9, leading=11),
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=7.5, leading=9),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8, leading=9.5),
        "right": ParagraphStyle("right", parent=base["Normal"], fontSize=9, alignment=TA_RIGHT),
    }


def _signed_color(minutes):
    if minutes < 0:
        return NEG
    if minutes > 0:
        return POS
    return colors.black


def _summary_table(rep, balance, st):
    absence_text = ", ".join(f"{k}: {str(v).replace('.0', '').replace('.', ',')} Tg."
                             for k, v in rep.absence_days().items()) or "–"
    data = [
        ["Sollzeit", fmt_minutes(rep.target_minutes), "Arbeitstage mit Buchung", str(rep.worked_days)],
        ["Istzeit (Arbeit)", fmt_minutes(rep.work_minutes), "Pausen gesamt", fmt_minutes(rep.pause_minutes)],
        ["Gutschriften (Abwesenheit)", fmt_minutes(rep.credit_minutes), "Abwesenheiten",
         Paragraph(escape(absence_text), st["cell"])],
        ["Differenz (bis heute)", fmt_minutes(rep.diff_minutes, signed=True),
         "Überstundensaldo (bis gestern)", fmt_minutes(balance, signed=True)],
    ]
    table = Table(data, colWidths=[55 * mm, 30 * mm, 60 * mm, 60 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (1, 3), (1, 3), _signed_color(rep.diff_minutes)),
        ("TEXTCOLOR", (3, 3), (3, 3), _signed_color(balance)),
        ("FONTNAME", (1, 3), (1, 3), "Helvetica-Bold"),
        ("FONTNAME", (3, 3), (3, 3), "Helvetica-Bold"),
    ]))
    return table


def _day_table(rep, st, hide_empty):
    header = ["Datum", "Tag", "Beginn", "Ende", "Pause", "Arbeit", "Soll", "Diff.", "Info / Bemerkung"]
    rows = [header]
    styles = []
    for d in rep.days:
        if hide_empty and d.is_empty:
            continue
        info_parts = []
        if d.holiday:
            info_parts.append(f"<b>{escape(d.holiday)}</b>")
        if d.absence:
            info_parts.append(f"<b>{escape(d.absence.kind_label)}</b>"
                              + (" (½ Tag)" if d.absence.half_day else ""))
        if d.running:
            info_parts.append("läuft …")
        info_parts += [escape(e.note) for e in d.entries if e.note]
        if any(e.source == "manual" for e in d.entries):
            info_parts.append("<i>korrigiert</i>")
        info_parts += [f'<font color="#b45309">! {escape(w)}</font>' for w in d.warnings]
        rows.append([
            d.day.strftime("%d.%m.%Y"), WEEKDAY_SHORT[d.day.weekday()],
            d.first_start.strftime("%H:%M") if d.first_start else "",
            d.last_end.strftime("%H:%M") if d.last_end else ("…" if d.running else ""),
            fmt_minutes(d.pause_minutes) if d.entries else "",
            fmt_minutes(d.work_minutes) if d.entries else "",
            fmt_minutes(d.target_minutes) if d.target_minutes else "",
            fmt_minutes(d.diff_minutes, signed=True) if not d.future and (d.target_minutes or d.work_minutes) else "",
            Paragraph(" · ".join(info_parts), st["cell"]),
        ])
        i = len(rows) - 1
        if d.day.weekday() >= 5 or d.holiday:
            styles.append(("BACKGROUND", (0, i), (-1, i), WEEKEND))
        styles.append(("TEXTCOLOR", (7, i), (7, i), _signed_color(d.diff_minutes)))

    rows.append(["Summe", "", "", "", fmt_minutes(rep.pause_minutes), fmt_minutes(rep.work_minutes),
                 fmt_minutes(rep.target_minutes), fmt_minutes(rep.diff_minutes, signed=True), ""])
    last = len(rows) - 1
    table = Table(rows, repeatRows=1, hAlign="LEFT",
                  colWidths=[22 * mm, 10 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm, 18 * mm,
                             None])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (7, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("BACKGROUND", (0, last), (-1, last), LIGHT),
        ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
        ("TEXTCOLOR", (7, last), (7, last), _signed_color(rep.diff_minutes)),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ] + styles))
    return table


def _team_overview(reports, balances, st):
    rows = [["Mitarbeiter", "Soll", "Ist", "Gutschrift", "Differenz", "Saldo", "Hinweise"]]
    for rep in reports:
        rows.append([rep.user.full_name, fmt_minutes(rep.target_minutes), fmt_minutes(rep.work_minutes),
                     fmt_minutes(rep.credit_minutes), fmt_minutes(rep.diff_minutes, signed=True),
                     fmt_minutes(balances[rep.user.id], signed=True), str(rep.warnings_count or "")])
    table = Table(rows, repeatRows=1, hAlign="LEFT",
                  colWidths=[70 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 20 * mm])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, WEEKEND]),
    ]
    for i, rep in enumerate(reports, start=1):
        style.append(("TEXTCOLOR", (4, i), (4, i), _signed_color(rep.diff_minutes)))
        style.append(("TEXTCOLOR", (5, i), (5, i), _signed_color(balances[rep.user.id])))
    table.setStyle(TableStyle(style))
    return table


def _signatures(st):
    line = "_" * 38
    table = Table([[line, "", line], ["Datum, Unterschrift Mitarbeiter/in", "",
                                      "Datum, Unterschrift Vorgesetzte/r"]],
                  colWidths=[90 * mm, 30 * mm, 90 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8),
                               ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#475569")),
                               ("TOPPADDING", (0, 0), (-1, 0), 14 * mm)]))
    return table


def render_pdf(reports, balances, period_label, hide_empty=True, generated_by=""):
    buffer = io.BytesIO()
    company = current_app.config["COMPANY_NAME"]
    created = now_local()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Zeitbericht {period_label}", author=company)
    st = _styles()

    def on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        width, _ = landscape(A4)
        canvas.drawString(14 * mm, 8 * mm,
                          f"{company} · Zeitbericht {period_label} · erstellt am "
                          f"{created:%d.%m.%Y %H:%M} von {generated_by}")
        canvas.drawRightString(width - 14 * mm, 8 * mm, f"Seite {doc_.page}")
        canvas.restoreState()

    story = []
    if len(reports) > 1:
        story += [Paragraph(f"Team-Übersicht – {escape(period_label)}", st["title"]),
                  Paragraph(escape(company), st["normal"]), Spacer(1, 4 * mm),
                  _team_overview(reports, balances, st), PageBreak()]

    for idx, rep in enumerate(reports):
        user = rep.user
        sup = user.supervisor.full_name if user.supervisor else "–"
        story += [
            Paragraph(f"Zeitbericht – {escape(user.full_name)}", st["title"]),
            Paragraph(f"<b>Zeitraum:</b> {escape(period_label)} &nbsp;&nbsp; "
                      f"<b>Benutzer:</b> {escape(user.username)} &nbsp;&nbsp; "
                      f"<b>Vorgesetzte/r:</b> {escape(sup)} &nbsp;&nbsp; "
                      f"<b>Wochenstunden:</b> {str(user.weekly_hours).replace('.', ',')}",
                      st["normal"]),
            Spacer(1, 3 * mm),
            _summary_table(rep, balances[user.id], st),
            Spacer(1, 4 * mm),
            _day_table(rep, st, hide_empty),
            KeepTogether([_signatures(st)]),
        ]
        if idx < len(reports) - 1:
            story.append(PageBreak())

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
