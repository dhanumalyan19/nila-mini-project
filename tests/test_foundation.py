"""Foundation behavior; database failures are simulated, never called MySQL tests."""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app
from app.config import ConfigurationError, build_config
from app.extensions import db


@pytest.fixture
def app():
    return create_app({"TESTING": True}, environ={})


def db_settings():
    return {
        "NILA_DB_HOST": "127.0.0.1",
        "NILA_DB_NAME": "fictional_test_database",
        "NILA_DB_USER": "fictional_test_user",
        "NILA_DB_PASSWORD": "synthetic-test-password:@/%#",
    }


def test_without_database_serves_home_and_honest_health(app):
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Setup needed" in response.data
    assert b"Missing information remains unknown" in response.data
    assert client.get("/health/live").json["status"] == "ok"
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json == {"database": "not_configured", "scope": "connection_only"}
    assert "sqlalchemy" not in app.extensions
    assert app.config["SQLALCHEMY_DATABASE_URI"] is None


def test_missing_database_cli_is_actionable(app):
    result = app.test_cli_runner().invoke(args=["db-check"])
    assert result.exit_code == 1
    assert "NILA_DB_*" in result.output
    assert "Traceback" not in result.output


def test_migration_scaffold_and_missing_configuration(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["db", "heads"])
    assert result.exit_code == 0
    result = runner.invoke(args=["db", "upgrade"])
    assert result.exit_code == 1
    assert "MySQL is not configured" in result.output


def test_mysql_url_preserves_password_symbols():
    config = build_config(db_settings())
    uri = config["SQLALCHEMY_DATABASE_URI"]
    assert uri.drivername == "mysql+pymysql"
    assert uri.password == db_settings()["NILA_DB_PASSWORD"]
    assert uri.query["charset"] == "utf8mb4"


@pytest.mark.parametrize("value", ["zero", "0", "65536", "3306/secret"])
def test_bad_port_fails_without_echoing_input(value):
    with pytest.raises(ConfigurationError, match="NILA_DB_PORT must be an integer") as failure:
        build_config({"NILA_DB_PORT": value})
    assert value not in str(failure.value)


def test_production_requires_persistent_key_and_database():
    with pytest.raises(ConfigurationError, match="persistent"):
        build_config({"NILA_ENV": "production"})
    with pytest.raises(ConfigurationError, match="connection settings"):
        build_config({"NILA_ENV": "production", "NILA_SECRET_KEY": "x" * 64})
    config = build_config({**db_settings(), "NILA_ENV": "production", "NILA_SECRET_KEY": "x" * 64})
    assert config["SESSION_COOKIE_SECURE"]
    assert config["SESSION_COOKIE_HTTPONLY"]
    assert not config["NILA_EPHEMERAL_SECRET"]


@pytest.mark.parametrize("code,state", [(1045, "access_denied"), (1049, "database_missing"), (2003, "unavailable")])
def test_database_failures_are_redacted(code, state, caplog):
    settings = db_settings()
    app = create_app({"TESTING": True}, environ=settings)
    driver_error = Exception(code, settings["NILA_DB_PASSWORD"])
    with app.app_context():
        with patch.object(db.engine, "connect", side_effect=OperationalError("SELECT 1", {}, driver_error)):
            response = app.test_client().get("/health/ready")
            result = app.test_cli_runner().invoke(args=["db-check"])
    assert response.status_code == 503
    assert response.json["database"] == state
    assert result.exit_code == 1
    combined = response.get_data(as_text=True) + result.output + caplog.text
    assert settings["NILA_DB_PASSWORD"] not in combined
    assert settings["NILA_DB_USER"] not in combined


def test_security_headers_static_asset_and_error_page(app):
    client = app.test_client()
    response = client.get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "object-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/static/css/base.css").status_code == 200
    response = client.get("/not-a-page")
    assert response.status_code == 404
    assert b"Return to Nila" in response.data


def test_configured_database_starts_without_connecting_and_checks_on_request():
    app = create_app({"TESTING": True}, environ=db_settings())
    with app.app_context():
        with patch.object(db.engine, "connect") as connect:
            client = app.test_client()
            assert client.get("/").status_code == 200
            assert client.get("/health/live").status_code == 200
            connect.assert_not_called()
            response = client.get("/health/ready")
            assert response.status_code == 200
            assert response.json["database"] == "connected"
            query = connect.return_value.__enter__.return_value.execute.call_args.args[0]
            assert str(query) == "SELECT 1"
            result = app.test_cli_runner().invoke(args=["db-check"])
            assert result.exit_code == 0
            assert "tables have not been verified" in result.output


def test_migration_connection_errors_are_redacted():
    settings = db_settings()
    app = create_app({"TESTING": True}, environ=settings)
    with app.app_context():
        with patch.object(db.engine, "connect", side_effect=OperationalError("", {}, Exception(settings["NILA_DB_PASSWORD"]))):
            result = app.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 1
    assert "MySQL migration failed" in result.output
    assert settings["NILA_DB_PASSWORD"] not in result.output


def test_csrf_protects_future_post_routes(app):
    @app.post("/test-form")
    def test_form():
        return "submitted"

    response = app.test_client().post("/test-form")
    assert response.status_code == 400
    assert b"form token is missing or expired" in response.data
