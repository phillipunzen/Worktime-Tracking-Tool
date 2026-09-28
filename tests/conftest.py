import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import create_app  # noqa: E402
from app.cli import init_database  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402


class TestConfig:
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    APP_TIMEZONE = "Europe/Berlin"
    COMPANY_NAME = "Testfirma"
    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "admin-pass"
    ADMIN_FULLNAME = "Admin"


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        init_database(app)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(username, role="employee", supervisor=None, **kw):
    u = User(username=username, full_name=kw.pop("full_name", username.title()), role=role,
             supervisor_id=supervisor.id if supervisor else None, **kw)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    return u


def login(client, username, password="password123"):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=True)
