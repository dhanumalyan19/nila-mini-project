"""Run with --mysql-integration. These tests use actual MySQL, never SQLite."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app import create_app
from app.extensions import db
from app.models import (
    Action, AssessmentCase, AuditEvent, Building, BuildingSurveyContext, Campaign,
    CampaignCandidate, EquipmentBooking, FollowUpReview, Measurement, MeasurementKind,
    Officer, OfficerOverride, PlanRun, PlanSelection, ScreeningRuleVersion, SeedBatch,
    SurveyArea, Ward,
)
from app.seed import SeedConflict, demo_summary, seed_demo

ANCHOR = date(2026, 9, 14)


def invoke_ok(app, *args):
    result = app.test_cli_runner().invoke(args=list(args), standalone_mode=False)
    # Test server only: diagnostic class/error code excludes credentials and SQL.
    if result.exit_code:
        context = getattr(result.exception, "__context__", None)
        original = getattr(context, "orig", None)
        diagnostic = getattr(original, 'args', ())
        # The test instance uses only generated schema/fixture identifiers.
        pytest.fail(f"Command {' '.join(args)} failed: {result.output}; database diagnostic: {diagnostic}")
    return result.output


@pytest.fixture(scope="session")
def seeded_mysql(mysql_settings):
    app = create_app({"TESTING": True}, environ=mysql_settings)
    with app.app_context():
        invoke_ok(app, "db", "upgrade")
        invoke_ok(app, "db", "current")
        with db.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_import_previews"
        # Round-trip an EMPTY temporary schema, before any test or seeded data.
        invoke_ok(app, "db", "downgrade", "base")
        assert set(inspect(db.engine).get_table_names()) <= {"alembic_version"}
        invoke_ok(app, "db", "upgrade")
        with db.engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), db.metadata) == []
        assert db.session.scalar(select(func.count()).select_from(MeasurementKind)) == 2
        output = invoke_ok(app, "seed-demo", "--anchor-date", ANCHOR.isoformat())
        assert "Synthetic demo data created" in output
        db.session.remove()
        db.engine.dispose()
    return mysql_settings


@pytest.fixture
def data_app(seeded_mysql):
    app = create_app({"TESTING": True}, environ=seeded_mysql)
    with app.app_context():
        yield app
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()


def first(model):
    return db.session.scalar(select(model).order_by(model.id))


def test_actual_mysql_connection_migration_and_seed_counts(data_app):
    assert "Connected to MySQL" in invoke_ok(data_app, "db-check")
    assert data_app.test_client().get("/health/ready").status_code == 200
    expected = {Building: 50, Ward: 5, AssessmentCase: 55, Measurement: 19,
                Officer: 3, ScreeningRuleVersion: 2, CampaignCandidate: 25,
                AuditEvent: 1, PlanRun: 0, PlanSelection: 0}
    for model, count in expected.items():
        assert db.session.scalar(select(func.count()).select_from(model)) == count
    assert len(inspect(db.engine).get_table_names()) == len(db.metadata.tables) + 1


def test_seed_preserves_edits_and_added_records(data_app):
    building = first(Building)
    building.name = "Officer-edited name"
    user_record = Building(code="USER-PRESERVE-ME", name="Officer record", ward_id=building.ward_id)
    db.session.add(user_record)
    db.session.flush()
    created, manifest = seed_demo(date(2030, 1, 1))
    assert not created
    assert manifest["anchor_date"] == ANCHOR.isoformat()
    db.session.expire_all()
    assert building.name == "Officer-edited name"
    assert user_record.id is not None and not user_record.is_synthetic
    assert db.session.scalar(select(func.count()).select_from(Building)) == 51


def test_cli_seed_repeat_is_noop(data_app):
    output = invoke_ok(data_app, "seed-demo", "--anchor-date", "2030-01-01")
    assert "nothing was changed" in output
    assert db.session.scalar(select(func.count()).select_from(Building)) == 50
    assert db.session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_conflicting_seed_identifier_rolls_back_everything(data_app, monkeypatch):
    # Simulate a fresh batch encountering an identifier already owned by a row.
    monkeypatch.setattr("app.seed.BATCH_KEY", "test-conflicting-batch")
    result = data_app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code == 1
    assert "Reserved demo identifier" in result.output
    assert db.session.scalar(select(func.count()).select_from(SeedBatch)) == 1
    assert db.session.scalar(select(func.count()).select_from(Building)) == 50
    assert first(Officer).username == "demo-officer-1"


def test_records_survive_fresh_app_and_connection(seeded_mysql):
    # Separate Flask instances and disposed connection pools, same actual database.
    for _ in range(2):
        app = create_app({"TESTING": True}, environ=seeded_mysql)
        with app.app_context():
            assert db.session.scalar(select(func.count()).select_from(Building)) == 50
            assert first(Building).name == "Aster Residential Residence 001"
            db.session.remove()
            db.engine.dispose()


def test_unknown_values_remain_null_and_evidence_not_inferred(data_app):
    building = db.session.scalar(select(Building).where(Building.code == "NILA-DEMO-B049"))
    assert building.latitude is None and building.longitude is None
    assert building.construction_year is None and building.approximate_occupancy is None
    assert building.hours_of_use_per_day is None and building.ventilation == "unknown"
    measurement = db.session.scalar(select(Measurement).where(Measurement.record_key == "NILA-DEMO-RADON-040"))
    assert measurement.value is None and measurement.record_status == "incomplete"
    assert measurement.instrument is None and measurement.duration_seconds is None
    for case in db.session.scalars(select(AssessmentCase).where(AssessmentCase.track == "regional_radiation")):
        assert case.priority_band == "unknown"
        assert case.evidence_status == "insufficient_information"


def test_equal_25_case_capacity_data_and_no_selections(data_app):
    before = [(c.id, c.priority_band) for c in db.session.scalars(select(AssessmentCase))]
    summary = json.loads(invoke_ok(data_app, "demo-summary"))
    assert summary["total_demand"] == 25
    assert summary["available_capacity"] == 10
    assert summary["minimum_unmet_demand"] == 15
    cases = list(db.session.scalars(select(AssessmentCase).join(CampaignCandidate)))
    assert len(cases) == 25
    assert len({c.waiting_since for c in cases}) == 1
    assert len({c.required_by for c in cases}) == 1
    assert all(c.priority_band == "priority" and c.waiting_allowed is None for c in cases)
    assert all(c.responsible_officer_id and c.scheduling_status == "waiting" for c in cases)
    assert before == [(c.id, c.priority_band) for c in db.session.scalars(select(AssessmentCase))]


def test_synthetic_provenance_offshore_geometry_and_disabled_officers(data_app):
    for model in (Building, Measurement, SurveyArea, AssessmentCase, Officer, EquipmentBooking):
        assert all(row.is_synthetic and row.seed_batch_id for row in db.session.scalars(select(model)))
    for officer in db.session.scalars(select(Officer)):
        assert not officer.is_active
        assert officer.password_hash.startswith("scrypt:")
    for area in db.session.scalars(select(SurveyArea)):
        ring = area.geometry["coordinates"][0]
        assert area.geometry["type"] == "Polygon" and ring[0] == ring[-1]
    for link in db.session.scalars(select(BuildingSurveyContext)):
        building = db.session.get(Building, link.building_id)
        area = db.session.get(SurveyArea, link.survey_area_id)
        ring = area.geometry["coordinates"][0]
        assert min(p[0] for p in ring) <= float(building.longitude) <= max(p[0] for p in ring)
        assert min(p[1] for p in ring) <= float(building.latitude) <= max(p[1] for p in ring)
        assert link.association_method == "synthetic_fixture"


def test_coverage_gap_and_due_followups(data_app):
    ember = db.session.scalar(select(Ward).where(Ward.code == "NILA-DEMO-W5"))
    assert db.session.scalar(select(func.count()).select_from(Measurement).join(Building).where(Building.ward_id == ember.id)) == 0
    due = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.follow_up_required.is_(True))))
    assert len(due) == 5
    assert all(case.required_by < datetime.combine(ANCHOR, datetime.min.time()) for case in due)
    booking = first(EquipmentBooking)
    assert booking.ends_at > datetime.combine(ANCHOR, datetime.min.time()) + timedelta(days=1)


def test_action_completion_has_no_automatic_review(data_app):
    action = db.session.scalar(select(Action).where(Action.status == "reported_complete"))
    assert action.reported_complete_at is not None
    assert db.session.get(AssessmentCase, action.case_id).workflow_status == "follow_up_pending"
    assert db.session.scalar(select(func.count()).select_from(FollowUpReview)) == 0


@pytest.mark.parametrize("changes", [
    {"unit": "uSv/h"}, {"track": "regional_radiation"}, {"value": Decimal("-1")},
    {"started_at": datetime(2026, 9, 15), "ended_at": datetime(2026, 9, 14)},
    {"duration_seconds": 7}, {"record_status": "submitted", "value": None},
    {"quality_status": "safe"}, {"building_id": None, "survey_location_id": None},
    {"record_key": "NILA-DEMO-GAMMA-1"},
])
def test_mysql_rejects_invalid_measurements(data_app, changes):
    values = dict(record_key="INVALID-TEST", building_id=first(Building).id,
        track="indoor_radon", measurement_type="indoor_radon_concentration", unit="Bq/m3",
        value=Decimal("45"), started_at=datetime(2026, 9, 1), ended_at=datetime(2026, 9, 2),
        duration_seconds=86400, instrument="Synthetic detector", source="Test only",
        record_status="submitted", notes="Synthetic test", is_synthetic=True)
    values.update(changes)
    db.session.add(Measurement(**values))
    with pytest.raises((IntegrityError, OperationalError)):
        db.session.flush()


@pytest.mark.parametrize("changes", [
    {"latitude": 91, "longitude": 20}, {"longitude": 181, "latitude": 20},
    {"latitude": 10}, {"approximate_occupancy": -1}, {"hours_of_use_per_day": 25},
])
def test_mysql_rejects_invalid_buildings(data_app, changes):
    db.session.add(Building(code="INVALID-BUILDING", name="Synthetic test", ward_id=first(Ward).id, **changes))
    with pytest.raises((IntegrityError, OperationalError)):
        db.session.flush()


def test_mysql_rejects_unreviewed_waiting_permission(data_app):
    case = first(AssessmentCase)
    case.waiting_allowed = True
    with pytest.raises((IntegrityError, OperationalError)):
        db.session.flush()


def test_mysql_rejects_rule_from_other_track(data_app):
    case = first(AssessmentCase)
    rule = db.session.scalar(select(ScreeningRuleVersion).where(ScreeningRuleVersion.track == "regional_radiation"))
    case.rule_version_id = rule.id
    with pytest.raises(IntegrityError):
        db.session.flush()


def test_mysql_rejects_bad_booking_interval(data_app):
    booking = first(EquipmentBooking)
    booking.ends_at = booking.starts_at
    with pytest.raises((IntegrityError, OperationalError)):
        db.session.flush()


def test_mysql_rejects_duplicate_candidate(data_app):
    candidate = first(CampaignCandidate)
    db.session.add(CampaignCandidate(campaign_id=candidate.campaign_id, case_id=candidate.case_id))
    with pytest.raises(IntegrityError):
        db.session.flush()


def test_mysql_rejects_blank_override_reason_and_duplicate_selection(data_app):
    campaign = first(Campaign)
    case = first(AssessmentCase)
    officer = first(Officer)
    plan = PlanRun(campaign_id=campaign.id, generated_by_id=officer.id, random_seed=1,
        algorithm_version="test-only", input_snapshot={}, rule_snapshot={}, total_demand=25,
        effective_capacity=10, selected_count=1, unmet_demand=24, is_synthetic=True)
    db.session.add(plan)
    db.session.flush()
    with db.session.begin_nested() as transaction:
        db.session.add(OfficerOverride(plan_run_id=plan.id, case_id=case.id, officer_id=officer.id,
            reason="   ", before={}, after={}, is_synthetic=True))
        with pytest.raises((IntegrityError, OperationalError)):
            db.session.flush()
        transaction.rollback()
    values = dict(plan_run_id=plan.id, case_id=case.id, category="priority_screening", applicable_rule="test",
        rule_version_id=case.rule_version_id, evidence_used={}, tie_break_reason="Synthetic test", is_synthetic=True)
    db.session.add(PlanSelection(selection_order=1, **values))
    db.session.flush()
    db.session.add(PlanSelection(selection_order=2, **values))
    with pytest.raises(IntegrityError):
        db.session.flush()


def test_public_foundation_never_serializes_seed_records(data_app):
    client = data_app.test_client()
    for route in ("/", "/health/live", "/health/ready"):
        response = client.get(route)
        assert response.status_code == 200
        assert b"SYNTHETIC OFFICER-ONLY NOTE" not in response.data
        assert b"Fictional building" not in response.data
        assert b"password_hash" not in response.data
