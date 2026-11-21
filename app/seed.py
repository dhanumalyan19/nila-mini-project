"""One atomic, add-only fictional fixture. Repeating a batch never edits records."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import random
import secrets

from sqlalchemy import func, select
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import (
    Action, AssessmentCase, AuditEvent, Building, BuildingSurveyContext, Campaign,
    CampaignCandidate, Equipment, EquipmentBooking, GuidanceEntry, Measurement,
    MeasurementReview, Officer, ScreeningRuleVersion, SeedBatch, SurveyArea,
    SurveyLocation, Ward,
)

BATCH_KEY = "nila-fictional-v1"
DEMO_SEED = 41025
DEMO_BUILDING_NAMES = (
    "Aster Sunrise School", "Aster Civic Hall", "Aster Health Post", "Aster Market House", "Aster Library",
    "Aster Family Centre", "Aster Workshop", "Aster Learning Hub", "Aster Garden Offices", "Aster Harbour Hostel",
    "Birch Riverside School", "Birch Community Hall", "Birch Health Centre", "Birch Cooperative Store", "Birch Public Library",
    "Birch Family Centre", "Birch Trades Workshop", "Birch Learning Hub", "Birch Garden Offices", "Birch Harbour Hostel",
    "Cedar Hill School", "Cedar Neighbourhood Hall", "Cedar Health Post", "Cedar Market House", "Cedar Reading Room",
    "Cedar Family Centre", "Cedar Repair Workshop", "Cedar Learning Hub", "Cedar Garden Offices", "Cedar Harbour Hostel",
    "Dune Coast School", "Dune Civic Hall", "Dune Health Centre", "Dune Cooperative Store", "Dune Public Library",
    "Dune Family Centre", "Dune Trades Workshop", "Dune Learning Hub", "Dune Garden Offices", "Dune Harbour Hostel",
    "Ember Valley School", "Ember Community Hall", "Ember Health Post", "Ember Market House", "Ember Reading Room",
    "Ember Family Centre", "Ember Repair Workshop", "Ember Learning Hub", "Ember Garden Offices", "Ember Harbour Hostel",
)


def demo_building_name(ward_prefix, building_use, number):
    labels = {
        "residential": "Residential Residence", "school": "School Building",
        "office": "Office Building", "community": "Community Centre",
        "commercial": "Commercial Building", "industrial": "Industrial Facility",
        "other": "Mixed-use Building", "unknown": "Assessment Site",
    }
    return f"{ward_prefix} {labels.get(building_use, 'Assessment Site')} {number:03}"


class SeedConflict(ValueError):
    pass


def seed_demo(anchor_date=None):
    """Return (created, manifest); caller commits or rolls back the whole batch."""
    existing = db.session.scalar(select(SeedBatch).where(SeedBatch.key == BATCH_KEY))
    if existing:
        return False, existing.manifest
    # Reserve the key within the same transaction. A concurrent run loses the
    # unique-key race and rolls back; it cannot create half a second seed batch.
    anchor = anchor_date or date.today()
    stamp = datetime.combine(anchor, time(9))
    rng = random.Random(DEMO_SEED)
    batch = SeedBatch(key=BATCH_KEY, anchor_date=anchor, random_seed=DEMO_SEED, manifest={})
    db.session.add(batch)
    db.session.flush()
    synthetic = {"is_synthetic": True, "seed_batch_id": batch.id}

    def add(model, **values):
        # Reserved natural keys must not silently appropriate user-entered data.
        natural_key = next((key for key in ("code", "username", "key", "record_key") if key in values), None)
        if natural_key:
            found = db.session.scalar(select(model.id).where(getattr(model, natural_key) == values[natural_key]))
            if found is not None:
                raise SeedConflict(f"Reserved demo identifier already exists in {model.__tablename__}; no demo data was committed.")
        row = model(**values, **synthetic)
        db.session.add(row)
        db.session.flush()
        return row

    officers = [add(Officer, username=f"demo-officer-{i}", display_name=f"Fictional Officer {i}",
                    password_hash=generate_password_hash(secrets.token_urlsafe(48)), is_active=False)
                for i in range(1, 4)]
    wards = []
    areas = []
    locations = []
    ward_names = ("Aster", "Birch", "Cedar", "Dune", "Ember")
    for i, name in enumerate(ward_names):
        wards.append(add(Ward, code=f"NILA-DEMO-W{i + 1}", name=f"Demo {name} Ward",
                         locality="Nila Fictional Demonstration Region",
                         public_notes="Synthetic planning fixture, placed offshore. No real locality or radiation survey is represented."))
        # Coordinates are offshore in the South Pacific, not on real households.
        west = -140 + i * 0.04
        south = -50
        ring = [[west, south], [west + .03, south], [west + .03, south + .03], [west, south + .03], [west, south]]
        area = add(SurveyArea, code=f"NILA-DEMO-AREA-{i + 1}", name=f"Fictional {name} survey area",
                   geometry={"type": "Polygon", "coordinates": [ring]},
                   geological_context="Fictional geological context for demonstrating records; no actual geology has been sampled.",
                   source="Nila synthetic fixture v1", observed_on=anchor - timedelta(days=60), review_status="unreviewed")
        areas.append(area)
        # Leave Ember without any survey measurement or indoor measurement.
        if i < 4:
            location = add(SurveyLocation, code=f"NILA-DEMO-POINT-{i + 1}", area_id=area.id,
                           latitude=Decimal(str(south + .015)), longitude=Decimal(str(west + .015)),
                           notes="Synthetic offshore point. Not a building measurement.")
            locations.append(location)
            add(Measurement, record_key=f"NILA-DEMO-GAMMA-{i + 1}", survey_location_id=location.id,
                track="regional_radiation", measurement_type="ambient_gamma_dose_rate", unit="uSv/h",
                value=Decimal("0.08") + Decimal(i) * Decimal("0.03"), started_at=stamp - timedelta(days=60),
                ended_at=stamp - timedelta(days=60) + timedelta(minutes=5), duration_seconds=300,
                instrument="Fictional survey meter", source="Nila synthetic fixture v1",
                quality_status="unreviewed", record_status="submitted",
                notes="Synthetic short observation. No indoor radon inference or long-term exposure estimate.")

    rules = {}
    for track in ("indoor_radon", "regional_radiation"):
        rules[track] = add(ScreeningRuleVersion, key=f"NILA-DEMO-{track}-v1", track=track,
            label="Unvalidated demonstration planning rules v1", validation_status="unvalidated_demo",
            configuration={"version": 1, "purpose": "planning_demonstration_only", "scientific_thresholds": [],
                           "priority_source": "explicit synthetic fixture designation", "follow_up_first": True,
                           "equal_priority_order": ["longest_wait", "recorded_random_seed"]},
            source="Nila fictional fixture; not official policy", effective_from=anchor,
            applicability="Software planning demonstrations only. Requires qualified local policy review before any real assessment use.")

    buildings = []
    cases = []
    for i in range(1, 51):
        ward_index = (i - 1) // 10
        row_in_ward = (i - 1) % 10
        unknown = i % 7 == 0 or i > 45
        building_use = "unknown" if unknown else rng.choice(["school", "office", "residential", "community"])
        building = add(Building, code=f"NILA-DEMO-B{i:03}", name=demo_building_name(ward_names[ward_index], building_use, i),
            ward_id=wards[ward_index].id, address=f"Synthetic plot {i:03}; fictional offshore region",
            latitude=None if i > 48 else Decimal(str(-50 + .004 + (row_in_ward // 5) * .01)),
            longitude=None if i > 48 else Decimal(str(-140 + ward_index * .04 + .003 + (row_in_ward % 5) * .004)),
            building_use=building_use,
            construction_year=None if unknown else rng.randint(1960, 2020),
            occupied_floors=None if unknown else rng.randint(1, 4),
            ground_contact_rooms=None if unknown else rng.randint(0, 5),
            ventilation="unknown" if unknown else rng.choice(["natural", "mechanical", "mixed"]),
            approximate_occupancy=None if unknown else rng.randint(5, 150),
            hours_of_use_per_day=None if unknown else Decimal("8"),
            private_notes="SYNTHETIC OFFICER-ONLY NOTE. Must never appear in a public locality response.")
        buildings.append(building)
        if building.latitude is not None:
            add(BuildingSurveyContext, building_id=building.id, survey_area_id=areas[ward_index].id,
                association_method="synthetic_fixture", source="Nila authored fixture geometry",
                notes="Authored demo containment link, not the Phase 5 geographic association algorithm. Area evidence is context only.")
        equal = i <= 25
        follow_up = 31 <= i <= 35
        case = add(AssessmentCase, building_id=building.id, track="indoor_radon",
            priority_band="priority" if equal or follow_up else "unknown",
            rule_version_id=rules["indoor_radon"].id if equal or follow_up else None,
            evidence_status="screening_only" if equal else "insufficient_information",
            workflow_status="follow_up_pending" if follow_up else "awaiting_assessment",
            priority_reason=("Equal-priority synthetic cohort; no measured risk or safety conclusion." if equal else
                             "Synthetic required follow-up; qualified review remains pending." if follow_up else
                             "Insufficient information; no screening priority has been established."),
            evidence_snapshot={"synthetic": True, "measurement_ids": [], "missing": ["reviewed_indoor_measurement"],
                               "basis": "fixture_designation" if equal or follow_up else "unknown"},
            waiting_since=stamp - timedelta(days=30 if equal else rng.randint(2, 75)),
            required_by=stamp + timedelta(days=7) if equal else stamp - timedelta(days=2) if follow_up else None,
            follow_up_required=follow_up, waiting_allowed=None,
            responsible_officer_id=officers[0 if equal else (i % 3)].id,
            scheduling_status="waiting" if equal else "unscheduled",
            next_action="Officer review of capacity and common deadline." if equal else
                        "Arrange and review follow-up evidence." if follow_up else "Collect missing assessment information.")
        cases.append(case)
        if 26 <= i <= 40:
            incomplete = i == 40
            measurement = add(Measurement, record_key=f"NILA-DEMO-RADON-{i:03}", building_id=building.id,
                track="indoor_radon", measurement_type="indoor_radon_concentration", unit="Bq/m3",
                value=None if incomplete else Decimal(rng.randint(25, 240)),
                started_at=stamp - timedelta(days=10),
                ended_at=None if incomplete else stamp - timedelta(days=9),
                duration_seconds=None if incomplete else 86400,
                instrument=None if incomplete else "Fictional indoor detector",
                source="Nila synthetic fixture v1", record_status="incomplete" if incomplete else "submitted",
                quality_status="unreviewed", submitted_by_id=officers[1].id,
                notes="Synthetic 24-hour example, not an annual average. Values do not imply any risk category."
                      if not incomplete else "Synthetic incomplete record: value, end/duration and instrument are unknown.")
            case.evidence_snapshot = {"synthetic": True, "measurement_ids": [measurement.id],
                                     "missing": ["qualified_review", "representative_measurement_protocol"]}
            if incomplete:
                case.workflow_status = "incomplete_record"
            else:
                case.evidence_status = "measured"
                if not follow_up:
                    case.workflow_status = "awaiting_review"
            if i in (26, 27):
                measurement.quality_status = "accepted"
                add(MeasurementReview, measurement_id=measurement.id, reviewer_id=officers[1].id,
                    decision="accepted", rationale="Synthetic record-quality review only; no long-term exposure or safety conclusion.")

    # Regional cases remain separate from each building's indoor-radon case.
    for index in range(5):
        add(AssessmentCase, building_id=buildings[index * 10].id, track="regional_radiation",
            priority_band="unknown", evidence_status="insufficient_information",
            workflow_status="awaiting_assessment", priority_reason="Area context is available; no building-specific regional assessment.",
            evidence_snapshot={"survey_area_id": areas[index].id, "missing": ["building_specific_evidence"], "synthetic": True},
            waiting_since=stamp - timedelta(days=15), next_action="Officer review of regional context and measurement coverage.")

    campaign = add(Campaign, code="NILA-DEMO-25-10", name="Fictional equal-attention exercise: 25 buildings / 10 slots",
        starts_on=anchor, ends_on=anchor + timedelta(days=7), available_slots=10, track="indoor_radon",
        staff_slots=None, equipment_slots=None,
        queue_weights={"required_follow_up": 3, "priority_screening": 5, "coverage_gap": 2},
        notes="Unvalidated 3–5–2 example only. All 25 have equal priority, waiting time and a common deadline. "
              "Waiting permission is unknown. Nominal slots are not confirmed staff/equipment capacity. "
              "The capacity requirement cannot be met with 10 slots. Phase 6 must create an escalation when generating a plan.")
    for case in cases[:25]:
        add(CampaignCandidate, campaign_id=campaign.id, case_id=case.id)

    guidance = add(GuidanceEntry, code="NILA-DEMO-GUIDANCE-REVIEW", title="Arrange a qualified evidence review",
        track="indoor_radon", content="An officer reviews record completeness and determines what additional assessment evidence is needed.",
        source="Nila synthetic workflow example; no external mitigation prescription",
        applicability="Demonstration workflow only. No automatic mitigation or clinical advice.", review_status="unvalidated_demo")
    for i in range(30, 35):
        add(Action, code=f"NILA-DEMO-ACTION-{i + 1}", case_id=cases[i].id, guidance_entry_id=guidance.id,
            assigned_to_id=officers[1].id, description="Collect additional assessment evidence for qualified review.",
            due_at=stamp - timedelta(days=2), status="reported_complete" if i == 30 else "follow_up_pending",
            reported_complete_at=stamp - timedelta(days=3),
            completion_notes="Synthetic completion report. Follow-up reviewer has not confirmed an outcome.")

    for i in range(1, 4):
        equipment = add(Equipment, code=f"NILA-DEMO-DETECTOR-{i}", name=f"Fictional indoor detector {i}",
            track="indoor_radon", status="available", notes="Fictional resource; bookings govern availability over time.")
        if i == 1:
            add(EquipmentBooking, equipment_id=equipment.id, case_id=cases[25].id,
                starts_at=stamp - timedelta(days=2), ends_at=stamp + timedelta(days=14), status="in_use",
                notes="Synthetic multi-day assignment; this detector is not available tomorrow.")

    batch.manifest = {
        "batch": BATCH_KEY, "anchor_date": anchor.isoformat(), "random_seed": DEMO_SEED,
        "buildings": 50, "wards": 5, "assessment_cases": 55, "measurements": 19,
        "campaign": campaign.code, "equal_priority_demand": 25, "available_slots": 10,
        "minimum_capacity_shortfall": 15, "plans_generated": 0,
    }
    add(AuditEvent, actor_id=None, event_type="demo_seed", entity_type="seed_batch", entity_key=BATCH_KEY,
        reason="Created an explicitly synthetic demonstration dataset.", before=None, after=batch.manifest)
    db.session.flush()
    return True, batch.manifest


def demo_summary():
    campaign = db.session.scalar(select(Campaign).where(Campaign.code == "NILA-DEMO-25-10"))
    if campaign is None:
        raise SeedConflict("Demo campaign not found. Run seed-demo first.")
    demand = db.session.scalar(select(func.count()).select_from(CampaignCandidate).where(CampaignCandidate.campaign_id == campaign.id))
    return {
        "campaign": campaign.code, "total_demand": demand, "available_capacity": campaign.available_slots,
        "minimum_unmet_demand": max(0, demand - campaign.available_slots),
        "note": "Capacity arithmetic only; no plan generated, no buildings selected or priorities changed.",
    }
