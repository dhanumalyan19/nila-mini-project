"""Phase 5 parser/geometry tests and actual MySQL HTTP import workflows."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import csv
import io
import json
from pathlib import Path
import uuid

import pytest
from shapely.geometry import Point
from sqlalchemy import func, select, text

from app import create_app
from app.extensions import db
from app.geography import associate_building, validate_geometry
from app.imports.validation import LOCATION_COLUMNS, MEASUREMENT_COLUMNS, parse_upload, validate_rows
from app.models import AssessmentCase, AuditEvent, Building, BuildingSurveyContext, ImportBatch, Measurement, Officer, SurveyArea, SurveyLocation
from app.models.common import utcnow
from test_access_buildings import access_settings, access_app, client, sign_in, token, new_building, PASSWORD

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def observation(**changes):
    row = dict.fromkeys(MEASUREMENT_COLUMNS, "")
    row.update(record_key="TEST-OBS-" + uuid.uuid4().hex[:16], building_code="NILA-DEMO-B001", track="indoor_radon",
        measurement_type="indoor_radon_concentration", unit="Bq/m3", value="12.5", started_at="2026-09-01T09:00:00Z",
        duration_seconds="300", instrument="Fictional test instrument", source="Test source " + uuid.uuid4().hex[:12],
        record_status="submitted", notes="Synthetic test only.", is_synthetic="true")
    return {**row, **changes}


def as_csv(rows, columns=MEASUREMENT_COLUMNS):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def preview_upload(client, raw, kind="measurements"):
    result = client.post("/imports/", data={"csrf_token": token(client.get("/imports/")), "kind": kind, "upload": (io.BytesIO(raw), "input.txt")})
    assert result.status_code == 302, result.get_data(as_text=True)[:2000]
    return result.location


def commit(client, url):
    return client.post(url + "/commit", data={"csrf_token": token(client.get(url)), "confirm": "y", "reason": "Synthetic import verification"})


def polygon():
    return {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]]]}


def test_polygon_boundaries_holes_and_multipolygons():
    area = validate_geometry(polygon())
    assert area.covers(Point(0, 5)) and area.covers(Point(2, 3))
    assert not area.covers(Point(3, 3)) and not area.covers(Point(12, 2))
    assert validate_geometry({"type": "MultiPolygon", "coordinates": [polygon()["coordinates"]]}).is_valid


@pytest.mark.parametrize("geometry", [None, {}, {"type": "Point", "coordinates": [0, 0]},
    {"type": "Polygon", "coordinates": []}, {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 1], [3, 3]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [181, 0], [1, 1], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[179, 0], [-179, 0], [-179, 1], [179, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 91], [1, 1], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [True, 1], [2, 1], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [float("nan"), 1], [2, 1], [0, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [10**500, 1], [2, 1], [0, 0]]]},
    {**polygon(), "crs": "EPSG:3857"}])
def test_invalid_geometry_is_rejected(geometry):
    with pytest.raises(ValueError):
        validate_geometry(geometry)


@pytest.mark.parametrize("raw", [b"", b"bad,headers\n1,2", b"\xff", b"\0", b'"unclosed'])
def test_malformed_csv_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_upload("measurements", raw)


def test_csv_limits_and_column_count():
    with pytest.raises(ValueError, match="500"):
        parse_upload("measurements", as_csv([observation()] * 501))
    raw = (",".join(MEASUREMENT_COLUMNS) + "\na,b\n").encode()
    assert parse_upload("measurements", raw)[0][1]["_error"]


@pytest.mark.parametrize("route", ["/imports/", "/imports/1", "/imports/samples/areas", "/map/", "/map/data"])
def test_private_import_and_map_routes(access_app, route):
    result = access_app.test_client().get(route)
    assert result.status_code == 302 and result.location == "/auth/login"


@pytest.mark.parametrize("changes,expected", [
    ({"unit": "uSv/h"}, "Incompatible"), ({"unit": "bq/m3"}, "Incompatible"),
    ({"value": "NaN"}, "value"), ({"value": "-1"}, "value"), ({"value": "Infinity"}, "value"),
    ({"value": "1.1234567"}, "rounding"), ({"value": "100000000"}, "value"),
    ({"started_at": "2026-09-01T09:00:00"}, "time zone"), ({"started_at": "2999-01-01T00:00:00Z"}, "future"),
    ({"ended_at": "2026-09-01T08:00:00Z"}, "later"), ({"ended_at": "2026-09-01T09:10:00Z"}, "does not match"),
    ({"duration_seconds": "0"}, "positive"), ({"duration_seconds": "1.5"}, "whole"),
    ({"duration_seconds": "2147483647"}, "future"), ({"building_code": "UNKNOWN"}, "not found"),
    ({"survey_location_code": "NILA-DEMO-POINT-1"}, "exactly one"),
    ({"building_code": "", "survey_location_code": "NILA-DEMO-POINT-1"}, "Indoor radon"),
    ({"is_synthetic": "false"}, "provenance"), ({"is_synthetic": ""}, "explicitly"),
    ({"source": ""}, "source"), ({"notes": ""}, "notes"), ({"instrument": ""}, "Submitted"),
    ({"value": ""}, "Submitted"), ({"record_status": "accepted"}, "record_status")])
def test_measurement_row_validation(access_app, changes, expected):
    report, objects = validate_rows("measurements", [(2, observation(**changes))])
    assert not objects and expected in report[0]["error"]


def test_preview_has_errors_before_partial_commit_unknowns_and_audit(access_app, client):
    row = observation(value="", started_at="", duration_seconds="", instrument="", record_status="incomplete")
    count = db.session.scalar(select(func.count()).select_from(Measurement))
    cases = list(db.session.execute(select(AssessmentCase.id, AssessmentCase.priority_band, AssessmentCase.evidence_status)))
    url = preview_upload(client, as_csv([observation(unit="wrong"), row]))
    response = client.get(url)
    assert b"1 valid records" in response.data and b"Incompatible" in response.data and b"No evidence has been saved" in response.data
    assert db.session.scalar(select(func.count()).select_from(Measurement)) == count
    assert commit(client, url).status_code == 302
    record = db.session.scalar(select(Measurement).where(Measurement.record_key == row["record_key"]))
    assert record.value is None and record.started_at is None and record.instrument is None
    assert record.quality_status == "unreviewed" and record.record_status == "incomplete"
    assert list(db.session.execute(select(AssessmentCase.id, AssessmentCase.priority_band, AssessmentCase.evidence_status))) == cases
    audit = db.session.scalar(select(AuditEvent).where(AuditEvent.entity_type == "import_batch", AuditEvent.entity_key == url.split("/")[-1]))
    assert audit.after["count"] == 1 and audit.after["skipped"] == 1 and audit.actor_id == record.submitted_by_id
    assert commit(client, url).status_code == 409
    assert db.session.scalar(select(func.count()).select_from(Measurement)) == count + 1


def test_duplicate_canonical_content_within_file_and_after_commit(access_app, client):
    row = observation()
    duplicate = {**row, "record_key": "RENAMED-" + uuid.uuid4().hex[:12], "value": "12.500000", "duration_seconds": "", "ended_at": "2026-09-01T09:05:00Z", "started_at": "2026-09-01T14:30:00+05:30", "notes": "Different note"}
    report, objects = validate_rows("measurements", [(2, row), (3, duplicate)])
    assert len(objects) == 1 and "Duplicate" in report[1]["error"]
    url = preview_upload(client, as_csv([row]))
    assert commit(client, url).status_code == 302
    report, objects = validate_rows("measurements", [(2, duplicate)])
    assert not objects and "Duplicate" in report[0]["error"]


def test_expired_preview_cannot_commit_and_owner_is_private(access_app, client):
    url = preview_upload(client, as_csv([observation()]))
    batch_id = int(url.split("/")[-1])
    batch = db.session.get(ImportBatch, batch_id)
    batch.expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert commit(client, url).status_code == 409
    username = "other-" + uuid.uuid4().hex[:10]
    result = access_app.test_cli_runner().invoke(args=["create-officer", "--username", username, "--name", "Another test officer"], input=f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code == 0
    access_app.config["TEST_USERNAME"] = username
    other = access_app.test_client()
    sign_in(access_app, other)
    assert other.get(url).status_code == 404
    assert other.post(url + "/commit", data={"csrf_token": token(other.get("/imports/")), "confirm": "y", "reason": "Not my import"}).status_code == 404


def test_commit_requires_csrf_confirmation_reason_and_ignores_posted_content(access_app, client):
    row = observation()
    url = preview_upload(client, as_csv([row]))
    assert client.post(url + "/commit", data={"confirm": "y", "reason": "x"}).status_code == 400
    assert client.post(url + "/commit", data={"csrf_token": token(client.get(url)), "reason": "x"}).status_code == 400
    assert client.post(url + "/commit", data={"csrf_token": token(client.get(url)), "confirm": "y", "reason": "  "}).status_code == 400
    result = client.post(url + "/commit", data={"csrf_token": token(client.get(url)), "confirm": "y", "reason": "Verify content binding", "value": "99999", "quality_status": "accepted"})
    assert result.status_code == 302
    record = db.session.scalar(select(Measurement).where(Measurement.record_key == row["record_key"]))
    assert str(record.value) == "12.500000" and record.quality_status == "unreviewed"


def test_competing_preview_revalidated_atomically(access_app, client):
    row = observation()
    first = preview_upload(client, as_csv([row]))
    second_row = observation()
    second = preview_upload(client, as_csv([row, second_row]))
    assert commit(client, first).status_code == 302
    assert commit(client, second).status_code == 409
    assert db.session.scalar(select(Measurement).where(Measurement.record_key == second_row["record_key"])) is None
    assert db.session.get(ImportBatch, int(second.split("/")[-1])).status == "preview"


def test_simultaneous_commit_of_same_preview_saves_once(access_app, client):
    row = observation()
    url = preview_upload(client, as_csv([row]))
    csrf = token(client.get(url))
    cookie = client.get_cookie("nila_session").value
    def submit():
        concurrent = access_app.test_client()
        concurrent.set_cookie("nila_session", cookie)
        return concurrent.post(url + "/commit", data={"csrf_token": csrf, "confirm": "y", "reason": "Concurrent save test"}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(results) == [302, 409]
    db.session.rollback()
    assert db.session.scalar(select(func.count()).select_from(Measurement).where(Measurement.record_key == row["record_key"])) == 1


def test_samples_area_point_measurements_end_to_end(access_app, client):
    before = db.session.scalar(select(func.count()).select_from(BuildingSurveyContext))
    for kind, filename in (("areas", "survey-areas.geojson"), ("locations", "survey-locations.csv"), ("measurements", "measurements.csv")):
        url = preview_upload(client, (SAMPLES / filename).read_bytes(), kind)
        assert b"0 records need correction" in client.get(url).data
        result = commit(client, url)
        assert result.status_code == 302, result.get_data(as_text=True)[:1000]
    assert db.session.scalar(select(func.count()).select_from(BuildingSurveyContext)) > before
    record = db.session.scalar(select(Measurement).where(Measurement.record_key == "IMPORT-DEMO-GAMMA-1"))
    assert record.building_id is None and record.survey_location_id and record.track == "regional_radiation"
    area = db.session.scalar(select(SurveyArea).where(SurveyArea.code == "IMPORT-DEMO-AREA-1"))
    assert area.review_status == "unreviewed"
    assert b"Nila synthetic import exercise" in client.get("/map/").data
    assert client.get("/imports/samples/areas").data == (SAMPLES / "survey-areas.geojson").read_bytes()
    assert client.get("/imports/samples/not-a-file").status_code == 404


@pytest.mark.parametrize("changes,expected", [({"latitude": "91"}, "latitude"), ({"longitude": "-181"}, "longitude"),
    ({"latitude": ""}, "latitude"), ({"area_code": "does-not-exist"}, "not found"),
    ({"area_code": "NILA-DEMO-AREA-1", "latitude": "0", "longitude": "0"}, "outside")])
def test_location_errors(access_app, changes, expected):
    row = {"code": "TEST-POINT-" + uuid.uuid4().hex[:10], "area_code": "", "latitude": "-50", "longitude": "-140", "notes": "Synthetic point", "is_synthetic": "true", **changes}
    report, objects = validate_rows("locations", [(2, row)])
    assert not objects and expected in report[0]["error"]


def test_association_overlaps_unknown_coordinates_and_provenance(access_app, client):
    b = new_building(client, latitude="0.000000", longitude="1.000000")
    existing = db.session.scalar(select(func.count()).select_from(Measurement).where(Measurement.building_id == b.id))
    areas = []
    for synthetic in (True, True, False):
        a = SurveyArea(code="TEST-AREA-" + uuid.uuid4().hex[:12], name="Test region", geometry=polygon(), geological_context="Test", source="Test source", observed_on=utcnow().date(), is_synthetic=synthetic)
        db.session.add(a)
        areas.append(a)
    db.session.flush()
    assert associate_building(b, areas) == 2
    db.session.flush()
    assert associate_building(b, areas) == 0
    assert db.session.scalar(select(func.count()).select_from(Measurement).where(Measurement.building_id == b.id)) == existing
    b.latitude, b.longitude = None, None
    assert associate_building(b, areas) == 0
    db.session.rollback()


def test_map_list_api_tracks_unknowns_and_escaping(access_app, client):
    building = new_building(client, name='<script>alert("private")</script>')
    response = client.get("/map/")
    assert response.status_code == 200 and b"&lt;script&gt;" in response.data and b'<script>alert("private")</script>' not in response.data
    data = client.get("/map/data?track=indoor_radon").json
    entry = next(b for b in data["buildings"] if b["id"] == building.id)
    assert entry["latitude"] is None and entry["priority"] == "unknown" and entry["coverage_gap"]
    assert data["unmapped"] >= 2
    assert all(m["track"] == "indoor_radon" for b in data["buildings"] for m in b["evidence"])
    assert all(m["track"] == "regional_radiation" for a in data["areas"] for m in a["evidence"])
    assert all(not b["synthetic"] for b in client.get("/map/data?provenance=real").json["buildings"])
    assert "private_notes" not in json.dumps(data)
    assert b"evidence-list" in response.data and b"JavaScript is disabled" in response.data
    assert "https://tile.openstreetmap.org" in response.headers["Content-Security-Policy"]
    assert "https://tile.openstreetmap.org" not in client.get("/imports/").headers["Content-Security-Policy"]


def test_bad_upload_and_oversized_upload_show_errors(access_app, client):
    result = client.post("/imports/", data={"csrf_token": token(client.get("/imports/")), "kind": "measurements", "upload": (io.BytesIO(b"bad headers"), "input.csv")})
    assert result.status_code == 400 and b"CSV headers" in result.data
    result = client.post("/imports/", data={"csrf_token": token(client.get("/imports/")), "kind": "measurements", "upload": (io.BytesIO(b"x" * 2100000), "input.csv")})
    assert result.status_code == 413


def test_phase4_database_upgrades_without_losing_records(mysql_settings):
    database_name = "nila_phase5_upgrade_" + uuid.uuid4().hex[:16]
    setup = create_app({"TESTING": True}, environ=mysql_settings)
    with setup.app_context():
        with db.engine.begin() as connection:
            connection.execute(text(f"CREATE DATABASE {database_name} CHARACTER SET utf8mb4"))
        db.engine.dispose()
    app = create_app({"TESTING": True}, environ={**mysql_settings, "NILA_DB_NAME": database_name})
    with app.app_context():
        runner = app.test_cli_runner()
        assert runner.invoke(args=["db", "upgrade", "0002_officer_access"]).exit_code == 0
        assert runner.invoke(args=["seed-demo", "--anchor-date", "2026-09-14"]).exit_code == 0
        assert runner.invoke(args=["db", "upgrade"]).exit_code == 0
        assert db.session.scalar(select(func.count()).select_from(Building)) == 50
        assert db.session.scalar(select(func.count()).select_from(ImportBatch)) == 0
        db.session.remove()
        db.engine.dispose()
