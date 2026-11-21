"""Use the Flask engine directly, without serializing credentials into an INI."""

import click
import re
from alembic import context
from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

if not current_app.config["NILA_DATABASE_CONFIGURED"]:
    raise click.ClickException("MySQL is not configured. Fill in NILA_DB_* in .env before running migrations.")

target_metadata = db.metadata


def run_migrations_offline():
    context.configure(
        url=db.engine.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    try:
        with db.engine.connect() as connection:
            version, engine = connection.execute(text("SELECT VERSION(), @@default_storage_engine")).one()
            numbers = tuple(int(value) for value in re.match(r"^(\d+)\.(\d+)\.(\d+)", version).groups())
            if "MariaDB" in version or numbers < (8, 0, 16):
                raise click.ClickException("Nila requires MySQL 8.0.16 or newer for enforced CHECK constraints.")
            if engine.lower() != "innodb":
                raise click.ClickException("Nila migrations require InnoDB as the default storage engine.")
            # The metadata check above starts a transaction. Finish it before
            # Alembic manages its own transaction for the migration/version row.
            connection.commit()
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    except SQLAlchemyError:
        # Driver errors can contain credentials, identifiers and user data.
        raise click.ClickException(
            "MySQL migration failed. Run db-check, check schema privileges and review "
            "the migration in Workbench. MySQL DDL may have committed partially."
        ) from None


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
