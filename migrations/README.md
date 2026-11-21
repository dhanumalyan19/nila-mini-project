# Nila database migrations

Flask-Migrate connects Alembic to the app's SQLAlchemy models. This directory is
initialized with the reviewed `0001_nila_schema` revision in Phase 3.
It creates the application tables and the compatible measurement type/unit
catalogue. It does not create a schema/account or load fictional buildings.
Phase 4 adds `0002_officer_access` for officer sessions, login throttling and
building edit versions. Existing Phase 3 building records are preserved.

`python -m flask --app app db upgrade` applies committed
revisions to the database configured in `.env`. Back up real data before schema
changes. Use a dedicated Nila database; never point it at the drone app's data.

For developers changing models: generate a migration using
`python -m flask --app app db migrate -m "Describe the schema change"`, inspect
the generated Python carefully, then apply it. Autogeneration is a proposal;
review constraints, data transformations and downgrade behavior before use.

Do not use `db.create_all()` as the migration strategy. MySQL DDL may commit
implicitly, so a failed schema migration is not guaranteed to roll back.
