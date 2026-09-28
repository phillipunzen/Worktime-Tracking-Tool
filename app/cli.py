import time

import click
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import User, audit


def wait_for_db(timeout=90):
    deadline = time.time() + timeout
    while True:
        try:
            db.session.execute(db.text("SELECT 1"))
            db.session.rollback()
            return
        except OperationalError as exc:
            db.session.rollback()
            if time.time() > deadline:
                raise
            click.echo(f"Warte auf Datenbank ... ({exc.orig.__class__.__name__})")
            time.sleep(3)


def init_database(app):
    wait_for_db()
    db.create_all()
    if User.query.count() == 0:
        admin = User(
            username=app.config["ADMIN_USERNAME"],
            full_name=app.config["ADMIN_FULLNAME"],
            role="admin",
            must_change_password=True,
        )
        admin.set_password(app.config["ADMIN_PASSWORD"])
        db.session.add(admin)
        audit(None, "Benutzer angelegt", admin, "Initialer Administrator")
        db.session.commit()
        click.echo(f"Administrator '{admin.username}' angelegt – bitte Passwort beim ersten Login ändern.")


def register_cli(app):
    @app.cli.command("init-db")
    def init_db_command():
        """Tabellen anlegen und initialen Administrator erzeugen."""
        init_database(app)
        click.echo("Datenbank bereit.")

    @app.cli.command("reset-password")
    @click.argument("username")
    @click.argument("password")
    def reset_password(username, password):
        """Passwort eines Benutzers zurücksetzen (Notfall)."""
        user = User.query.filter_by(username=username).first()
        if not user:
            raise click.ClickException("Benutzer nicht gefunden.")
        user.set_password(password)
        user.failed_logins = 0
        user.locked_until = None
        user.active = True
        user.must_change_password = True
        audit(None, "Passwort zurückgesetzt", user, "per Kommandozeile")
        db.session.commit()
        click.echo("Passwort gesetzt.")
