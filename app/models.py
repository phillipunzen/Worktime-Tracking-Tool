from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager
from .utils import now_local, today_local

ROLES = {
    "employee": "Mitarbeiter",
    "supervisor": "Vorgesetzter",
    "admin": "Administrator",
}

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# key -> (Bezeichnung, Tag wird als Sollzeit gutgeschrieben, benötigt Genehmigung)
ABSENCE_TYPES = {
    "vacation": ("Urlaub", True, True),
    "sick": ("Krank", True, False),
    "special": ("Sonderurlaub", True, True),
    "training": ("Fortbildung / Dienstreise", True, True),
    "comp": ("Freizeitausgleich", False, True),
}

ABSENCE_STATUS = {
    "pending": "Beantragt",
    "approved": "Genehmigt",
    "rejected": "Abgelehnt",
}


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    full_name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")
    supervisor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    weekly_hours = db.Column(db.Float, nullable=False, default=40.0)
    work_days = db.Column(db.String(20), nullable=False, default="0,1,2,3,4")
    vacation_days = db.Column(db.Float, nullable=False, default=30.0)
    tracking_start = db.Column(db.Date, nullable=False, default=today_local)
    initial_balance_minutes = db.Column(db.Integer, nullable=False, default=0)

    active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)

    supervisor = db.relationship("User", remote_side=[id], backref="subordinates")
    entries = db.relationship("TimeEntry", backref="user", cascade="all, delete-orphan",
                              lazy="dynamic", foreign_keys="TimeEntry.user_id")
    absences = db.relationship("Absence", backref="user", cascade="all, delete-orphan",
                               lazy="dynamic", foreign_keys="Absence.user_id")

    @property
    def is_active(self):
        return bool(self.active)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role)

    @property
    def workday_list(self):
        return sorted({int(d) for d in (self.work_days or "").split(",") if d.strip().isdigit()})

    @property
    def daily_target_minutes(self):
        days = self.workday_list
        if not days:
            return 0
        return round((self.weekly_hours or 0) * 60 / len(days))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


class TimeEntry(db.Model):
    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=True)
    break_minutes = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.String(500))
    # stamp = gestempelt, manual = nachgetragen/korrigiert
    source = db.Column(db.String(20), nullable=False, default="stamp")
    # pause = Segment wurde durch "Pause" beendet, out = durch "Gehen"
    end_reason = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_local, onupdate=now_local)

    @property
    def duration_minutes(self):
        if not self.end_time:
            return None
        return max(0, int((self.end_time - self.start_time).total_seconds() // 60))


class Absence(db.Model):
    __tablename__ = "absences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, default="vacation")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    half_day = db.Column(db.Boolean, nullable=False, default=False)
    note = db.Column(db.String(500))
    status = db.Column(db.String(20), nullable=False, default="pending")
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    decided_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local)

    decided_by = db.relationship("User", foreign_keys=[decided_by_id])

    @property
    def kind_label(self):
        return ABSENCE_TYPES.get(self.kind, (self.kind,))[0]

    @property
    def status_label(self):
        return ABSENCE_STATUS.get(self.status, self.status)

    @property
    def credits_target(self):
        return ABSENCE_TYPES.get(self.kind, ("", True))[1]


class Holiday(db.Model):
    __tablename__ = "holidays"

    id = db.Column(db.Integer, primary_key=True)
    holiday_date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(128), nullable=False)
    # 1.0 = ganzer Feiertag, 0.5 = halber Tag (z. B. Heiligabend)
    factor = db.Column(db.Float, nullable=False, default=1.0)


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)
    actor_id = db.Column(db.Integer)
    actor_name = db.Column(db.String(128))
    target_user_id = db.Column(db.Integer)
    target_name = db.Column(db.String(128))
    action_name = db.Column(db.String(64), nullable=False)
    details = db.Column(db.String(1000))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def audit(actor, action, target=None, details=""):
    db.session.add(AuditLog(
        actor_id=getattr(actor, "id", None),
        actor_name=getattr(actor, "full_name", None) or "System",
        target_user_id=getattr(target, "id", None),
        target_name=getattr(target, "full_name", None),
        action_name=action,
        details=(details or "")[:1000],
    ))

