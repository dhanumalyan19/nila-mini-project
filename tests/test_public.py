"""Phase 8 privacy-safe public lookup and request intake tests."""
from sqlalchemy import func, select

from app.extensions import db
from app.models import AuditEvent, PublicRequest
from test_access_buildings import access_settings, access_app, client, token


def test_public_lookup_is_curated_and_hides_private_building_data(access_app):
    response = access_app.test_client().get("/public/localities?q=Fictional Demonstration Region")
    assert response.status_code == 200
    assert b"Regional observations provide context only" in response.data
    assert b"SYNTHETIC OFFICER-ONLY NOTE" not in response.data
    assert b"NILA-DEMO-B001" not in response.data


def test_public_request_is_validated_rate_limited_and_audited(access_app):
    public_client = access_app.test_client()
    page = public_client.get("/public/requests/new")
    response = public_client.post("/public/requests/new", data={
        "csrf_token": token(page), "locality": "Fictional Demonstration Region",
        "contact": "resident@example.test", "request_text": "Please review the available regional information.", "website": ""
    })
    assert response.status_code == 302
    row = db.session.scalar(select(PublicRequest).order_by(PublicRequest.id.desc()))
    assert row.status == "submitted" and row.contact == "resident@example.test"
    assert db.session.scalar(select(AuditEvent).where(AuditEvent.event_type == "public_request_submitted", AuditEvent.entity_key == str(row.id)))
    page = public_client.get("/public/requests/new")
    response = public_client.post("/public/requests/new", data={
        "csrf_token": token(page), "locality": "Fictional Demonstration Region",
        "contact": "resident@example.test", "request_text": "Please send another review request.", "website": ""
    })
    assert response.status_code == 400
    assert db.session.scalar(select(func.count()).select_from(PublicRequest)) == 1


def test_officer_can_update_public_request_status_with_reason(access_app, client):
    row = PublicRequest(reference="NILA-REQ-TEST", locality="Demo locality", request_text="Please review this locality.", status="submitted", is_synthetic=False)
    db.session.add(row)
    db.session.commit()
    page = client.get("/workflow/")
    response = client.post(f"/workflow/requests/{row.id}/status", data={
        "csrf_token": token(page), "status": "under_review", "reason": "Officer triage started."
    })
    assert response.status_code == 302
    assert row.status == "under_review"
