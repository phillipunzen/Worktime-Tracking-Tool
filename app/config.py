import os

from sqlalchemy.engine import URL


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "ja")


def build_database_uri():
    """Build the SQLAlchemy URI from DATABASE_URL or the DB_* variables."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    db_type = os.environ.get("DB_TYPE", "mysql").strip().lower()
    host = os.environ.get("DB_HOST", "db")
    name = os.environ.get("DB_NAME", "zeiterfassung")
    user = os.environ.get("DB_USER", "zeiterfassung")
    password = os.environ.get("DB_PASSWORD", "")

    if db_type == "sqlite":
        return "sqlite:///" + os.environ.get("DB_PATH", "/app/instance/zeiterfassung.db")

    if db_type in ("mssql", "sqlserver"):
        port = int(os.environ.get("DB_PORT", "1433"))
        uri = URL.create("mssql+pymssql", username=user, password=password,
                         host=host, port=port, database=name)
    else:
        port = int(os.environ.get("DB_PORT", "3306"))
        uri = URL.create("mysql+pymysql", username=user, password=password,
                         host=host, port=port, database=name,
                         query={"charset": "utf8mb4"})
    return uri.render_as_string(hide_password=False)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    SQLALCHEMY_DATABASE_URI = build_database_uri()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    APP_TIMEZONE = os.environ.get("APP_TIMEZONE") or os.environ.get("TZ") or "Europe/Berlin"
    COMPANY_NAME = os.environ.get("COMPANY_NAME", "Zeiterfassung")

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
    ADMIN_FULLNAME = os.environ.get("ADMIN_FULLNAME", "Administrator")

    BEHIND_PROXY = env_bool("BEHIND_PROXY", False)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_TIME_LIMIT = None
