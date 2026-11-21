"""Explicit input contracts shared by previews and commit-time validation."""
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re

from sqlalchemy import or_, select

from ..extensions import db
from ..geography import validate_geometry
from ..models import Building, Measurement, MeasurementKind, SurveyArea, SurveyLocation
from ..models.common import utcnow

MEASUREMENT_COLUMNS = ("record_key", "building_code", "survey_location_code", "track", "measurement_type", "unit", "value", "started_at", "ended_at", "duration_seconds", "instrument", "source", "record_status", "notes", "is_synthetic")
LOCATION_COLUMNS = ("code", "area_code", "latitude", "longitude", "notes", "is_synthetic")
AREA_COLUMNS = ("code", "name", "geological_context", "source", "observed_on", "is_synthetic")
MAX_ROWS = 500


def required(row, key, limit):
    value = row.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{key} is required and must be at most {limit} characters.")
    return value.strip()


def code(row, key, limit=60):
    value = required(row, key, limit)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError(f"{key} must use letters, numbers, dots, hyphens or underscores.")
    return value


def synthetic(value):
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError("is_synthetic must explicitly be true or false.")


def number(value, label, minimum, maximum, places=6):
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be a finite number.") from None
    if not result.is_finite() or not minimum <= result <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    if result.as_tuple().exponent < -places:
        raise ValueError(f"{label} allows at most {places} decimal places; no silent rounding.")
    return result


def timestamp(value, label):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.microsecond:
            raise ValueError()
        result = result.astimezone(timezone.utc).replace(tzinfo=None)
        if result.year < 1000 or result > utcnow():
            raise ValueError()
        return result
    except (ValueError, OverflowError):
        raise ValueError(f"{label} needs ISO 8601 with a time zone, whole seconds, and no future date (for example 2026-09-01T09:00:00Z).") from None


def fingerprint(values):
    # Exclude user record ID, notes, review/workflow state: renaming/rewording
    # the same observation must not create new evidence. End/duration canonicalize.
    get = values.get if isinstance(values, dict) else lambda key: getattr(values, key)
    start, end, duration = get("started_at"), get("ended_at"), get("duration_seconds")
    if start is not None and end is not None:
        duration = int((end - start).total_seconds())
        end = None
    value = get("value")
    result = {key: get(key) for key in ("building_id", "survey_location_id", "track", "measurement_type", "unit", "is_synthetic")}
    result.update(value=(str(Decimal(value).normalize()) if value else "0") if value is not None else None,
        started_at=start.isoformat() if start else None, ended_at=end.isoformat() if end else None, duration_seconds=duration,
        instrument=(get("instrument") or "").strip().casefold(), source=get("source").strip().casefold())
    return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()


def measurement(row):
    values = {"record_key": code(row, "record_key", 100), "is_synthetic": synthetic(row.get("is_synthetic")),
              "source": required(row, "source", 255), "notes": required(row, "notes", 4000)}
    for key in ("track", "measurement_type", "unit"):
        values[key] = required(row, key, {"track": 24, "measurement_type": 40, "unit": 16}[key])
    catalogue = db.session.get(MeasurementKind, tuple(values[key] for key in ("track", "measurement_type", "unit")))
    if not catalogue or any(values[key] != getattr(catalogue, key) for key in ("track", "measurement_type", "unit")):
        raise ValueError("Incompatible track/type/unit. Use the exact catalogue combination; no unit conversion is performed.")
    building_code, location_code = row.get("building_code"), row.get("survey_location_code")
    if bool(building_code) == bool(location_code):
        raise ValueError("Provide exactly one of building_code or survey_location_code.")
    target_model, target_code = (Building, building_code) if building_code else (SurveyLocation, location_code)
    target = db.session.scalar(select(target_model).where(target_model.code == target_code))
    if target is None:
        raise ValueError("Location code not found. Register the building or import the survey location first.")
    if target.is_synthetic != values["is_synthetic"]:
        raise ValueError("Synthetic provenance must match the referenced building or survey location.")
    if values["track"] == "indoor_radon" and not building_code:
        raise ValueError("Indoor radon needs a building_code, not an outdoor survey location.")
    values.update(building_id=target.id if building_code else None, survey_location_id=target.id if location_code else None)
    values["value"] = number(row["value"], "value", 0, Decimal("99999999.999999")) if row.get("value") else None
    values["started_at"] = timestamp(row.get("started_at"), "started_at")
    values["ended_at"] = timestamp(row.get("ended_at"), "ended_at")
    duration = row.get("duration_seconds")
    if duration and (not re.fullmatch(r"[0-9]{1,10}", duration) or not 1 <= int(duration) <= 2147483647):
        raise ValueError("duration_seconds must be a positive whole number up to 2147483647.")
    values["duration_seconds"] = int(duration) if duration else None
    instrument = row.get("instrument", "")
    if len(instrument) > 160:
        raise ValueError("instrument must be at most 160 characters.")
    values["instrument"] = instrument or None
    start, end = values["started_at"], values["ended_at"]
    if end and (not start or end <= start):
        raise ValueError("ended_at requires started_at and must be later than it.")
    if start and end and duration and (end - start).total_seconds() != int(duration):
        raise ValueError("duration_seconds does not match the start/end interval.")
    if start and duration:
        try:
            if start + timedelta(seconds=int(duration)) > utcnow():
                raise ValueError()
        except (OverflowError, ValueError):
            raise ValueError("The start plus duration would end in the future or outside the supported date range.") from None
    status = row.get("record_status")
    if status not in ("incomplete", "submitted"):
        raise ValueError("record_status must be incomplete or submitted.")
    if status == "submitted" and (values["value"] is None or not start or not (end or duration) or not instrument):
        raise ValueError("Submitted records need value, started_at, ended_at or duration_seconds, and instrument. Use incomplete for missing evidence.")
    values.update(record_status=status, quality_status="unreviewed")
    values["deduplication_hash"] = fingerprint(values)
    duplicate = db.session.scalar(select(Measurement.id).where(or_(Measurement.record_key == values["record_key"], Measurement.deduplication_hash == values["deduplication_hash"])))
    # Legacy seed/manual observations have no hash; still check their content.
    legacy = db.session.scalars(select(Measurement).where(Measurement.deduplication_hash.is_(None),
        Measurement.building_id == values["building_id"], Measurement.survey_location_id == values["survey_location_id"]))
    if duplicate or any(fingerprint(record) == values["deduplication_hash"] for record in legacy):
        raise ValueError("Duplicate record ID or observation already exists; imports never overwrite evidence.")
    return values


def location(row):
    values = {"code": code(row, "code"), "is_synthetic": synthetic(row.get("is_synthetic")),
              "latitude": number(row.get("latitude"), "latitude", -90, 90),
              "longitude": number(row.get("longitude"), "longitude", -180, 180), "notes": required(row, "notes", 4000)}
    values["area_id"] = None
    if row.get("area_code"):
        area = db.session.scalar(select(SurveyArea).where(SurveyArea.code == row["area_code"]))
        if not area:
            raise ValueError("area_code not found. Import the GeoJSON survey area first.")
        if area.is_synthetic != values["is_synthetic"]:
            raise ValueError("Synthetic provenance must match the survey area.")
        from shapely.geometry import Point
        if not validate_geometry(area.geometry).covers(Point(float(values["longitude"]), float(values["latitude"]))):
            raise ValueError("Survey point is outside the named area (or inside a polygon hole).")
        values["area_id"] = area.id
    if db.session.scalar(select(SurveyLocation.id).where(SurveyLocation.code == values["code"])):
        raise ValueError("Duplicate survey location code; imports never overwrite locations.")
    return values


def area(row):
    values = {key: required(row, key, limit) for key, limit in (("name", 160), ("source", 255), ("geological_context", 4000))}
    values.update(code=code(row, "code"), is_synthetic=synthetic(row.get("is_synthetic")), review_status="unreviewed")
    try:
        observed = date.fromisoformat(row.get("observed_on", ""))
        if observed.year < 1000 or observed > utcnow().date():
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("observed_on must be YYYY-MM-DD and cannot be a future date.") from None
    values["observed_on"] = observed
    validate_geometry(row.get("geometry"))
    values["geometry"] = row["geometry"]
    if db.session.scalar(select(SurveyArea.id).where(SurveyArea.code == values["code"])):
        raise ValueError("Duplicate survey area code; imports never overwrite survey areas.")
    return values


VALIDATORS = {"measurements": measurement, "locations": location, "areas": area}


def parse_upload(kind, raw):
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Save the file as UTF-8 CSV or GeoJSON and try again.") from None
    if "\x00" in content:
        raise ValueError("The file contains null bytes; upload a text file.")
    if kind == "areas":
        try:
            data = json.loads(content)
        except (ValueError, RecursionError):
            raise ValueError("Invalid JSON. Upload a GeoJSON FeatureCollection.") from None
        if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or "crs" in data:
            raise ValueError("Use a WGS84 GeoJSON FeatureCollection without a custom CRS.")
        features = data.get("features")
        if not isinstance(features, list) or not 1 <= len(features) <= 100:
            raise ValueError("Upload between 1 and 100 area features at a time.")
        rows = []
        for i, feature in enumerate(features, 1):
            if not isinstance(feature, dict) or feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict) or "crs" in feature:
                rows.append((i, {"_error": "Each item must be a Feature with properties and WGS84 geometry."}))
            else:
                props = feature["properties"]
                if set(props) != set(AREA_COLUMNS):
                    rows.append((i, {"code": str(props.get("code", ""))[:100], "_error": "Properties must match the sample exactly: " + ", ".join(AREA_COLUMNS)}))
                else:
                    rows.append((i, {**props, "geometry": feature.get("geometry")}))
        return rows
    columns = MEASUREMENT_COLUMNS if kind == "measurements" else LOCATION_COLUMNS
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(columns) or set(reader.fieldnames) != set(columns):
            raise ValueError("CSV headers must match the sample exactly: " + ", ".join(columns))
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS:
                raise ValueError("Limit CSV imports to 500 records per file.")
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                rows.append((line, {"_error": "Wrong number of columns. Quote commas inside values."}))
            else:
                rows.append((line, {key: value.strip() for key, value in row.items()}))
        if not rows:
            raise ValueError("The CSV has no data rows.")
        return rows
    except csv.Error:
        raise ValueError("Malformed CSV or oversized cell. Check quoting and use the provided sample.") from None


def validate_rows(kind, rows):
    report, objects, keys, fingerprints = [], [], set(), set()
    for number_, raw in rows:
        label = str(raw.get("record_key", raw.get("code", "Unnamed record")))[:100]
        error, values = None, None
        try:
            if raw.get("_error"):
                raise ValueError(raw["_error"])
            values = VALIDATORS[kind](raw)
            key = values.get("record_key", values.get("code"))
            digest = values.get("deduplication_hash")
            if key.casefold() in keys or digest and digest in fingerprints:
                raise ValueError("Duplicate ID or observation earlier in this file.")
            keys.add(key.casefold())
            if digest:
                fingerprints.add(digest)
        except ValueError as exception:
            error = str(exception)
        report.append({"row": number_, "label": label, "error": error, "raw": raw if not error else None})
        if not error:
            objects.append(values)
    return report, objects
