# Phase 2 verification

Verified locally on 2026-09-14 using Windows, Python 3.12.10 and the exact package
versions in `requirements-lock.txt`. All project source and verification files
are under `nila/`.

## Automated and terminal checks

- `python -m pytest -q`: **16 passed**, no warnings in the final run.
- `python -m pip check`: no broken requirements found.
- Flask started at `http://127.0.0.1:5001`, debug and reloader disabled.
- `flask --app app routes` listed `/`, `/health/live`, `/health/ready` and static
  assets with GET routes (Flask also supplies HEAD/OPTIONS).
- With no `.env` credentials, `flask --app app db-check` returned exit code 1
  with instructions to fill in the Nila database settings; no traceback.
- Missing database configuration serves the home page, gives liveness HTTP 200
  and readiness HTTP 503, and creates no SQLAlchemy engine or fallback database.
- Configured database startup does not connect until an explicit check.
- Connection failure tests simulate access denied, missing database and
  unreachable server errors; credentials are absent from output and logs.
- MySQL URL construction preserves passwords containing URL punctuation.
- Invalid ports and incomplete production configuration are rejected safely.
- Missing form tokens return an understandable HTTP 400 error.
- CSS, security headers and the HTTP 404 recovery page were exercised.
- Migration scaffolding loads, with no revision heads in Phase 2; attempting
  an upgrade without credentials returns an actionable error. A simulated
  migration connection failure is also redacted.

The success-path database test uses a mocked connection and checks the actual
`SELECT 1` command. Neither mocked success nor mocked failure tests establish
live MySQL connectivity.

## Browser checks

Used agent-browser 0.37.1 with the locally installed Microsoft Edge executable
in headless mode. Browser user agent reported Edge 152.0.0.0.

- Opened the running application and inspected its accessibility snapshot.
- Captured and visually inspected `phase-2-desktop.png` at 1440 × 1000 and
  `phase-2-mobile.png` at 390 × 844 (both are full-page captures).
- Desktop document width and viewport width both measured 1440 px; mobile
  widths both measured 390 px. No horizontal overflow at either size.
- Main status text, separate assessment tracks and evidence limitations were
  readable in both layouts.
- Navigated to `/not-a-page`, then clicked **Return to Nila** and confirmed
  arrival at `/`.
- After clearing diagnostic history and reloading the home page, browser
  console and page-error commands returned no entries. An earlier browser
  evaluation command had a shell quoting error; corrected width checks were
  run successfully. This was a verification command error, not a page error.

Screenshots are local verification artifacts excluded from Git by default.
Browser tooling is optional and is not a runtime dependency of Nila.

## Database status and verification limits

The Windows `MySQL80` service was observed running, and MySQL Server / Workbench
installation folders are present. Nila database credentials were not configured.
No database password was requested, guessed or read from unrelated projects.

**Not verified:** authenticated MySQL connection, database/schema creation,
real migrations, persistent records or seed data. No database substitute was
used. Tests for login, imports, measurement units, planning, equipment bookings,
reviews and public privacy await their implementation phases.

The temporary development secret is intentional for the first setup page.
Before officer login is added, the user must configure a persistent local secret.
The foundation contains no assessment records, measurement claims or scientific
thresholds. The complete scientific rule and workflow checks remain future work.

The temporary Flask verification server and browser session were stopped after
testing. Use the README startup command to run the page again.
