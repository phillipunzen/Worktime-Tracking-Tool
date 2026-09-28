from datetime import date, datetime, timedelta

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
    app.config["ALLOW_SELF_EDIT"] = False
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
