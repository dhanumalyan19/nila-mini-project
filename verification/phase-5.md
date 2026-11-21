# Phase 5 verification — imports, geographic context and map

Date: 2026-09-15. Project: `C:\Users\dhanu\OneDrive\Desktop\nila`.

## Automated verification actually performed

`python -m pytest -q --mysql-integration`: **140 passed in 80.32 seconds**.
This run used Python 3.12, Flask and isolated loopback-only MySQL 8.0.44
instances. It did not read `.env`, use SQLite, or modify the user's MySQL Windows
service. The test schemas now use generated per-run names because disposable
MySQL data directories are intentionally retained for diagnostics.

The suite verifies the Phase 1–4 behaviour plus:

- CSV/GeoJSON headers, encoding, row limits, malformed files, units, values,
  timestamps, duration consistency, coordinates and synthetic provenance.
- Row-specific errors appear before a write; a preview can save valid rows while
  invalid rows remain unsaved. Unknown incomplete fields persist as `NULL`.
- Exact composite track/type/unit catalogue matching; no unit conversion.
- Duplicate detection within a file, after a saved observation, during competing
  previews and during concurrent commit attempts. A preview is private, expires,
  requires CSRF/confirmation/reason, ignores client-supplied replacement content,
  and can commit only once.
- Real MySQL migration from the existing Phase 4 revision to `0003_import_previews`
  preserves seeded building data.
- Polygon/MultiPolygon validation; exterior, boundary and hole semantics;
  overlapping associations; synthetic/real separation; and retained survey
  measurements when a context link is added.
- Officer-only map/import routes, map API track/provenance filtering, HTML
  escaping, absence of private notes from map JSON, list fallback markup and
  narrow map-only Content Security Policy support for an optional tile provider.

`python -m pip check` reported no broken dependencies. `node --check
app/static/js/map.js` completed successfully. Local Leaflet 1.9.4 JS/CSS hashes
match the integrity values published by Leaflet.

## Browser verification actually performed

Using headless Microsoft Edge with a temporary fictional database:

1. Signed in as the preview-only officer.
2. Opened **Import data** and uploaded `measurements-with-errors.csv`.
3. Confirmed the page displayed two precise errors (incompatible type/unit and
   invalid value), one valid record and the statement that no evidence had yet
   been saved.
4. Supplied an import reason and confirmation, then saved exactly the valid
   incomplete fictional record. The post-save page preserved the two skipped
   row errors and marked only the valid row saved.
5. Opened **Map & coverage**. Leaflet loaded from local application assets;
   priority markers, regional survey points, three layer checkboxes, synthetic
   warning, and server-rendered building/regional/survey-point lists all rendered.

Screenshots: `verification/phase-5-import-preview.png` and
`verification/phase-5-map.png` (ignored by Git). The fictional seed clusters
markers because its coordinates are intentionally compact; the map does not
claim a real location and the evidence list remains usable for individual
records.

## Known limits at this phase boundary

- No manual measurement-entry form or qualified measurement-review workflow yet;
  imports create unreviewed records only.
- No approved production tile provider, offline tiles, map clustering, spatial
  database index, antimeridian support or broad-area pagination. The map caps
  visible data at 500 buildings/points and 100 areas, with a notice.
- The application calculates geographic context only. It does not create a
  health assessment, apply a threshold, prescribe mitigation, or infer indoor
  radon from regional information.
- Browser interaction verified the full import path and map render. The explicit
  JavaScript-disabled fallback is covered by server-rendered markup/tests rather
  than a separate disabled-JS browser session.
