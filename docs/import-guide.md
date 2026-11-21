# Phase 5 — validated import and map guide

All commands below run from **inside** `C:\Users\dhanu\OneDrive\Desktop\nila`.
This guide describes officer-only pages after local database setup, migration and
sign-in. Imports are decision-support records, not medical conclusions or proof
that a building is safe.

## Import safely

1. Open **Import data** after officer sign-in.
2. Download a sample and retain its headers exactly. The samples are fictional.
3. Upload the file and read every row in the preview. Nothing has been saved at
   this point.
4. Correct invalid rows in a new file, or explicitly save only the rows marked
   valid. Enter a reason and check the confirmation box.
5. Open **Map & coverage** or the building record to inspect the saved evidence.

Each preview belongs only to the officer who created it, expires after 30
minutes, and is committed once at most. Nila validates again immediately before
save, so a file is not saved if a conflicting record arrived since its preview.
The original file is not stored in a browser cookie. A preview contains the
validated row values and errors in the protected MySQL database.

## Measurement CSV

Use the exact columns in `samples/measurements.csv`:

```text
record_key,building_code,survey_location_code,track,measurement_type,unit,value,started_at,ended_at,duration_seconds,instrument,source,record_status,notes,is_synthetic
```

- Supply exactly one location: `building_code` **or** `survey_location_code`.
- `indoor_radon` requires a building. Nila never turns a regional observation
  into an indoor radon measurement.
- The current catalogue permits only `indoor_radon / indoor_radon_concentration /
  Bq/m3` and `regional_radiation / ambient_gamma_dose_rate / uSv/h`. Values are
  not converted or compared across units.
- A submitted record needs a value, timestamp, end time or duration, instrument,
  source and notes. An incomplete record may leave unavailable evidence blank;
  blank is stored as unknown, not zero.
- Timestamps use ISO 8601 with a time zone and whole seconds, for example
  `2026-09-01T09:00:00Z`. End time must be later than start time. Dates and
  calculated end times cannot be in the future.
- New imported measurements are always `unreviewed`; import does not change a
  building's priority, workflow, action status or assessment decision.
- `record_key` and a canonical observation fingerprint prevent duplicate or
  renamed copies. Imports never overwrite existing measurements.

`is_synthetic` must explicitly be `true` or `false` and must match the related
building or survey location. Use synthetic records only for training/demo data.

## Survey areas and points

Import survey areas before importing points that refer to them.

- GeoJSON must be a WGS84 `FeatureCollection` with up to 100 Polygon or
  MultiPolygon features. Area feature properties must exactly match the sample.
- Coordinates are `[longitude, latitude]`; rings must be closed, valid and have
  finite coordinates in normal longitude/latitude bounds. Self-intersections,
  empty/zero-area geometries, custom coordinate-reference systems and
  antimeridian-crossing polygons are rejected.
- Survey-location CSVs use `code,area_code,latitude,longitude,notes,is_synthetic`.
  A named point must be inside its area; an exterior point or a point inside a
  hole is rejected.
- When a building coordinate lies within a survey polygon, including its outer
  boundary, Nila adds a `point_in_polygon` **context** link. It retains all
  overlaps and never chooses the nearest reading. Polygon holes do not match.
  Context is visibly labelled and never copied as a building measurement.
- Updating a building coordinate clears previous contexts and recalculates
  matching same-provenance areas. Survey observations themselves are retained.

## Map and list fallback

The officer map has three layers: survey context, assessment priorities and
coverage gaps. Grey `?` means unknown/not assessed, never safe. A coverage gap
means there is no **reviewed, submitted building measurement in the selected
track**; regional radiation does not fill an indoor radon gap.

The complete building, regional-area and survey-point evidence lists are
rendered by the server underneath the map. They work with JavaScript disabled or
when the interactive map cannot load.

The optional **Load OpenStreetMap background** button is off by default. It sends
only normal browser tile requests for the current view; it does not send Nila
record names or readings. Background tiles are best-effort and are not suitable
as an approved production map service without a separate provider decision.

## Try the samples

Run the temporary preview server if your persistent MySQL configuration is not
ready:

```powershell
.\.venv\Scripts\python.exe scripts\preview_officer_flow.py
```

Sign in using the temporary credentials printed in that terminal. Under **Import
data**, use `measurements-with-errors.csv` to see two row errors and one valid
incomplete record. You may save that single fictional valid row with a reason.
For an end-to-end geographic example, import `survey-areas.geojson`, then
`survey-locations.csv`, then `measurements.csv`. The latter includes both a
building indoor-radon record and a separate regional survey-point record.

Press Ctrl+C to stop the preview. It never uses `.env` or the regular MySQL
service; it retains ignored diagnostic test files in `.test-artifacts/`.
