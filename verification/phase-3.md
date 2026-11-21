# Phase 3 verification — database and synthetic data

Date: 2026-09-14. Project: `C:\Users\dhanu\OneDrive\Desktop\nila` (the user moved
it from the original drone-project directory before this phase).

## Actual test environment

- Windows; Python 3.12.10 in Nila's `.venv`.
- MySQL Community Server **8.0.44**, using the installed `mysqld.exe` binary.
- Each integration run initialized a fresh isolated database directory under
  `.test-artifacts/`, a random loopback port, and a temporary random password.
- The existing MySQL Windows service, accounts and application databases were
  not modified. Tests did not read `.env` and used no SQLite substitute.
- Each owned temporary MySQL process was shut down after its test run.

## Results

`python -m pytest -q --mysql-integration`: **46 passed in 20.57 seconds**, with
no warnings in the final full run. This includes 16 foundation tests and 30
actual-MySQL test cases.

`python -m pytest -q` without the opt-in flag: **16 passed, 30 explicitly
skipped**. `python -m pip check`: no broken requirements found.

The integration suite actually exercised:

- Applying initial revision `0001_nila_schema` to real MySQL.
- Reading the migration version, downgrading the empty test schema to base,
  and applying the migration again before inserting data.
- Comparing the actual migrated schema with SQLAlchemy metadata: no differences.
- Creating 25 application tables, plus Alembic's version table and two
  compatible measurement-kind catalogue rows.
- Successful authenticated `db-check`, and Flask readiness HTTP 200.
- Creating the fictional seed through the Flask CLI: 50 buildings, five wards,
  55 assessment cases, 19 measurements, three disabled officers and two demo
  rule versions. No generated plans or selections.
- Repeating the seed without adding duplicates or altering its anchor date.
- Preserving edited seeded records and an additional user-style record.
- Rolling back the entire attempted seed on a reserved-identifier conflict.
- Retaining records across fresh Flask application instances and disposed/new
  database connections. This tests persistence across app/connection restarts,
  not a MySQL service restart or backup restoration.
- Returning 25 demand, 10 nominal slots and 15 minimum unmet demand while
  preserving all 25 priorities, common waiting time/deadline, officers and status.
- Keeping unknown building fields and incomplete measurement values NULL.
- Checking synthetic provenance, disabled hashed-password officer records and
  authored polygon containment links.
- Finding the unmeasured demo ward, five overdue follow-ups and a detector
  assignment extending beyond the next day.
- Retaining follow-up-pending state after a synthetic action completion report.
- MySQL rejecting incompatible track/type/unit combinations, negative values,
  inconsistent durations, reversed measurement dates, incomplete submitted
  records, invalid quality states, missing measurement locations and duplicate
  record identifiers.
- MySQL rejecting invalid coordinates, occupancy and hours-of-use values.
- MySQL rejecting waiting permission without a recorded reviewer/reason, rules
  from the wrong assessment track, invalid equipment intervals, duplicate
  campaign candidates, blank override reasons and duplicate plan selections.
- Confirming current public foundation/health routes do not serialize building
  records, private notes or password hashes even when the database is seeded.

## Browser verification

Started a separate Flask server at `127.0.0.1:5012` without changing the user's
existing server on port 5001. Used agent-browser 0.37.1 with installed Microsoft
Edge in headless mode.

- Inspected the accessibility snapshot and confirmed the Phase 3 status text.
- Captured and visually inspected `phase-3-desktop.png` at 1440 × 1000 and
  `phase-3-mobile.png` at 390 × 844; both are full-page captures.
- At the mobile viewport, document width and viewport width both measured
  390 px. Text and status rows remained readable without horizontal overflow.
- Browser console and page-error commands returned no entries.

The browser check covered the setup page only. There are no officer building
pages to test yet. Screenshots are ignored local artifacts. The temporary
verification browser and port-5012 web server were stopped afterward; the
user's port-5001 server was left running and needs a restart to load new code.

## Issues found and corrected

The first actual-MySQL migration failed because two plan-selection unique
constraints inherited the same generated name. Both now have distinct explicit
names. The full migration/seed suite passes after the fix.

An initial test expected Alembic's current-version output in Click's captured
buffer, but Alembic printed it through its own stream. The test now verifies
the actual `alembic_version` row directly, in addition to running the command.

Automatic approval review rejected the attempted cleanup of disposable test
database directories. Those ignored database files and logs remain under
`.test-artifacts/`; no project or user records were deleted. They are test
artifacts and are not needed to run Nila.

## Remaining limitations

The user's regular Nila database has **not** been configured or populated;
`.env` credentials are still absent. Follow `docs/database-setup.md` to create
the schema/account, configure credentials locally, migrate and seed it.

Phase 3 implements storage and sample data, not officer login, CRUD pages,
general CSV/GeoJSON validation, allocation algorithms, overlap prevention,
complete audit coverage, review-transition enforcement or public forms. Those
remain their approved future phases. In particular, a valid booking interval
is not proof of non-overlap, and schema uniqueness is not full planner testing.

The demo has no official thresholds, exposure estimates or clinical claims.
The 3–5–2 weights and priority designations are unvalidated fictional planning
inputs. No plan or escalation is generated by `demo-summary`; the common
deadline/capacity failure must be handled by Phase 6's planner.
