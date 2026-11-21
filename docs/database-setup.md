# MySQL setup for Windows and Workbench

Use the current project folder: `C:\Users\dhanu\OneDrive\Desktop\nila`.
If VS Code already has that folder open, **do not run `cd .\nila` again**.

## 1. Create the dedicated database

Open MySQL Workbench and connect to your existing local MySQL Server using your
administrator account. Open `sql/create_database.sql`, read its comments and
execute it using the lightning button. It creates only the `nila` schema if
absent. If that name already holds unrelated data, choose another schema name
and use it consistently in this script and `.env`.

Nila requires **MySQL 8.0.16 or newer** and InnoDB. The migration checks these
requirements before creating tables. Use MySQL's normal strict SQL mode.
Workbench is a client application; the MySQL Server Windows service must run.

## 2. Create a local Nila account

In Workbench, open **Administration → Users and Privileges → Add Account**.
Choose a login name such as `nila_app`, a local host restriction matching your
local connection (typically `localhost`), and a password of your own. Under
**Schema Privileges**, add the `nila` schema and grant schema privileges for
SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP and REFERENCES.
These cover this local app's CRUD operations and migrations; do not grant
global administrator privileges. Apply the changes.

Use this account in Nila, rather than your administrator account. A real pilot
should separate the runtime account from a more privileged migration account.

## 3. Fill in local settings

In VS Code, copy `.env.example` to a file named `.env`. If `.env` already exists,
edit it rather than overwriting it. Enter the local database host, port, schema,
account name and password into the matching `NILA_DB_*` fields.

Generate a session key in the terminal:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Paste the result into `NILA_SECRET_KEY` in `.env`. Keep all credentials local;
do not send passwords in chat. Single-quote `.env` values containing spaces or
`#`; values containing a single quote can use double quotes with appropriate
escaping. Environment variable expansion inside passwords is disabled.

## 4. Create the tables and fictional data

Stop the old Flask process with Ctrl+C in its terminal. From **inside nila**:

```powershell
.\.venv\Scripts\python.exe -m flask --app app db-check
.\.venv\Scripts\python.exe -m flask --app app db upgrade
.\.venv\Scripts\python.exe -m flask --app app seed-demo
.\.venv\Scripts\python.exe -m flask --app app demo-summary
```

Run each command after the preceding one succeeds. `db-check` should report a
successful MySQL connection. `db upgrade` applies the schema and officer-access migrations. The seed
command commits the whole fixture in one transaction. It adds 50 buildings,
five wards, 19 measurements and related records, all explicitly fictional.

`demo-summary` should report **25 demand / 10 capacity / 15 minimum unmet**.
This is a data demonstration, not a planner run. Nobody has been selected and
all 25 priorities remain unchanged. Unknown staff/equipment limits can further
reduce actual capacity; they are not assumed sufficient.

Refresh the **Schemas** panel in Workbench, expand `nila → Tables`, and open
`sql/inspect_demo.sql` to inspect the data. Follow `docs/officer-guide.md` to
create your officer account, then start Nila:

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --port 5001
```

Open <http://127.0.0.1:5001/auth/login>. Sign in to view the building register.
Restarting the web server does not recreate
the database or delete records.

## Repeatability and recovery

`seed-demo --anchor-date 2026-09-14` uses a fixed reference date for reproducible
demonstrations. Omitting it anchors deadlines to the current local date. All
stored timestamps use UTC; the fixture uses 09:00 UTC on its recorded anchor.
The fixture's random seed is 41025. Run date, seed and manifest are stored in
`seed_batches`. Changing `--anchor-date` on a later run does not change the
existing batch. There is no force/reset option.

If the batch already exists, seeding is a no-op, including records edited since
the first seed. A conflicting reserved identifier causes a full seed rollback;
it never overwrites or adopts a user record. To make a separate demonstration,
create a separate empty database and configure it deliberately.

MySQL DDL can commit implicitly. If a migration fails, inspect the schema and
error before retrying; do not use `db stamp` to conceal a partial schema. Back
up real data before migrations. `db downgrade base` removes application tables
and data, so it is not a normal troubleshooting command for your database.

## Common messages

- **MySQL is not configured:** complete `.env`, confirm it is named `.env` (not
  `.env.txt`), then restart the command/server.
- **MySQL refused access:** check the username, password, host restriction and
  schema privileges in Workbench.
- **Database does not exist:** create the schema and match `NILA_DB_NAME`.
- **Cannot connect:** check the service and the host/port; the usual local port
  is 3306, but use the value configured for your installation.
- **Demo seed was not committed:** apply the migration, then check for reserved
  demo identifiers or another concurrent seed command.
- **Cannot find ...\nila\nila:** your terminal is already inside `nila`; skip
  the `cd .\nila` step.

## Testing without touching your configured database

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q --mysql-integration
```

The first command skips database integration tests. The second initializes a
separate actual MySQL Server with a fresh loopback port, random temporary root
password and data directory under ignored `.test-artifacts/`. It never loads
your `.env` and does not alter the existing MySQL service. It stops the owned
test server afterward. Logs and disposable data remain in `.test-artifacts/`.

If MySQL is installed elsewhere, set `NILA_TEST_MYSQLD` to its `mysqld.exe` path
before running integration tests. Python's subprocesses use hidden windows.
The migration downgrade test operates only on the fresh test schema before
seeded records are added. No tests use SQLite.

Technical sources:
[MySQL CHECK constraints](https://dev.mysql.com/doc/refman/8.0/en/create-table-check-constraints.html),
[SQLAlchemy composite foreign keys](https://docs.sqlalchemy.org/en/20/core/constraints.html),
[Alembic migration review](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).
