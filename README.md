# Nila — Radiation Assessment and Action Planner

Phase 6: local officer access, building records, validated evidence imports,
geographic context and fair assessment planning, using Flask and MySQL.
This project lives entirely inside `nila/`, independently of the existing drone
project. Python 3.12 is the initial development target.

## What works now

- Flask start page, shared template and local CSS; no internet needed to render.
- Environment-based configuration, MySQL driver and read-only connection check.
- Clear distinction between a running web server and a ready database connection.
- Reviewed initial MySQL migration, relational models and compatible type/unit constraints.
- Add-only synthetic seed command: 50 buildings, five wards and a 25/10 capacity fixture.
- Foundation safeguards: CSRF protection, bounded requests, session settings and
  browser security headers, officer login, expiring/revocable sessions and login throttling.
- Protected building search, creation, editing, evidence details and audited assignments.
- Officer-only CSV/GeoJSON import previews with row-specific validation errors,
  duplicate prevention, expiring private previews and explicit audited commits.
- Geographic context association using validated WGS84 polygons, plus a local
  Leaflet map with server-rendered building/survey evidence-list fallback.
- Officer campaigns, reproducible fair planning runs, unmet-demand visibility,
  deadline escalations, audited overrides and non-overlapping equipment booking.
- Officer measurement entry and quality review, non-prescriptive guidance
  references, assigned actions, separate follow-up evidence/reviewer decisions
  and private workflow audit history.

Public lookup and request forms are now available. Demo screening rules are unvalidated planning examples
with no scientific thresholds. No health diagnosis or building safety
certification is provided. Regional radiation and indoor radon remain separate
tracks; missing data remains unknown.

To try the officer interface now with a temporary fictional database, run:

```powershell
.\.venv\Scripts\python.exe scripts\preview_officer_flow.py
```

Open the printed preview URL and use the temporary credentials shown in the
terminal. This preview does not use your regular database; Ctrl+C stops it.
Each run starts fresh and leaves disposable test data under `.test-artifacts/`.

For persistent use, follow [Workbench/database setup](docs/database-setup.md),
[officer setup and demonstration](docs/officer-guide.md),
[the data model explanation](docs/data-model.md), [the planner guide](docs/planner-guide.md)
and [the workflow guide](docs/workflow-guide.md). Results are recorded in the
phase verification reports.

## Run on Windows / VS Code

Open the **nila folder** in VS Code and open its PowerShell terminal. The current
project is at `C:\Users\dhanu\OneDrive\Desktop\nila`. If your terminal is already
there, do not run `cd .\nila` again. The following environment-creation and
installation steps are needed only for a fresh setup:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5001
```

Open <http://127.0.0.1:5001>. Port 5001 keeps this application's default separate
from the existing drone app's port 5000. Press Ctrl+C in the terminal to stop.
The commands use the virtual environment's Python directly, so PowerShell
activation policy does not need to change. In VS Code's **Python: Select
Interpreter**, choose `nila\.venv\Scripts\python.exe`.

To reproduce the exact versions tested through Phase 6, install
`requirements-lock.txt` instead of `requirements-dev.txt`. The lock includes
test dependencies and the MySQL authentication cryptography dependency.

You can run the foundation page before supplying database credentials. The
terminal will report missing MySQL settings and the temporary development
session key. No alternate database is created. Without a persistent secret,
sessions reset on restart. Officer login is disabled until a persistent key is configured.

## Local configuration

Copy `.env.example` to `.env` in VS Code. If `.env` already exists, edit it rather
than replacing it. Generate a local random session key:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Paste the result into `NILA_SECRET_KEY` in your local `.env`. Do not share the
key. `.env` is ignored by Git. Shell environment settings override `.env`.
The app reads only `nila/.env`, even when invoked from a different directory.

Supply `NILA_DB_HOST`, `NILA_DB_PORT`, `NILA_DB_NAME`, `NILA_DB_USER` and
`NILA_DB_PASSWORD` for a dedicated Nila MySQL database. Store passwords containing
`#` or spaces inside single quotes in `.env`. Passwords do not need URL escaping;
the app constructs the connection URL safely from the individual values.

MySQL Workbench is a database client; MySQL Server must also be running.
In Workbench, connect using your existing local administrator connection and
create a schema named `nila` with the `utf8mb4` character set if it does not
already exist. Under **Administration → Users and Privileges**, create a
dedicated local Nila account with your own password and schema privileges only
on `nila`. Schema migrations need DDL privileges as well as normal CRUD
privileges. Never reuse unrelated schemas or give the app the root account.
Follow [the step-by-step database guide](docs/database-setup.md) to create the
schema/account, apply the migration and seed demo records.

Restart Flask after editing `.env`, then check connectivity from another terminal:

```powershell
.\.venv\Scripts\python.exe -m flask --app app db-check
```

Success means `SELECT 1` ran in MySQL. It does **not** verify application tables
or migration privileges. Failure exits with code 1 and safe recovery guidance.
Credentials must be entered locally; do not send passwords in chat.

After `db-check` succeeds, run these commands one at a time:

```powershell
.\.venv\Scripts\python.exe -m flask --app app db upgrade
.\.venv\Scripts\python.exe -m flask --app app seed-demo
.\.venv\Scripts\python.exe -m flask --app app demo-summary
.\.venv\Scripts\python.exe -m flask --app app create-officer
```

Expected summary: 25 demand, 10 nominal slots and a minimum capacity shortfall
of 15. This command does not generate a plan or change any priority.
The seed is labelled synthetic, records its anchor date/random seed, and does
nothing on repeat runs. It never overwrites existing records.

## Understand the application flow

`python -m flask --app app` finds `create_app()` in `app/__init__.py`. This factory
reads configuration, attaches the shared extensions and registers the routes.
A blueprint is simply a named group of related pages; the foundation uses
`app/main/routes.py`. Future features will get separate blueprints.

`GET /` renders `app/templates/main/index.html` inside `base.html`. It reports
whether configuration exists, without attempting to log into MySQL.
`GET /health/live` checks that Flask responds. `GET /health/ready` attempts the
same read-only database check as the terminal command and returns 503 if it
cannot connect. Readiness currently covers **connectivity only**.

`app/config.py` creates a MySQL-only SQLAlchemy URL. `app/extensions.py` holds the
database, migration and CSRF extensions. `app/database.py` handles connectivity
without exposing raw database errors. `app/cli.py` exposes terminal commands.
Missing credentials leave the database extension unattached in development.

`migrations/` tracks changes to the database structure using Alembic Python
revisions. `flask db heads` returns `0003_import_previews`; `db upgrade` applies pending revisions
to the configured MySQL schema. `app/models/` holds the table definitions and
`app/seed.py` supplies the fictional dataset.
There is deliberately no automatic `create_all()` on startup.

After sign-in, `app/auth/` verifies the server session on each request,
`app/buildings/` provides the protected register, `app/imports/` provides
private preview/commit pages, and `app/maps/` provides the protected geographic
view and list fallback. `app/planner/` provides assessment campaigns, allocation
runs, overrides and resource booking; `app/workflow/` provides measurement review,
actions, follow-up and its audit history. Building saves and audit entries share one transaction.
Optimistic record versions detect stale edits. See [the Phase 5 import/map
guide](docs/import-guide.md) for the file contracts and geographic rules.

The app binds to localhost for development. Production mode requires a
persistent secret and complete database settings and uses HTTPS-only session
cookies. This phase does not provide a production deployment. Leaflet is served
locally; an optional OpenStreetMap background requires an explicit user click,
and its narrow content-security-policy exception applies only to the map page.

## Check the application and database

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest -q --mysql-integration
.\.venv\Scripts\python.exe -m flask --app app routes
.\.venv\Scripts\python.exe -m flask --app app db heads
```

Tests exercise actual Flask request handling, missing settings, safe database
failure messages, MySQL URL handling, migration configuration and CSRF.
`--mysql-integration` additionally starts a disposable real MySQL instance,
tests migrations, persistence, seeded data and constraints, and then stops it.
It never reads `.env` or touches the existing MySQL Windows service. Without
that flag, integration tests are explicitly skipped.

For a short demonstration: start Flask, open the home page, inspect
`/health/live` and `/health/ready`, then run `db-check` in a second terminal.
A missing database produces 503 readiness while the home page remains usable.
Visit `/not-a-page` and follow **Return to Nila** to try the error state.

See `verification/phase-8.md` for current results and remaining limits;
the Phase 2–4 reports preserve earlier checks.

## Remaining phases

5. Validated imports, geographic association, map and list fallback. **Complete.**
6. Planner, fair selection, capacity shortages, equipment bookings and overrides. **Complete.**
7. Measurement review, actions, follow-up evidence and audit history. **Complete.**
8. Public locality lookup, requests and interface polish. **Complete.**
9. Full workflow verification and handover. **Complete.**

Each phase needs separate user approval. Planner documentation, sample imports,
demo scripts and full pilot limitations will grow alongside their features.

## Implementation references

- [Flask application factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)
- [Flask configuration](https://flask.palletsprojects.com/en/stable/config/)
- [Flask-SQLAlchemy configuration](https://flask-sqlalchemy.palletsprojects.com/en/stable/config/)
- [Flask-Migrate](https://flask-migrate.readthedocs.io/en/latest/index.html)
