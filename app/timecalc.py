"""Berechnung von Ist-, Soll- und Saldozeiten."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import modules
from .models import Absence, Holiday, TimeEntry
from .utils import daterange, day_bounds, now_local


@dataclass
class DayResult:
    day: date
    entries: list = field(default_factory=list)
    first_start: object = None
    last_end: object = None
    running: bool = False
    work_minutes: int = 0
    pause_minutes: int = 0
    target_minutes: int = 0
    credit_minutes: int = 0
    holiday: str = None
    absence: object = None
    warnings: list = field(default_factory=list)
    future: bool = False

    @property
    def diff_minutes(self):
        # Zukünftige Tage sind noch nicht fällig und zählen nicht in die Differenz
        if self.future:
            return 0
        return self.work_minutes + self.credit_minutes - self.target_minutes

    @property
    def is_empty(self):
        return not self.entries and not self.absence and not self.holiday and not self.target_minutes


@dataclass
class Report:
    user: object
    start: date
    end: date
    days: list

    @property
    def work_minutes(self):
        return sum(d.work_minutes for d in self.days)

    @property
    def pause_minutes(self):
        return sum(d.pause_minutes for d in self.days)

    @property
    def target_minutes(self):
        return sum(d.target_minutes for d in self.days)

    @property
    def credit_minutes(self):
        return sum(d.credit_minutes for d in self.days)

    @property
    def diff_minutes(self):
        return sum(d.diff_minutes for d in self.days)

    @property
    def worked_days(self):
        return sum(1 for d in self.days if d.work_minutes > 0)

    @property
    def warnings_count(self):
        return sum(len(d.warnings) for d in self.days)

    def absence_days(self):
        """{Bezeichnung: Anzahl Arbeitstage}"""
        result = defaultdict(float)
        for d in self.days:
            if d.absence and d.target_minutes:
                result[d.absence.kind_label] += 0.5 if d.absence.half_day else 1
        return dict(result)


def holiday_map(start, end):
    if not modules.enabled("holidays"):
        return {}
    rows = Holiday.query.filter(Holiday.holiday_date >= start, Holiday.holiday_date <= end).all()
    return {h.holiday_date: h for h in rows}


def target_for_day(user, day, holidays):
    if day < user.tracking_start or day.weekday() not in user.workday_list:
        return 0
    target = user.daily_target_minutes
    holiday = holidays.get(day)
    if holiday:
        target = round(target * (1 - (holiday.factor or 1)))
    return target


def compute_report(user, start, end, now=None):
    now = now or now_local()
    lo, hi = day_bounds(start, end)
    entries = (TimeEntry.query
               .filter(TimeEntry.user_id == user.id,
                       TimeEntry.start_time >= lo, TimeEntry.start_time < hi)
               .order_by(TimeEntry.start_time).all())
    absences = (Absence.query
                .filter(Absence.user_id == user.id, Absence.status == "approved",
                        Absence.start_date <= end, Absence.end_date >= start)
                .all())
    holidays = holiday_map(start, end)
    arbzg = modules.enabled("arbzg")

    by_day = defaultdict(list)
    for e in entries:
        by_day[e.start_time.date()].append(e)

    days = []
    for day in daterange(start, end):
        res = DayResult(day=day, entries=by_day.get(day, []), future=day > now.date())
        gross = 0
        breaks = 0
        missing_end = False
        prev_end = None
        gaps = 0
        for e in res.entries:
            if e.end_time:
                gross += e.duration_minutes
                end_time = e.end_time
            elif day == now.date():
                gross += max(0, int((now - e.start_time).total_seconds() // 60))
                res.running = True
                end_time = None
            else:
                missing_end = True
                end_time = None
            breaks += e.break_minutes or 0
            if prev_end and e.start_time > prev_end:
                gaps += int((e.start_time - prev_end).total_seconds() // 60)
            prev_end = end_time
            if res.first_start is None:
                res.first_start = e.start_time
            if end_time and (res.last_end is None or end_time > res.last_end):
                res.last_end = end_time

        res.work_minutes = max(0, gross - breaks)
        res.pause_minutes = gaps + breaks
        res.target_minutes = target_for_day(user, day, holidays)
        if day in holidays:
            res.holiday = holidays[day].name

        for a in absences:
            if a.start_date <= day <= a.end_date:
                res.absence = a
                if a.credits_target and res.target_minutes:
                    res.credit_minutes = round(res.target_minutes * (0.5 if a.half_day else 1))
                break

        if missing_end:
            res.warnings.append("Ausstempeln fehlt")
        if arbzg:
            res.warnings += arbzg_warnings(res.work_minutes, res.pause_minutes)
        days.append(res)

    return Report(user=user, start=start, end=end, days=days)


def arbzg_warnings(work, pause):
    """Hinweise nach Arbeitszeitgesetz (§ 3, § 4 ArbZG)."""
    warnings = []
    if work > 9 * 60 and pause < 45:
        warnings.append("Pause unter 45 min bei mehr als 9 h")
    elif work > 6 * 60 and pause < 30:
        warnings.append("Pause unter 30 min bei mehr als 6 h")
    if work > 10 * 60:
        warnings.append("Mehr als 10 h Arbeitszeit")
    return warnings


def balance_minutes(user, until=None):
    """Überstundensaldo seit Beginn der Zeiterfassung bis einschließlich `until`."""
    until = until or (now_local().date() - timedelta(days=1))
    if until < user.tracking_start:
        return user.initial_balance_minutes or 0
    report = compute_report(user, user.tracking_start, until)
    return (user.initial_balance_minutes or 0) + report.diff_minutes


def vacation_summary(user, year):
    """Genommene / beantragte Urlaubstage (nur Arbeitstage) für ein Jahr."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    holidays = holiday_map(start, end)
    rows = (Absence.query
            .filter(Absence.user_id == user.id, Absence.kind == "vacation",
                    Absence.status.in_(("approved", "pending")),
                    Absence.start_date <= end, Absence.end_date >= start)
            .all())
    taken = pending = 0.0
    for a in rows:
        days = count_workdays(user, max(a.start_date, start), min(a.end_date, end), holidays)
        if a.half_day:
            days *= 0.5
        if a.status == "approved":
            taken += days
        else:
            pending += days
    total = user.vacation_days or 0
    return {"total": total, "taken": taken, "pending": pending, "left": total - taken - pending}


def count_workdays(user, start, end, holidays=None):
    if holidays is None:
        holidays = holiday_map(start, end)
    count = 0.0
    for day in daterange(start, end):
        if day.weekday() not in user.workday_list:
            continue
        holiday = holidays.get(day)
        count += 1 - (holiday.factor if holiday else 0)
    return count
