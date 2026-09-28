from .utils import MONTHS, WEEKDAY_SHORT, fmt_minutes


def register_filters(app):
    @app.template_filter("hm")
    def hm(minutes):
        return fmt_minutes(minutes)

    @app.template_filter("hm_signed")
    def hm_signed(minutes):
        return fmt_minutes(minutes, signed=True)

    @app.template_filter("d")
    def fmt_date(value):
        return value.strftime("%d.%m.%Y") if value else ""

    @app.template_filter("dw")
    def fmt_date_weekday(value):
        return f"{WEEKDAY_SHORT[value.weekday()]}, {value:%d.%m.%Y}" if value else ""

    @app.template_filter("t")
    def fmt_time(value):
        return value.strftime("%H:%M") if value else ""

    @app.template_filter("dt")
    def fmt_datetime(value):
        return value.strftime("%d.%m.%Y %H:%M") if value else ""

    @app.template_filter("iso")
    def fmt_iso(value):
        return value.isoformat() if value else ""

    @app.template_filter("month_name")
    def month_name(value):
        return MONTHS[value - 1]

    @app.template_filter("num")
    def fmt_num(value):
        if value is None:
            return ""
        text = f"{value:.1f}" if value % 1 else f"{value:.0f}"
        return text.replace(".", ",")
