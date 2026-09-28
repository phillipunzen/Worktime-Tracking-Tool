from functools import wraps

from flask import abort
from flask_login import current_user

from . import modules
from .extensions import db
from .models import User


def subordinate_ids(user):
    """Alle direkten und indirekten Mitarbeiter eines Vorgesetzten."""
    result = set()
    frontier = [user.id]
    while frontier:
        rows = db.session.query(User.id).filter(User.supervisor_id.in_(frontier)).all()
        frontier = [r[0] for r in rows if r[0] not in result and r[0] != user.id]
        result.update(frontier)
    return result


def visible_users(user, include_inactive=True):
    query = User.query
    if not user.is_admin:
        ids = subordinate_ids(user) | {user.id}
        query = query.filter(User.id.in_(ids))
    if not include_inactive:
        query = query.filter(User.active == db.true())
    return query.order_by(User.full_name).all()


def can_view(viewer, target):
    return viewer.is_admin or viewer.id == target.id or target.id in subordinate_ids(viewer)


def can_edit_entries(viewer, target):
    if viewer.is_admin or target.id in subordinate_ids(viewer):
        return True
    return viewer.id == target.id and modules.enabled("self_edit")


def can_decide_absence(viewer, target):
    if viewer.is_admin:
        return True
    return target.id != viewer.id and target.id in subordinate_ids(viewer)


def has_team(user):
    return user.is_admin or bool(subordinate_ids(user))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def get_visible_user_or_404(user_id):
    target = db.session.get(User, user_id) if user_id else None
    if target is None:
        abort(404)
    if not can_view(current_user, target):
        abort(403)
    return target
