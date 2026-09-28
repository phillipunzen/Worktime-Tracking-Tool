import calendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAY_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

PERIODS = {
    "day": "Tag",
    "week": "Woche",
    "month": "Monat",
    "year": "Jahr",
    "custom": "Zeitraum",
}


def _tz():
    name = "Europe/Berlin"
    if has_app_context():
        name = current_app.config.get("APP_TIMEZONE", name)
    return ZoneInfo(name)


def now_local():
    """Aktuelle lokale Zeit (ohne tzinfo, sekundengenau) – so wird in der DB gespeichert."""
    return datetime.now(_tz()).replace(tzinfo=None, microsecond=0)


def today_local():
    return now_local().date()


def parse_date(value, default=None):
    if not value:
        return default
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return default


def parse_time(value):
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%H.%M"):
        try:
            return datetime.strptime(value.strip(), fmt).time()
        except ValueError:
            continue
    return None


def parse_hours(value, default=0.0):
    """'7,5' / '7.5' / '7:30' / '-2:15' -> Stunden als float."""
    if value is None or str(value).strip() == "":
        return default
    value = str(value).strip().replace(",", ".")
    try:
        if ":" in value:
            negative = value.startswith("-")
            h, m = value.lstrip("+-").split(":", 1)
            hours = int(h or 0) + int(m or 0) / 60
            return -hours if negative else hours
        return float(value)
    except ValueError:
        return default


def daterange(start, end):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def day_bounds(start, end):
    """Datumsbereich -> [start 00:00, end+1 00:00)"""
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


def add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def period_range(period, ref, start=None, end=None):
    if period == "day":
        return ref, ref
    if period == "week":
        first = ref - timedelta(days=ref.weekday())
        return first, first + timedelta(days=6)
    if period == "month":
        return ref.replace(day=1), ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
    if period == "year":
        return date(ref.year, 1, 1), date(ref.year, 12, 31)
    start = start or ref
    end = end or start
    if end < start:
        start, end = end, start
    return start, end


def shift_ref(period, ref, direction):
    if period == "day":
        return ref + timedelta(days=direction)
    if period == "week":
        return ref + timedelta(days=7 * direction)
    if period == "month":
        return add_months(ref, direction)
    if period == "year":
        return add_months(ref, 12 * direction)
    return ref


def period_label(period, start, end):
    if period == "day":
        return f"{WEEKDAY_NAMES[start.weekday()]}, {start:%d.%m.%Y}"
    if period == "week":
        iso = start.isocalendar()
        return f"KW {iso[1]} / {iso[0]} ({start:%d.%m.} – {end:%d.%m.%Y})"
    if period == "month":
        return f"{MONTHS[start.month - 1]} {start.year}"
    if period == "year":
        return f"Jahr {start.year}"
    return f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"


def fmt_minutes(minutes, signed=False):
    if minutes is None:
        return ""
    minutes = int(round(minutes))
    sign = ""
    if minutes < 0:
        sign = "-"
    elif signed and minutes > 0:
        sign = "+"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60}:{minutes % 60:02d}"
