"""Real HTTP form/session workflows backed by isolated MySQL; CSRF stays on."""

from datetime import timedelta
import re
import uuid

import pytest
from flask import has_app_context
from flask.testing import FlaskClient
from sqlalchemy import delete, func, select, text
from werkzeug.security import check_password_hash

from app import create_app
from app.extensions import db
from app.models import AssessmentCase, AuditEvent, Building, LoginThrottle, Officer, OfficerSession, Ward
from app.models.common import utcnow

PASSWORD = "test-only-passphrase-12345"


class IsolatedRequestClient(FlaskClient):
    """Match real per-request g/session lifetimes while tests inspect DB objects."""
    def open(self, *args, **kwargs):
        with self.application.app_context():
            response = super().open(*args, **kwargs)
        if has_app_context():
            # End the inspector's REPEATABLE READ snapshot to see HTTP commits.
            db.session.rollback()
        return response


def token(response):
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.get_data(as_text=True))
    assert match, response.get_data(as_text=True)[:200]
    return match[1]


@pytest.fixture(scope="session")
def access_settings(mysql_settings):
    # The MySQL server fixture retains its test data directory for diagnosis.
    # Give each run a fresh schema rather than relying on any destructive cleanup.
    database_name = "nila_access_" + uuid.uuid4().hex[:16]
    setup_app = create_app({"TESTING": True}, environ=mysql_settings)
    with setup_app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text(f"CREATE DATABASE {database_name} CHARACTER SET utf8mb4"))
        db.engine.dispose()
    settings = {**mysql_settings, "NILA_DB_NAME": database_name}
    app = create_app({"TESTING": True}, environ=settings)
    with app.app_context():
        for args in (["db", "upgrade"], ["seed-demo", "--anchor-date", "2026-09-14"]):
            result = app.test_cli_runner().invoke(args=args)
            assert result.exit_code == 0, result.output
        db.session.remove()
        db.engine.dispose()
    return settings


@pytest.fixture
def access_app(access_settings):
    app = create_app({"TESTING": True}, environ=access_settings)
    app.test_client_class = IsolatedRequestClient
    with app.app_context():
        db.session.execute(delete(LoginThrottle))
        db.session.commit()
        username = "test-" + uuid.uuid4().hex[:12]
        result = app.test_cli_runner().invoke(args=["create-officer", "--username", username, "--name", "Test Officer"], input=f"{PASSWORD}\n{PASSWORD}\n")
        assert result.exit_code == 0, result.output
        assert PASSWORD not in result.output
        app.config["TEST_USERNAME"] = username
        yield app
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()


def sign_in(app, client):
    result = client.post("/auth/login", data={"username": app.config["TEST_USERNAME"], "password": PASSWORD, "csrf_token": token(client.get("/auth/login"))})
    assert result.status_code == 302
    assert result.location == "/buildings/"
    return result


@pytest.fixture
def client(access_app):
    client = access_app.test_client()
    sign_in(access_app, client)
    return client


def payload(client, **changes):
    ward_id = db.session.scalar(select(Ward.id).where(Ward.code == "NILA-DEMO-W1"))
    data = {"csrf_token": token(client.get("/buildings/new")), "code": "TEST-" + uuid.uuid4().hex[:12],
            "name": "Synthetic test building", "ward_id": str(ward_id), "building_use": "unknown", "ventilation": "unknown",
            "version_id": "1", "is_synthetic": "y", "change_reason": "Integration test registration"}
    return {**data, **changes}


def new_building(client, **changes):
    data = payload(client, **changes)
    result = client.post("/buildings/new", data=data)
    assert result.status_code == 302, result.get_data(as_text=True)[:500]
    return db.session.scalar(select(Building).where(Building.code == data["code"]))


@pytest.mark.parametrize("route", ["/buildings/", "/buildings/1", "/buildings/new", "/buildings/1/edit"])
def test_anonymous_cannot_read_private_routes(access_app, route):
    response = access_app.test_client().get(route)
    assert response.status_code == 302 and response.location == "/auth/login"
    assert b"Fictional building" not in response.data


def test_login_password_hash_session_headers_and_logout_replay(access_app):
    client = access_app.test_client()
    result = sign_in(access_app, client)
    header = result.headers["Set-Cookie"]
    assert "HttpOnly" in header and "SameSite=Lax" in header
    officer = db.session.scalar(select(Officer).where(Officer.username == access_app.config["TEST_USERNAME"]))
    assert officer.password_hash.startswith("scrypt:") and check_password_hash(officer.password_hash, PASSWORD)
    cookie = client.get_cookie("nila_session").value
    assert client.get("/buildings/").status_code == 200
    result = client.post("/auth/logout", data={"csrf_token": token(client.get("/buildings/"))})
    assert result.status_code == 302
    client.set_cookie("nila_session", cookie)
    assert client.get("/buildings/1").status_code == 302
    assert client.get("/auth/logout").status_code == 405


def test_wrong_unknown_and_disabled_users_have_same_error(access_app):
    client = access_app.test_client()
    for username in (access_app.config["TEST_USERNAME"], "does-not-exist", "demo-officer-1"):
        response = client.post("/auth/login", data={"username": username, "password": "incorrect", "csrf_token": token(client.get("/auth/login"))})
        assert response.status_code == 401
        assert b"Username or password is incorrect" in response.data
        assert "officer_token" not in client.get_cookie("nila_session").value


def test_login_does_not_redirect_to_attacker_url(access_app):
    client = access_app.test_client()
    csrf = token(client.get("/auth/login?next=https://example.invalid/steal"))
    response = client.post("/auth/login?next=https://example.invalid/steal", data={"csrf_token": csrf, "username": access_app.config["TEST_USERNAME"], "password": PASSWORD})
    assert response.location == "/buildings/"


def test_expired_and_disabled_sessions_fail_closed(access_app, client):
    officer = db.session.scalar(select(Officer).where(Officer.username == access_app.config["TEST_USERNAME"]))
    session_record = db.session.scalar(select(OfficerSession).where(OfficerSession.officer_id == officer.id))
    session_record.expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert client.get("/buildings/").status_code == 302
    sign_in(access_app, client)
    officer.is_active = False
    db.session.commit()
    assert client.get("/buildings/").status_code == 302


def test_csrf_blocks_modifying_routes(access_app, client):
    for route in ("/auth/logout", "/buildings/new", "/buildings/1/edit", "/buildings/1/assignment/indoor_radon"):
        assert client.post(route, data={}).status_code == 400
    assert access_app.test_client().post("/auth/login", data={"username": "bad", "password": "bad"}).status_code == 400


def test_create_unknown_fields_and_separate_assessment_tracks(access_app, client):
    building = new_building(client)
    assert building.approximate_occupancy is None and building.latitude is None
    assert building.construction_year is None and building.ventilation == "unknown"
    cases = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.building_id == building.id)))
    assert {c.track for c in cases} == {"regional_radiation", "indoor_radon"}
    assert all(c.priority_band == "unknown" and c.evidence_status == "insufficient_information" for c in cases)
    assert all(c.responsible_officer_id for c in cases)
    assert b"Unknown" in client.get(f"/buildings/{building.id}").data


@pytest.mark.parametrize("change", [
    {"latitude": "99", "longitude": "0"}, {"latitude": "10"}, {"approximate_occupancy": "-1"},
    {"construction_year": "9999"}, {"hours_of_use_per_day": "25"}, {"ward_id": "999999"},
    {"latitude": "NaN", "longitude": "0"}, {"hours_of_use_per_day": "Infinity"}, {"change_reason": "   "},
    {"is_synthetic": ""},
])
def test_invalid_building_forms_retain_values_without_writes(access_app, client, change):
    data = payload(client, **change)
    response = client.post("/buildings/new", data=data)
    assert response.status_code == 400
    assert data["code"].encode() in response.data
    assert db.session.scalar(select(Building).where(Building.code == data["code"])) is None


def test_duplicate_id_edit_conflict_and_audit(access_app, client):
    building = new_building(client)
    duplicate = payload(client, code=building.code)
    assert client.post("/buildings/new", data=duplicate).status_code == 400
    edit_data = payload(client, code=building.code, name="Changed by officer", change_reason="Correcting name")
    assert client.post(f"/buildings/{building.id}/edit", data=edit_data).status_code == 302
    assert building.name == "Changed by officer" and building.version_id == 2
    edit_data.update(name="Stale overwrite", csrf_token=token(client.get(f"/buildings/{building.id}/edit")))
    assert client.post(f"/buildings/{building.id}/edit", data=edit_data).status_code == 409
    assert building.name == "Changed by officer"
    event = db.session.scalar(select(AuditEvent).where(AuditEvent.entity_key == str(building.id), AuditEvent.event_type == "building_updated"))
    assert event.reason == "Correcting name" and event.before["name"] == "Synthetic test building"


def test_search_filter_empty_state_and_html_escaping(access_app, client):
    building = new_building(client, name="<script>alert(1)</script>")
    response = client.get("/buildings/", query_string={"q": building.code})
    assert b"&lt;script&gt;" in response.data and b"<script>alert" not in response.data
    assert b"1 building" in response.data
    assert b"No matching buildings" in client.get("/buildings/?q=absent-unique-record").data
    assert client.get("/buildings/?page=2").status_code == 200
    assert b"No matching buildings" in client.get("/buildings/?q=%25").data


def test_assignment_changes_are_audited_without_priority_change(access_app, client):
    building = new_building(client)
    case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.building_id == building.id, AssessmentCase.track == "indoor_radon"))
    response = client.post(f"/buildings/{building.id}/assignment/indoor_radon", data={"csrf_token": token(client.get(f"/buildings/{building.id}")), "responsible_officer_id": "0", "next_action": "Arrange evidence collection", "reason": "Awaiting available officer", "priority_band": "priority", "workflow_status": "outcome_reviewed"})
    assert response.status_code == 302
    assert case.responsible_officer_id is None and case.next_action == "Arrange evidence collection"
    assert case.priority_band == "unknown" and case.workflow_status == "awaiting_assessment"


def test_evidence_tracks_units_and_private_notes_stay_private(access_app, client):
    response = client.get("/buildings/26")
    assert response.status_code == 200
    assert b"Bq/m3" in response.data and b"uSv/h" in response.data
    assert b"SYNTHETIC OFFICER-ONLY NOTE" in response.data
    for route in ("/", "/auth/login", "/health/live", "/buildings/26"):
        assert b"SYNTHETIC OFFICER-ONLY NOTE" not in access_app.test_client().get(route).data


def test_login_throttle_blocks_after_twenty_submissions(access_app):
    client = access_app.test_client()
    for index in range(21):
        response = client.post("/auth/login", data={"username": "absent", "password": "wrong", "csrf_token": token(client.get("/auth/login"))})
        assert response.status_code == (401 if index < 20 else 429)
    assert response.headers["Retry-After"] == "600"


def test_officer_creation_rejects_duplicate_username(access_app):
    result = access_app.test_cli_runner().invoke(args=["create-officer", "--username", access_app.config["TEST_USERNAME"], "--name", "Duplicate"])
    assert result.exit_code == 1 and "already exists" in result.output


def test_record_persists_in_fresh_app(access_app, access_settings, client):
    building = new_building(client)
    code = building.code
    app = create_app({"TESTING": True}, environ=access_settings)
    with app.app_context():
        restored = db.session.scalar(select(Building).where(Building.code == code))
        assert restored.name == "Synthetic test building"
        db.session.remove()
        db.engine.dispose()


def test_anonymous_post_with_valid_csrf_cannot_create(access_app):
    client = access_app.test_client()
    csrf = token(client.get("/auth/login"))
    count = db.session.scalar(select(func.count()).select_from(Building))
    result = client.post("/buildings/new", data={"csrf_token": csrf, "code": "UNAUTHORIZED"})
    assert result.status_code == 302 and result.location == "/auth/login"
    assert db.session.scalar(select(func.count()).select_from(Building)) == count


def test_upgrade_preserves_existing_phase3_building(mysql_settings):
    setup_app = create_app({"TESTING": True}, environ=mysql_settings)
    with setup_app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("CREATE DATABASE nila_upgrade_test CHARACTER SET utf8mb4"))
        db.engine.dispose()
    app = create_app({"TESTING": True}, environ={**mysql_settings, "NILA_DB_NAME": "nila_upgrade_test"})
    with app.app_context():
        runner = app.test_cli_runner()
        assert runner.invoke(args=["db", "upgrade", "0001_nila_schema"]).exit_code == 0
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO wards (id, code, name, locality, created_at, is_synthetic) VALUES (1, 'OLD-WARD', 'Existing ward', 'Fictional upgrade test', UTC_TIMESTAMP(), 1)"))
            connection.execute(text("INSERT INTO buildings (code, name, ward_id, building_use, ventilation, created_at, is_synthetic) VALUES ('OLD-BUILDING', 'Keep this building', 1, 'unknown', 'unknown', UTC_TIMESTAMP(), 1)"))
        assert runner.invoke(args=["db", "upgrade"]).exit_code == 0
        building = db.session.scalar(select(Building).where(Building.code == "OLD-BUILDING"))
        assert building.name == "Keep this building" and building.version_id == 1
        db.session.remove()
        db.engine.dispose()
