"""Read only Nila's environment settings; never guess database credentials."""

import os
from datetime import timedelta
from pathlib import Path
import secrets

from dotenv import load_dotenv
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_REQUIRED = ("NILA_DB_HOST", "NILA_DB_NAME", "NILA_DB_USER", "NILA_DB_PASSWORD")


class ConfigurationError(ValueError):
    """A configuration error whose message is safe to display."""


def build_config(environ=None, *, load_env=True):
    # An explicit mapping makes tests independent of the developer's real .env.
    if environ is None:
        if load_env:
            load_dotenv(PROJECT_ROOT / ".env", override=False, interpolate=False)
        environ = os.environ

    mode = environ.get("NILA_ENV", "development")
    if mode not in {"development", "production"}:
        raise ConfigurationError("NILA_ENV must be development or production.")
    secret = environ.get("NILA_SECRET_KEY", "")
    if secret and len(secret) < 32:
        raise ConfigurationError("NILA_SECRET_KEY must contain at least 32 characters.")
    if mode == "production" and not secret:
        raise ConfigurationError("Production requires a persistent NILA_SECRET_KEY.")

    missing = tuple(name for name in DB_REQUIRED if not environ.get(name))
    try:
        port = int(environ.get("NILA_DB_PORT", "3306"))
        if not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        raise ConfigurationError("NILA_DB_PORT must be an integer from 1 to 65535.") from None
    if mode == "production" and missing:
        raise ConfigurationError("Production requires all NILA_DB_* connection settings.")

    # URL.create preserves passwords containing @, :, /, %, and other URL symbols.
    uri = None
    if not missing:
        uri = URL.create(
            "mysql+pymysql",
            username=environ["NILA_DB_USER"],
            password=environ["NILA_DB_PASSWORD"],
            host=environ["NILA_DB_HOST"],
            port=port,
            database=environ["NILA_DB_NAME"],
            query={"charset": "utf8mb4"},
        )
    return {
        "NILA_ENV": mode,
        "SECRET_KEY": secret or secrets.token_hex(32),
        "NILA_EPHEMERAL_SECRET": not bool(secret),
        "NILA_DATABASE_CONFIGURED": uri is not None,
        "NILA_DATABASE_MISSING": missing,
        "SQLALCHEMY_DATABASE_URI": uri,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ECHO": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "hide_parameters": True,
            "connect_args": {"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5},
        },
        "SESSION_COOKIE_NAME": "nila_session",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": mode == "production",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "WTF_CSRF_TIME_LIMIT": 3600,
        "MAX_CONTENT_LENGTH": 2 * 1024 * 1024,
    }
