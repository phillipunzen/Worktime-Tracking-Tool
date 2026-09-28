import os
import secrets

from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, login_manager


def _ensure_secret_key(app):
    if app.config.get("SECRET_KEY"):
        return
    os.makedirs(app.instance_path, exist_ok=True)
    path = os.path.join(app.instance_path, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        app.config["SECRET_KEY"] = fh.read().strip()


def create_app(config_object=None):
    app = Flask(__name__, instance_path=os.environ.get("INSTANCE_PATH") or None)
    app.config.from_object(config_object or Config)
    _ensure_secret_key(app)

    if app.config.get("BEHIND_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Bitte melde dich an."
    login_manager.login_message_category = "info"

    from . import models  # noqa: F401  (Modelle registrieren)
    from .filters import register_filters
    register_filters(app)

    from .absences import bp as absences_bp
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .entries import bp as entries_bp
    from .main import bp as main_bp
    from .reports import bp as reports_bp
    from .terminal import bp as terminal_bp
    from .terminal import restrict_to_terminal
    for blueprint in (auth_bp, main_bp, entries_bp, absences_bp, reports_bp, admin_bp, terminal_bp):
        app.register_blueprint(blueprint)
    if app.config.get("APP_MODE") == "terminal":
        restrict_to_terminal(app)

    from .cli import register_cli
    register_cli(app)

    @app.before_request
    def force_password_change():
        if (current_user.is_authenticated and current_user.must_change_password
                and request.endpoint not in ("auth.account", "auth.logout", "static", "health")):
            return redirect(url_for("auth.account"))

    @app.context_processor
    def inject_globals():
        from . import modules
        from .permissions import has_team
        ctx = {"company_name": app.config["COMPANY_NAME"], "show_team": False, "pending_count": 0,
               "module": modules.enabled}
        if current_user.is_authenticated:
            from .absences import pending_for
            leads_team = has_team(current_user)
            ctx["show_team"] = leads_team and modules.enabled("team")
            if leads_team and modules.enabled("absences"):
                ctx["pending_count"] = len(pending_for(current_user))
        return ctx

    @app.get("/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok"}

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="Keine Berechtigung."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Seite nicht gefunden."), 404

    return app
