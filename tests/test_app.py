from datetime import date, datetime, timedelta

from app import modules
from app.extensions import db
from app.models import Absence, Holiday, TimeEntry, User
from app.timecalc import balance_minutes, compute_report, vacation_summary

from .conftest import login, make_user


def test_admin_created_and_must_change_password(client):
    resp = login(client, "admin", "admin-pass")
    assert "Bitte vergib jetzt ein eigenes Passwort" in resp.get_data(as_text=True)
    resp = client.post("/account", data={"action": "password", "old_password": "admin-pass",
                                         "new_password": "neues-passwort", "new_password2": "neues-passwort"},
                       follow_redirects=True)
    assert "Passwort geändert" in resp.get_data(as_text=True)
    assert "Stempeluhr" in client.get("/").get_data(as_text=True)


def test_wrong_password_and_lockout(client):
    make_user("max")
    for _ in range(5):
        login(client, "max", "falsch")
    resp = login(client, "max")  # korrektes Passwort, aber gesperrt
    assert "Zu viele Fehlversuche" in resp.get_data(as_text=True)


def test_stamp_flow(client):
    make_user("max")
    login(client, "max")
    assert "Eingestempelt" in client.post("/stamp", data={"action": "in"}, follow_redirects=True).get_data(as_text=True)
    assert "Pause gestartet" in client.post("/stamp", data={"action": "pause"}, follow_redirects=True).get_data(as_text=True)
    assert "Pause beendet" in client.post("/stamp", data={"action": "resume"}, follow_redirects=True).get_data(as_text=True)
    assert "Ausgestempelt" in client.post("/stamp", data={"action": "out"}, follow_redirects=True).get_data(as_text=True)
    # doppeltes Gehen ist nicht möglich
    assert "nicht möglich" in client.post("/stamp", data={"action": "out"}, follow_redirects=True).get_data(as_text=True)
    user = User.query.filter_by(username="max").one()
    entries = TimeEntry.query.filter_by(user_id=user.id).order_by(TimeEntry.id).all()
    assert [e.end_reason for e in entries] == ["pause", "out"]


def test_report_calculation(app):
    u = make_user("max", weekly_hours=40, tracking_start=date(2026, 1, 1))
    day = date(2026, 3, 2)  # Montag
    db.session.add_all([
        TimeEntry(user_id=u.id, start_time=datetime(2026, 3, 2, 8, 0), end_time=datetime(2026, 3, 2, 12, 0)),
        TimeEntry(user_id=u.id, start_time=datetime(2026, 3, 2, 12, 30), end_time=datetime(2026, 3, 2, 17, 0)),
        # Dienstag: 7 h ohne Pause -> Warnung
        TimeEntry(user_id=u.id, start_time=datetime(2026, 3, 3, 8, 0), end_time=datetime(2026, 3, 3, 15, 0)),
        Holiday(holiday_date=date(2026, 3, 4), name="Testfeiertag"),
        Absence(user_id=u.id, kind="vacation", start_date=date(2026, 3, 5), end_date=date(2026, 3, 5),
                status="approved"),
        Absence(user_id=u.id, kind="comp", start_date=date(2026, 3, 6), end_date=date(2026, 3, 6),
                status="approved"),
    ])
    db.session.commit()
    rep = compute_report(u, day, day + timedelta(days=6), now=datetime(2026, 4, 1, 12, 0))
    mon, tue, wed, thu, fri = rep.days[:5]
    assert mon.work_minutes == 510 and mon.pause_minutes == 30 and mon.diff_minutes == 30
    assert tue.work_minutes == 420 and tue.warnings
    assert wed.target_minutes == 0 and wed.holiday == "Testfeiertag"
    assert thu.credit_minutes == 480 and thu.diff_minutes == 0
    assert fri.diff_minutes == -480  # Freizeitausgleich
    assert rep.target_minutes == 4 * 480
    assert rep.diff_minutes == 30 - 60 - 480


def test_balance_and_vacation(app):
    u = make_user("max", weekly_hours=40, tracking_start=date(2026, 3, 2), initial_balance_minutes=120)
    db.session.add(TimeEntry(user_id=u.id, start_time=datetime(2026, 3, 2, 8, 0),
                             end_time=datetime(2026, 3, 2, 17, 0), break_minutes=30))
    db.session.add(Absence(user_id=u.id, kind="vacation", start_date=date(2026, 3, 9),
                           end_date=date(2026, 3, 13), status="approved"))
    db.session.commit()
    assert balance_minutes(u, date(2026, 3, 2)) == 120 + 30
    v = vacation_summary(u, 2026)
    assert v["taken"] == 5 and v["left"] == 25


def test_supervisor_visibility(client):
    boss = make_user("boss", role="supervisor")
    emp = make_user("emp", supervisor=boss)
    other = make_user("other")
    login(client, "emp")
    assert client.get(f"/reports/?user={boss.id}").status_code == 403
    assert client.get("/team").status_code == 403
    client.post("/logout")
    login(client, "boss")
    assert client.get(f"/reports/?user={emp.id}").status_code == 200
    assert client.get(f"/reports/?user={other.id}").status_code == 403
    team = client.get("/team").get_data(as_text=True)
    assert "Emp" in team and "Other" not in team


def test_vacation_request_and_approval(client):
    boss = make_user("boss", role="supervisor")
    emp = make_user("emp", supervisor=boss)
    login(client, "emp")
    client.post("/absences/new", data={"kind": "vacation", "start_date": "2026-08-03", "end_date": "2026-08-07"})
    a = Absence.query.one()
    assert a.status == "pending"
    # eigener Antrag kann nicht selbst genehmigt werden
    assert client.post(f"/absences/{a.id}/approve").status_code == 403
    client.post("/logout")
    login(client, "boss")
    assert "Offene Anträge" in client.get("/absences/").get_data(as_text=True)
    client.post(f"/absences/{a.id}/approve")
    db.session.refresh(a)
    assert a.status == "approved" and a.decided_by_id == boss.id
    assert emp.id == a.user_id


def test_manual_entry_overlap_and_audit(client):
    make_user("max")
    login(client, "max")
    ok = client.post("/entries/new", data={"date": "2026-03-02", "start": "08:00", "end": "16:30",
                                            "break_minutes": "30", "note": "nachgetragen"},
                     follow_redirects=True)
    assert "Eintrag gespeichert" in ok.get_data(as_text=True)
    clash = client.post("/entries/new", data={"date": "2026-03-02", "start": "16:00", "end": "18:00"},
                        follow_redirects=True)
    assert "Überschneidung" in clash.get_data(as_text=True)
    night = client.post("/entries/new", data={"date": "2026-03-03", "start": "22:00", "end": "02:00"},
                        follow_redirects=True)
    assert "Eintrag gespeichert" in night.get_data(as_text=True)
    e = TimeEntry.query.order_by(TimeEntry.id.desc()).first()
    assert e.duration_minutes == 240


def test_self_edit_disabled(app, client):
    modules.set_state("self_edit", False)
    db.session.commit()
    make_user("max")
    login(client, "max")
    assert client.get("/entries/new").status_code == 403


def test_reports_pdf_and_csv(client):
    boss = make_user("boss", role="supervisor")
    emp = make_user("emp", supervisor=boss, tracking_start=date(2026, 1, 1))
    db.session.add(TimeEntry(user_id=emp.id, start_time=datetime(2026, 2, 3, 8, 0),
                             end_time=datetime(2026, 2, 3, 16, 30), break_minutes=30, note="Projekt Ä"))
    db.session.commit()
    login(client, "boss")
    for period in ("day", "week", "month", "year"):
        assert client.get(f"/reports/?user={emp.id}&period={period}&ref=2026-02-03").status_code == 200
    pdf = client.get(f"/reports/pdf?user=team&period=custom&from=2026-02-01&to=2026-02-28")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    csv = client.get(f"/reports/csv?user={emp.id}&period=month&ref=2026-02-03")
    text = csv.data.decode("utf-8-sig")
    assert "03.02.2026" in text and "8:00" in text and "Projekt Ä" in text


def test_admin_user_management(client):
    admin = User.query.filter_by(username="admin").one()
    admin.must_change_password = False
    db.session.commit()
    login(client, "admin", "admin-pass")
    resp = client.post("/admin/users/new", data={
        "username": "neu", "full_name": "Neue Person", "role": "employee", "password": "geheim123",
        "weekly_hours": "38,5", "vacation_days": "28", "wd0": "1", "wd1": "1", "wd2": "1", "wd3": "1",
        "active": "1", "initial_balance": "-1:30",
    }, follow_redirects=True)
    assert "angelegt" in resp.get_data(as_text=True)
    u = User.query.filter_by(username="neu").one()
    assert u.weekly_hours == 38.5 and u.workday_list == [0, 1, 2, 3] and u.initial_balance_minutes == -90
    # Zirkelbezug verhindern
    boss = make_user("boss", role="supervisor", supervisor=u)
    u_resp = client.post(f"/admin/users/{u.id}", data={
        "username": "neu", "full_name": "Neue Person", "role": "supervisor", "supervisor_id": str(boss.id),
        "weekly_hours": "40", "vacation_days": "30", "active": "1"}, follow_redirects=True)
    assert "Zirkelbezug" in u_resp.get_data(as_text=True)
    assert client.get("/admin/audit").status_code == 200
    resp = client.post("/admin/holidays", data={"action": "import", "year": "2026", "state": "BY"},
                       follow_redirects=True)
    assert "importiert" in resp.get_data(as_text=True)
    assert Holiday.query.filter_by(holiday_date=date(2026, 1, 6)).first() is not None
    client.post(f"/admin/users/{u.id}/delete", data={"confirm": "neu"})
    assert User.query.filter_by(username="neu").first() is None


def test_employee_cannot_access_admin(client):
    make_user("max")
    login(client, "max")
    assert client.get("/admin/users").status_code == 403


def test_pages_render(client):
    make_user("max")
    login(client, "max")
    for url in ("/", "/entries/", "/absences/", "/reports/", "/account", "/manifest.webmanifest", "/health"):
        assert client.get(url).status_code == 200, url


def test_future_days_not_in_diff(app):
    u = make_user("max", weekly_hours=40, tracking_start=date(2026, 1, 1))
    rep = compute_report(u, date(2026, 3, 2), date(2026, 3, 8), now=datetime(2026, 3, 3, 12, 0))
    assert rep.target_minutes == 5 * 480
    assert rep.diff_minutes == -960  # Mo + heutiger Di zählen, Mi–Fr noch nicht


def _admin_client(client):
    admin = User.query.filter_by(username="admin").one()
    admin.must_change_password = False
    db.session.commit()
    login(client, "admin", "admin-pass")


def test_modules_page_toggles_features(client):
    _admin_client(client)
    page = client.get("/admin/modules").get_data(as_text=True)
    assert "Abwesenheiten &amp; Urlaub" in page and "Team-Übersicht" in page
    # alles aktiv lassen außer Team, PDF und Abwesenheiten
    on = {k: "1" for k in modules.MODULES if k not in ("team", "pdf_export", "absences", "terminal")}
    resp = client.post("/admin/modules", data=on, follow_redirects=True)
    assert "3 Änderung(en) gespeichert" in resp.get_data(as_text=True)
    assert not modules.enabled("team") and not modules.enabled("absences")
    # abhängige Module sind automatisch inaktiv
    assert modules.own_state("absence_approval") and not modules.enabled("absence_approval")
    assert client.get("/team").status_code == 404
    assert client.get("/absences/").status_code == 404
    assert client.get("/reports/pdf").status_code == 404
    assert client.get("/reports/csv").status_code == 200
    nav = client.get("/").get_data(as_text=True)
    assert "Abwesenheiten" not in nav and 'href="/team"' not in nav
    assert "⬇ PDF" not in client.get("/reports/").get_data(as_text=True)
    # Protokoll hat die Änderungen erfasst
    assert "Modul deaktiviert" in client.get("/admin/audit").get_data(as_text=True)


def test_module_env_default(app, monkeypatch):
    monkeypatch.setenv("MODULE_TEAM", "false")
    modules.clear_cache()
    assert not modules.enabled("team")
    modules.set_state("team", True)  # gespeicherter Wert gewinnt
    db.session.commit()
    assert modules.enabled("team")


def test_pause_and_notes_modules(client):
    make_user("max")
    modules.set_state("pause_button", False)
    modules.set_state("stamp_notes", False)
    db.session.commit()
    login(client, "max")
    client.post("/stamp", data={"action": "in", "note": "geheim"})
    page = client.get("/").get_data(as_text=True)
    assert 'value="pause"' not in page and 'name="note"' not in page
    assert "nicht möglich" in client.post("/stamp", data={"action": "pause"}, follow_redirects=True).get_data(as_text=True)
    assert TimeEntry.query.one().note is None


def test_holidays_and_arbzg_modules(app):
    u = make_user("max", weekly_hours=40, tracking_start=date(2026, 1, 1))
    db.session.add(Holiday(holiday_date=date(2026, 3, 2), name="Test"))
    db.session.add(TimeEntry(user_id=u.id, start_time=datetime(2026, 3, 3, 8, 0), end_time=datetime(2026, 3, 3, 15, 0)))
    db.session.commit()
    now = datetime(2026, 4, 1)
    rep = compute_report(u, date(2026, 3, 2), date(2026, 3, 3), now=now)
    assert rep.days[0].target_minutes == 0 and rep.days[1].warnings
    modules.set_state("holidays", False)
    modules.set_state("arbzg", False)
    db.session.commit()
    rep = compute_report(u, date(2026, 3, 2), date(2026, 3, 3), now=now)
    assert rep.days[0].target_minutes == 480 and not rep.days[1].warnings


def test_approval_workflow_off(client):
    boss = make_user("boss", role="supervisor")
    make_user("emp", supervisor=boss)
    modules.set_state("absence_approval", False)
    db.session.commit()
    login(client, "emp")
    client.post("/absences/new", data={"kind": "vacation", "start_date": "2026-08-03"})
    assert Absence.query.one().status == "approved"


def test_overtime_module_off(client):
    boss = make_user("boss", role="supervisor")
    make_user("emp", supervisor=boss)
    modules.set_state("overtime", False)
    db.session.commit()
    login(client, "boss")
    assert "Überstundenkonto" not in client.get("/").get_data(as_text=True)
    assert "Saldo" not in client.get("/team").get_data(as_text=True)
    pdf = client.get("/reports/pdf?user=team&period=month&ref=2026-02-03")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")


def _terminal_setup(require_pin=True):
    from app.models import Terminal, TerminalCredential
    modules.set_state("terminal", True)
    user = make_user("max")
    cred = TerminalCredential(user_id=user.id, badge_number="1001")
    cred.set_pin("4711")
    terminal = Terminal(name="Eingang", token="tok123", require_pin=require_pin)
    db.session.add_all([cred, terminal])
    db.session.commit()
    return user, terminal


def _ticket(html):
    import re
    return re.search(r'name="ticket" value="([^"]+)"', html).group(1)


def test_terminal_stamp_flow(client):
    user, _ = _terminal_setup()
    assert "Personalnummer" in client.get("/terminal/tok123").get_data(as_text=True)
    assert client.get("/terminal/falsch").status_code == 404
    bad = client.post("/terminal/tok123", data={"badge": "1001", "pin": "0000"}).get_data(as_text=True)
    assert "falsche PIN" in bad
    page = client.post("/terminal/tok123", data={"badge": "1001", "pin": "4711"}).get_data(as_text=True)
    assert "Hallo Max" in page and "Kommen" in page
    done = client.post("/terminal/tok123/stamp", data={"ticket": _ticket(page), "action": "in"}).get_data(as_text=True)
    assert "Eingestempelt" in done
    entry = TimeEntry.query.one()
    assert entry.user_id == user.id and entry.source == "terminal" and entry.end_time is None
    page = client.post("/terminal/tok123", data={"badge": "1001", "pin": "4711"}).get_data(as_text=True)
    assert "Gehen" in page
    client.post("/terminal/tok123/stamp", data={"ticket": _ticket(page), "action": "out"})
    assert TimeEntry.query.one().end_time is not None
    # manipuliertes Ticket
    assert client.post("/terminal/tok123/stamp", data={"ticket": "x", "action": "in"}).status_code == 400


def test_terminal_pin_lockout_and_no_pin_mode(client):
    _terminal_setup(require_pin=False)
    page = client.post("/terminal/tok123", data={"badge": "1001"}).get_data(as_text=True)
    assert "Hallo Max" in page
    from app.models import Terminal
    t = Terminal.query.one()
    t.require_pin = True
    db.session.commit()
    for _ in range(5):
        client.post("/terminal/tok123", data={"badge": "1001", "pin": "1111"})
    locked = client.post("/terminal/tok123", data={"badge": "1001", "pin": "4711"}).get_data(as_text=True)
    assert "Zu viele Fehlversuche" in locked


def test_terminal_disabled_or_locked(client):
    from app.models import Terminal
    _terminal_setup()
    Terminal.query.one().active = False
    db.session.commit()
    assert client.get("/terminal/tok123").status_code == 404
    Terminal.query.one().active = True
    modules.set_state("terminal", False)
    db.session.commit()
    assert client.get("/terminal/tok123").status_code == 404


def test_terminal_admin_and_user_pin(client):
    from app.models import Terminal, TerminalCredential
    _admin_client(client)
    assert client.get("/admin/terminals").status_code == 404  # Modul aus
    modules.set_state("terminal", True)
    db.session.commit()
    client.post("/admin/terminals", data={"action": "create", "name": "Halle 1", "require_pin": "1"})
    t = Terminal.query.one()
    assert t.token and "Halle 1" in client.get("/admin/terminals").get_data(as_text=True)
    old = t.token
    client.post("/admin/terminals", data={"action": "regenerate", "id": t.id})
    assert Terminal.query.one().token != old
    resp = client.post("/admin/users/new", data={
        "username": "neu", "full_name": "Neu", "role": "employee", "password": "geheim123",
        "weekly_hours": "40", "vacation_days": "30", "wd0": "1", "active": "1",
        "badge_number": "2002", "pin": "12"}, follow_redirects=True)
    assert "4 bis 8 Ziffern" in resp.get_data(as_text=True)
    client.post("/admin/users/new", data={
        "username": "neu", "full_name": "Neu", "role": "employee", "password": "geheim123",
        "weekly_hours": "40", "vacation_days": "30", "wd0": "1", "active": "1",
        "badge_number": "2002", "pin": "1234"})
    u = User.query.filter_by(username="neu").one()
    assert u.terminal_credential.badge_number == "2002" and u.terminal_credential.check_pin("1234")
    # Mitarbeiter ändert eigene PIN
    client.post("/logout")
    login(client, "neu", "geheim123")
    client.post("/account", data={"action": "password", "old_password": "geheim123",
                                  "new_password": "geheim1234", "new_password2": "geheim1234"})
    client.post("/account", data={"action": "pin", "pin": "9876", "pin2": "9876", "password": "geheim1234"})
    assert db.session.get(TerminalCredential, u.id).check_pin("9876")


def test_terminal_only_mode():
    from app import create_app
    from app.cli import init_database

    from .conftest import TestConfig

    class TerminalConfig(TestConfig):
        APP_MODE = "terminal"

    app = create_app(TerminalConfig)
    with app.app_context():
        init_database(app)
        c = app.test_client()
        assert c.get("/login").status_code == 404
        assert c.get("/admin/users").status_code == 404
        assert c.get("/").status_code == 404 and "nicht freigeschaltet" in c.get("/").get_data(as_text=True)
        assert c.get("/health").status_code == 200
        db.session.remove()
        db.drop_all()
