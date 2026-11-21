"""Commands run from the terminal; db-check never creates or alters tables."""

import click
from datetime import date
import json
import re
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError

from .database import check_database
from .extensions import db


def register_commands(app):
    @app.cli.command("create-officer")
    @click.option("--username", prompt=True)
    @click.option("--name", prompt="Officer name")
    def create_officer(username, name):
        """Create an active local officer; password is entered privately."""
        from .models import AuditEvent, Officer
        require_database()
        if app.config["NILA_EPHEMERAL_SECRET"]:
            raise click.ClickException("Configure a persistent NILA_SECRET_KEY before creating login accounts.")
        username, name = username.strip().lower(), name.strip()
        if not re.fullmatch(r"[a-z0-9_.-]{3,80}", username) or not 1 <= len(name) <= 120:
            raise click.ClickException("Use a 3–80 character username (letters, numbers, dot, underscore, hyphen) and a name up to 120 characters.")
        try:
            if db.session.scalar(select(Officer.id).where(Officer.username == username)):
                raise click.ClickException("That username already exists; no account was changed.")
            password = click.prompt("Password (12–256 characters)", hide_input=True, confirmation_prompt=True)
            if not 12 <= len(password) <= 256:
                raise click.ClickException("Password must contain 12–256 characters.")
            officer = Officer(username=username, display_name=name, password_hash=generate_password_hash(password), is_active=True, is_synthetic=False)
            db.session.add(officer)
            db.session.flush()
            db.session.add(AuditEvent(actor_id=officer.id, event_type="officer_created", entity_type="officer", entity_key=str(officer.id), reason="Account created by local operator through the CLI."))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise click.ClickException("Could not create the officer. Apply db upgrade and check for a duplicate username.") from None
        click.echo(f"Officer {username} created. Sign in at /auth/login.")

    @app.cli.command("create-ward")
    @click.option("--code", prompt=True)
    @click.option("--name", prompt="Ward name")
    @click.option("--locality", prompt=True)
    def create_ward(code, name, locality):
        """Register a real ward for building forms; demo wards remain synthetic."""
        from .models import AuditEvent, Ward
        require_database()
        code, name, locality = code.strip(), name.strip(), locality.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", code) or not 1 <= len(name) <= 120 or not 1 <= len(locality) <= 160:
            raise click.ClickException("Enter a valid code (up to 40 characters), ward name (120) and locality (160).")
        try:
            ward = Ward(code=code, name=name, locality=locality, is_synthetic=False)
            db.session.add(ward)
            db.session.flush()
            db.session.add(AuditEvent(actor_id=None, event_type="ward_created", entity_type="ward", entity_key=str(ward.id), reason="Ward registered by local operator through the CLI."))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise click.ClickException("Could not create the ward. Check its unique code and apply db upgrade.") from None
        click.echo("Ward registered. It is now available in building forms.")

    @app.cli.command("db-check")
    def db_check():
        """Check MySQL connectivity without printing credentials or changing data."""
        status = check_database()
        if not status.connected:
            raise click.ClickException(status.message)
        click.echo(status.message)

    def require_database():
        status = check_database()
        if not status.connected:
            raise click.ClickException(status.message)

    @app.cli.command("seed-demo")
    @click.option("--anchor-date", type=click.DateTime(formats=["%Y-%m-%d"]), help="Reference date for fictional deadlines; defaults to today.")
    def seed_demo_command(anchor_date):
        """Add the fictional v1 dataset once; never overwrite existing records."""
        from .seed import SeedConflict, seed_demo
        require_database()
        try:
            created, manifest = seed_demo(anchor_date.date() if anchor_date else date.today())
            db.session.commit()
        except SeedConflict as error:
            db.session.rollback()
            raise click.ClickException(str(error)) from None
        except SQLAlchemyError:
            db.session.rollback()
            raise click.ClickException("Demo seed was not committed. Run db upgrade and check for conflicting demo identifiers or a concurrent seed run.") from None
        click.echo("Synthetic demo data created." if created else "Demo batch already exists; nothing was changed.")
        click.echo(json.dumps(manifest, indent=2))

    @app.cli.command("demo-summary")
    def demo_summary_command():
        """Show the demo capacity arithmetic without running a planner."""
        from .seed import SeedConflict, demo_summary
        require_database()
        try:
            click.echo(json.dumps(demo_summary(), indent=2))
        except SeedConflict as error:
            raise click.ClickException(str(error)) from None
        except SQLAlchemyError:
            raise click.ClickException("Cannot read demo data. Run db upgrade, then seed-demo.") from None

    @app.cli.command("rename-demo-buildings")
    def rename_demo_buildings():
        """Give existing synthetic demo buildings meaningful fictional names."""
        from .models import AuditEvent, Building
        from .seed import demo_building_name
        require_database()
        rows = list(db.session.scalars(select(Building).where(Building.code.like("NILA-DEMO-B%"), Building.is_synthetic.is_(True)).order_by(Building.code)))
        changed = 0
        for row in rows:
            try:
                number = int(row.code.rsplit("B", 1)[1])
                ward_prefix = row.ward.name.removeprefix("Demo ").removesuffix(" Ward")
                name = demo_building_name(ward_prefix, row.building_use, number)
            except (ValueError, IndexError):
                continue
            if row.name != name:
                before = {"name": row.name}
                row.name = name
                db.session.add(AuditEvent(actor_id=None, event_type="demo_building_renamed", entity_type="building", entity_key=str(row.id), reason="Updated synthetic demo label for clearer demonstration use.", before=before, after={"name": name}, is_synthetic=True))
                changed += 1
        db.session.commit()
        click.echo(f"Renamed {changed} synthetic demo buildings. Real building records were not changed.")
