"""Phase 6 planning and booking workflows against actual isolated MySQL."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import AssessmentCase, AuditEvent, Campaign, CampaignCandidate, Equipment, EquipmentBooking, Escalation, Officer, OfficerOverride, PlanRun, PlanSelection
from app.planner.service import allocations, category, effective_capacity, generate
from test_access_buildings import access_settings, access_app, client, token


def campaign():
    return db.session.scalar(select(Campaign).where(Campaign.code == "NILA-DEMO-25-10"))


def post_plan(client, campaign_id, seed=123456):
    page = client.get(f"/planner/{campaign_id}")
    return client.post(f"/planner/{campaign_id}/generate", data={"csrf_token": token(page), "random_seed": str(seed), "reason": "Synthetic planner verification"})


def test_planner_private_routes_and_campaign_page(access_app, client):
    anonymous = access_app.test_client()
    for route in ("/planner/", "/planner/new", "/planner/1", "/planner/equipment"):
        response = anonymous.get(route)
        assert response.status_code == 302 and response.location == "/auth/login"
    response = client.get("/planner/")
    assert response.status_code == 200 and b"NILA-DEMO-25-10" in response.data
    assert client.post(f"/planner/{campaign().id}/generate", data={"reason": "No CSRF"}).status_code == 400


def test_demo_25_10_shortfall_preserves_priority_and_escalates(access_app, client):
    item = campaign()
    original = {case.id: (case.priority_band, case.waiting_since, case.responsible_officer_id) for case in db.session.scalars(
        select(AssessmentCase).join(CampaignCandidate, CampaignCandidate.case_id == AssessmentCase.id).where(CampaignCandidate.campaign_id == item.id))}
    response = post_plan(client, item.id)
    assert response.status_code == 302
    plan = db.session.scalar(select(PlanRun).where(PlanRun.campaign_id == item.id).order_by(PlanRun.id.desc()))
    assert (plan.total_demand, plan.effective_capacity, plan.selected_count, plan.unmet_demand, plan.deadline_feasible) == (25, 10, 10, 15, False)
    selections = list(db.session.scalars(select(PlanSelection).where(PlanSelection.plan_run_id == plan.id)))
    assert len(selections) == len({row.case_id for row in selections}) == 10
    assert {row.category for row in selections} == {"priority_screening"}
    assert db.session.scalar(select(func.count()).select_from(Escalation).where(Escalation.plan_run_id == plan.id)) == 1
    selected_ids = {row.case_id for row in selections}
    for case_id, (priority, waiting, officer) in original.items():
        case = db.session.get(AssessmentCase, case_id)
        assert (case.priority_band, case.waiting_since, case.responsible_officer_id) == (priority, waiting, officer)
        assert case.scheduling_status == ("planned" if case_id in selected_ids else "waiting")
    response = client.get(f"/planner/plans/{plan.id}")
    assert b"25 buildings need equal attention, 10 slots are available, and 15 remain unmet" in response.data
    assert b"All 25 retain their original priority" in response.data
    assert db.session.scalar(select(AuditEvent).where(AuditEvent.entity_key == str(plan.id), AuditEvent.event_type == "plan_generated"))


def test_same_seed_reproduces_equal_waiting_tie_order(access_app, client):
    item = campaign()
    assert post_plan(client, item.id, seed=9981).status_code == 302
    assert post_plan(client, item.id, seed=9981).status_code == 302
    plans = list(db.session.scalars(select(PlanRun).where(PlanRun.campaign_id == item.id).order_by(PlanRun.id.desc()).limit(2)))
    first = [row.case_id for row in db.session.scalars(select(PlanSelection).where(PlanSelection.plan_run_id == plans[0].id).order_by(PlanSelection.selection_order))]
    second = [row.case_id for row in db.session.scalars(select(PlanSelection).where(PlanSelection.plan_run_id == plans[1].id).order_by(PlanSelection.selection_order))]
    assert first == second and all("recorded random seed 9981" in row.tie_break_reason for row in db.session.scalars(select(PlanSelection).where(PlanSelection.plan_run_id == plans[0].id)))


def test_required_follow_up_precedes_weights_and_capacity_limits(access_app):
    cases = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.building_id.in_([31, 32, 33, 34, 35]), AssessmentCase.track == "indoor_radon").order_by(AssessmentCase.id)))
    item = Campaign(code="TEST-FOLLOWUP-2", name="Synthetic follow-up precedence", starts_on=date(2026, 9, 14), ends_on=date(2026, 9, 20),
        available_slots=7, staff_slots=2, equipment_slots=5, track="indoor_radon", queue_weights={"required_follow_up": 0, "priority_screening": 100, "coverage_gap": 0},
        notes="Test", is_synthetic=True)
    db.session.add(item)
    db.session.flush()
    for case in cases:
        db.session.add(CampaignCandidate(campaign_id=item.id, case_id=case.id, is_synthetic=True))
    officer = db.session.scalar(select(Officer).where(Officer.username == access_app.config["TEST_USERNAME"]))
    plan, selected, unselected = generate(item.id, officer.id, "test", seed=42)
    assert effective_capacity(item) == 2
    assert len(selected) == 2 and len(unselected) == 3
    assert all(name == "required_follow_up" and case.follow_up_required for name, case in selected)
    assert plan.unmet_demand == 3
    db.session.rollback()


def test_create_campaign_validation_and_no_automatic_candidates(access_app, client):
    page = client.get("/planner/new")
    response = client.post("/planner/new", data={"csrf_token": token(page), "code": "TEST-NEW-CAMPAIGN", "name": "Officer campaign", "track": "indoor_radon",
        "starts_on": "2026-09-14", "ends_on": "2026-09-20", "available_slots": "2", "staff_slots": "", "equipment_slots": "",
        "follow_up_weight": "3", "priority_weight": "5", "coverage_weight": "2", "notes": "Officer-created planning exercise", "reason": "Test creation"})
    assert response.status_code == 302
    item = db.session.scalar(select(Campaign).where(Campaign.code == "TEST-NEW-CAMPAIGN"))
    assert item and not item.is_synthetic
    assert db.session.scalar(select(func.count()).select_from(CampaignCandidate).where(CampaignCandidate.campaign_id == item.id)) == 0
    response = client.post("/planner/new", data={"csrf_token": token(client.get("/planner/new")), "code": "BAD", "name": "Bad", "track": "indoor_radon", "starts_on": "2026-09-20", "ends_on": "2026-09-14", "available_slots": "1", "follow_up_weight": "0", "priority_weight": "0", "coverage_weight": "0", "notes": "x", "reason": "x"})
    assert response.status_code == 400


def test_officer_override_replaces_without_capacity_or_priority_change(access_app, client):
    item = campaign()
    assert post_plan(client, item.id).status_code == 302
    plan = db.session.scalar(select(PlanRun).where(PlanRun.campaign_id == item.id).order_by(PlanRun.id.desc()))
    selections = list(db.session.scalars(select(PlanSelection).where(PlanSelection.plan_run_id == plan.id).order_by(PlanSelection.selection_order)))
    selected = selections[0]
    replaced_case_id = selected.case_id
    replacement = db.session.scalar(select(AssessmentCase).join(CampaignCandidate, CampaignCandidate.case_id == AssessmentCase.id).where(CampaignCandidate.campaign_id == item.id, AssessmentCase.id.not_in([row.case_id for row in selections])))
    original_priority = replacement.priority_band
    page = client.get(f"/planner/plans/{plan.id}")
    response = client.post(f"/planner/plans/{plan.id}/override", data={"csrf_token": token(page), "replacement_case_id": str(replacement.id), "selection_order": str(selected.selection_order), "reason": "Synthetic qualified officer exception"})
    assert response.status_code == 302
    db.session.expire_all()
    revised = db.session.scalar(select(PlanSelection).where(PlanSelection.id == selected.id))
    assert revised.case_id == replacement.id and db.session.get(AssessmentCase, replacement.id).priority_band == original_priority
    assert db.session.scalar(select(func.count()).select_from(OfficerOverride).where(OfficerOverride.plan_run_id == plan.id)) == 1
    assert db.session.get(AssessmentCase, replaced_case_id).scheduling_status == "waiting"
    assert db.session.get(AssessmentCase, replacement.id).scheduling_status == "planned"
    assert db.session.scalar(select(func.count()).select_from(PlanSelection).where(PlanSelection.plan_run_id == plan.id)) == plan.selected_count


def test_equipment_booking_rejects_overlap_and_track_provenance_mismatch(access_app, client):
    equipment = db.session.scalar(select(Equipment).where(Equipment.code == "NILA-DEMO-DETECTOR-2"))
    case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.building_id == 1, AssessmentCase.track == "indoor_radon"))
    page = client.get("/planner/equipment")
    data = {"csrf_token": token(page), "equipment_id": str(equipment.id), "case_id": str(case.id), "starts_at": "2026-09-14T09:00", "ends_at": "2026-09-14T10:00", "notes": "Synthetic reservation", "reason": "Test reservation"}
    assert client.post("/planner/equipment", data=data).status_code == 302
    assert db.session.scalar(select(func.count()).select_from(EquipmentBooking).where(EquipmentBooking.equipment_id == equipment.id)) == 1
    data["csrf_token"] = token(client.get("/planner/equipment"))
    data["starts_at"], data["ends_at"] = "2026-09-14T09:30", "2026-09-14T10:30"
    response = client.post("/planner/equipment", data=data)
    assert response.status_code == 400 and b"already has an active overlapping booking" in response.data
    data["csrf_token"] = token(client.get("/planner/equipment"))
    regional_case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.track == "regional_radiation"))
    data["case_id"] = str(regional_case.id)
    response = client.post("/planner/equipment", data=data)
    assert response.status_code == 400 and b"same track and data origin" in response.data


def test_allocation_never_wastes_capacity_when_weighted_queue_is_empty():
    class Thing:
        available_slots, staff_slots, equipment_slots = 10, None, None
        queue_weights = {"required_follow_up": 3, "priority_screening": 5, "coverage_gap": 2}
    queues = {"required_follow_up": [object()], "priority_screening": [], "coverage_gap": [object()] * 9}
    assert allocations(Thing(), queues, 10) == {"required_follow_up": 1, "priority_screening": 0, "coverage_gap": 9}
    class Case:
        follow_up_required = False
        workflow_status = "awaiting_assessment"
        priority_band = "unknown"
    assert category(Case()) == "coverage_gap"
