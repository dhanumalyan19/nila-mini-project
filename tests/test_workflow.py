"""Phase 7 officer workflow tests against the opt-in isolated MySQL fixture."""
from sqlalchemy import select

from app.extensions import db
from app.models import Action, AssessmentCase, AuditEvent, FollowUpReview, GuidanceEntry, Measurement, MeasurementReview, Officer
from test_access_buildings import access_settings, access_app, client, token


def measurement(key):
    return db.session.scalar(select(Measurement).where(Measurement.record_key == key))


def test_workflow_is_private_and_measurement_review_needs_csrf(access_app, client):
    anonymous = access_app.test_client()
    for route in ("/workflow/", "/workflow/measurements/new", "/workflow/actions/new", "/workflow/audit"):
        response = anonymous.get(route)
        assert response.status_code == 302 and response.location == "/auth/login"
    target = measurement("NILA-DEMO-RADON-028")
    assert client.post(f"/workflow/measurements/{target.id}/review", data={"decision": "accepted", "rationale": "No CSRF"}).status_code == 400


def test_review_assign_complete_and_follow_up_keep_decisions_separate(access_app, client):
    target = measurement("NILA-DEMO-RADON-028")
    case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.building_id == target.building_id, AssessmentCase.track == target.track))
    page = client.get("/workflow/")
    response = client.post(f"/workflow/measurements/{target.id}/review", data={
        "csrf_token": token(page), "decision": "accepted", "rationale": "Synthetic record-quality check only."
    })
    assert response.status_code == 302
    assert target.quality_status == "accepted"
    assert case.workflow_status == "action_required"
    assert db.session.scalar(select(MeasurementReview).where(MeasurementReview.measurement_id == target.id))
    assert db.session.scalar(select(Action).where(Action.case_id == case.id)) is None

    guidance = db.session.scalar(select(GuidanceEntry).where(GuidanceEntry.track == case.track))
    officer = db.session.scalar(select(Officer).where(Officer.username == access_app.config["TEST_USERNAME"]))
    page = client.get("/workflow/actions/new")
    response = client.post("/workflow/actions/new", data={
        "csrf_token": token(page), "case_id": case.id, "guidance_entry_id": guidance.id,
        "assigned_to_id": officer.id, "description": "Arrange additional fictional evidence.",
        "due_at": "", "reason": "Synthetic officer decision."
    })
    assert response.status_code == 302
    action = db.session.scalar(select(Action).where(Action.case_id == case.id))
    assert action.status == "assigned" and case.workflow_status == "action_assigned"

    page = client.get("/workflow/")
    response = client.post(f"/workflow/actions/{action.id}/complete", data={
        "csrf_token": token(page), "completion_notes": "Synthetic completion report.", "reason": "Synthetic update."
    })
    assert response.status_code == 302
    assert action.status == "reported_complete"
    assert case.workflow_status == "action_reported_complete"
    assert case.workflow_status != "outcome_reviewed"

    page = client.get(f"/workflow/actions/{action.id}/follow-up")
    response = client.post(f"/workflow/actions/{action.id}/follow-up", data={
        "csrf_token": token(page), "measurement_id": target.id, "decision": "outcome_reviewed",
        "evidence_notes": "Reviewed synthetic follow-up measurement.", "rationale": "Synthetic reviewer decision."
    })
    assert response.status_code == 302
    assert action.status == "outcome_reviewed" and case.workflow_status == "outcome_reviewed"
    assert db.session.scalar(select(FollowUpReview).where(FollowUpReview.action_id == action.id))
    events = list(db.session.scalars(select(AuditEvent).where(AuditEvent.entity_key == str(action.id))))
    assert {event.event_type for event in events} >= {"action_assigned", "action_reported_complete"}


def test_rejected_measurement_returns_case_to_information_collection(access_app, client):
    target = measurement("NILA-DEMO-RADON-029")
    case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.building_id == target.building_id, AssessmentCase.track == target.track))
    page = client.get("/workflow/")
    response = client.post(f"/workflow/measurements/{target.id}/review", data={
        "csrf_token": token(page), "decision": "needs_information", "rationale": "Synthetic record has missing contextual information."
    })
    assert response.status_code == 302
    assert target.quality_status == "needs_information"
    assert case.workflow_status == "awaiting_assessment"
    assert "Collect or correct" in case.next_action
