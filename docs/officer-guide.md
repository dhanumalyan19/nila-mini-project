# Phase 4 — officer login and building records

All commands below run from **inside `C:\Users\dhanu\OneDrive\Desktop\nila`**.
Do not enter another `cd .\nila` when already there.

## Try the working interface immediately with fictional data

If your regular `.env` database connection is not configured yet:

```powershell
.\.venv\Scripts\python.exe scripts\preview_officer_flow.py
```

This starts a separate temporary MySQL instance using the locally installed
server, creates fictional records and prints a temporary officer username and
random password. Open **http://127.0.0.1:5012/auth/login** and use those printed
credentials. The script never reads `.env` or modifies the existing MySQL
service. Only enter fictional information into this preview.

Press Ctrl+C in that terminal to stop both the preview web server and its owned
MySQL process. Each run starts fresh: previous preview edits are not loaded on
the next run. Disposable data/logs remain under ignored `.test-artifacts/` and
can use disk space. This is a demonstration, not your regular persistent app.
The Python virtual environment must include the normal app dependencies; no
browser automation package is needed just to use the preview yourself.

## Set up your persistent local officer account

Complete `docs/database-setup.md` first. Both the MySQL connection and a
persistent `NILA_SECRET_KEY` must be configured in `.env` before login works.
Stop your previous Flask server with Ctrl+C, then run these one at a time:

```powershell
.\.venv\Scripts\python.exe -m flask --app app db-check
.\.venv\Scripts\python.exe -m flask --app app db upgrade
.\.venv\Scripts\python.exe -m flask --app app create-officer
.\.venv\Scripts\python.exe -m flask --app app run --port 5001
```

The create-officer command prompts for a username, officer name and password.
The password is hidden while entered, must contain 12–256 characters, and is
stored as a salted scrypt hash. Do not put it on the command line or share it in
chat. Existing usernames are rejected rather than overwritten. There is no
public registration or shared default login. Seeded fictional officers remain
disabled and cannot sign in.

Open **http://127.0.0.1:5001/auth/login**. A successful login opens the building
register. Signing out revokes the server session, so replaying the old cookie
cannot recover access. Sessions expire after eight hours. Disabling an officer
in the database invalidates their sessions on the next request. No password
reset/account-management UI is included yet.

For a populated demonstration in the persistent database, run `seed-demo` once
before signing in. For actual records, add real wards with:

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-ward
```

The command prompts for a unique ward code, name and locality. A real building
cannot be registered in a synthetic ward. The synthetic checkbox identifies
fictional additions; provenance cannot be switched during later edits.

## Browser demonstration

1. Sign in and search for `NILA-DEMO-B026`. Open the result to compare its
   building measurement history with separately labelled regional survey
   context. Quantities retain their individual units, times, sources and quality.
2. Return to the register and choose **Register building**. For a demo ward,
   check the fictional/synthetic checkbox. Enter an ID, name, ward and reason;
   leave optional fields blank to demonstrate unknown values.
3. Save. The building receives two separate assessment cases, both with unknown
   priority and insufficient information. They are assigned to the creating
   officer with an initial next action; no screening algorithm has run.
4. Choose **Edit building**, update a field and supply a reason. Save, reload
   the page and inspect **Recent record changes**.
5. Under an assessment track, expand **Update officer and next action**, make
   an assignment and provide a reason. Priority and review status do not change.
6. Try invalid input, such as only one coordinate or negative occupancy. The
   form returns field errors and preserves your entries without committing data.
7. Sign out, then revisit a private building URL. You should return to sign-in.

To demonstrate edit conflicts, open the same edit form in two tabs, save one,
then submit the older form. Nila returns a conflict and refuses to overwrite
the newer change. Reload the latest record before editing again.

## Implementation notes

- `app/auth/security.py`: officer lookup, session checks and database-backed
  per-address throttling (20 sign-in submissions per 10 minutes). IP addresses
  are keyed with HMAC rather than stored as plaintext. Forwarded headers are
  not trusted; reverse-proxy configuration is outside this local phase.
- `app/auth/routes.py`: login, generic credential errors, session rotation,
  POST-only CSRF-protected logout and sign-in/sign-out audit events.
- `app/buildings/forms.py`: required fields, finite numbers, coordinate pairs,
  optional unknowns and bounds. All validation also happens server-side.
- `app/buildings/routes.py`: protected search/pagination, atomic record/case/audit
  creation, editing with optimistic version checks, evidence details and audited
  assignments. No delete-building route is offered in this phase.
- `0002_officer_access.py`: adds session/throttle tables and a version column,
  initializing existing buildings to version 1 while preserving their data.

When a building's coordinates change, its previous area-context associations
are removed because they may no longer be valid. Original survey areas and
measurements are retained, and the user receives a notice. General reassociation
arrives with Phase 5. This form does not treat nearby survey readings as indoor
measurements or infer a health status.

All modifying forms have CSRF protection. Session cookies are HttpOnly and
SameSite=Lax; production configuration uses HTTPS-only cookies. Database errors
show recovery guidance without raw SQL, credentials or private records. Current
officers share access to the local municipal register; per-ward roles, MFA and
production deployment are not included in this phase.

Public locality lookup is Phase 8. Current public routes expose no private
building records; evidence/history pages require officer access. Full measurement
review transitions and audit coverage for later workflows remain future work.

Implementation references: [Flask security](https://flask.palletsprojects.com/en/stable/web-security/),
[Werkzeug password hashing](https://werkzeug.palletsprojects.com/en/stable/utils/),
[WTForms validation](https://wtforms.readthedocs.io/en/3.2.x/validators/).
