"""Read-only connectivity checks with messages that never expose credentials."""

from dataclasses import dataclass

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db


@dataclass(frozen=True)
class DatabaseStatus:
    state: str
    message: str

    @property
    def connected(self):
        return self.state == "connected"


def check_database():
    if not current_app.config["NILA_DATABASE_CONFIGURED"]:
        return DatabaseStatus(
            "not_configured",
            "MySQL is not configured. Fill in the NILA_DB_* settings in .env, then restart Nila.",
        )
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as error:
        # Do not log str(error): drivers can include usernames, hosts and SQL.
        args = getattr(getattr(error, "orig", None), "args", ())
        code = args[0] if args else None
        if code in {1044, 1045, 1698}:
            return DatabaseStatus("access_denied", "MySQL refused access. Check the Nila user's credentials and database permissions in Workbench.")
        if code == 1049:
            return DatabaseStatus("database_missing", "The configured MySQL database does not exist. Create the Nila database in Workbench.")
        return DatabaseStatus("unavailable", "Cannot connect to MySQL. Check the service, host, port and connection settings, then retry.")
    return DatabaseStatus("connected", "Connected to MySQL. SELECT 1 succeeded; application tables have not been verified.")

