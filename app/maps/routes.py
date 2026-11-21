from collections import defaultdict

from flask import Blueprint, abort, jsonify, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..auth.security import login_required
from ..extensions import db
from ..geography import validate_geometry
from ..models import AssessmentCase, Building, BuildingSurveyContext, Measurement, SurveyArea, SurveyLocation
from ..models.common import TRACKS

bp = Blueprint("maps", __name__, url_prefix="/map")


def evidence(record):
    return {"track": record.track, "type": record.measurement_type, "value": str(record.value) if record.value is not None else "Unknown",
        "unit": record.unit, "source": record.source, "date": record.started_at.isoformat() + "Z" if record.started_at else "Unknown",
        "quality": record.quality_status, "status": record.record_status, "synthetic": record.is_synthetic}


def map_data():
    track = request.args.get("track", "indoor_radon")
    provenance = request.args.get("provenance", "all")
    if track not in TRACKS or provenance not in ("all", "synthetic", "real"):
        abort(404)
    buildings_query = select(Building).options(joinedload(Building.ward)).order_by(Building.code)
    areas_query = select(SurveyArea).order_by(SurveyArea.code)
    points_query = select(SurveyLocation).order_by(SurveyLocation.code)
    if provenance != "all":
        buildings_query = buildings_query.where(Building.is_synthetic == (provenance == "synthetic"))
        areas_query = areas_query.where(SurveyArea.is_synthetic == (provenance == "synthetic"))
        points_query = points_query.where(SurveyLocation.is_synthetic == (provenance == "synthetic"))
    buildings = list(db.session.scalars(buildings_query.limit(501)))
    areas = list(db.session.scalars(areas_query.limit(101)))
    points = list(db.session.scalars(points_query.limit(501)))
    truncated = len(buildings) > 500 or len(areas) > 100 or len(points) > 500
    buildings, areas = buildings[:500], areas[:100]
    points = points[:500]
    ids = [b.id for b in buildings]
    area_ids = [a.id for a in areas]
    cases = {c.building_id: c for c in db.session.scalars(select(AssessmentCase).where(AssessmentCase.building_id.in_(ids), AssessmentCase.track == track))}
    measurements = defaultdict(list)
    for m in db.session.scalars(select(Measurement).where(Measurement.building_id.in_(ids), Measurement.track == track).order_by(Measurement.started_at.desc())):
        measurements[m.building_id].append(m)
    links = defaultdict(list)
    for building_id, area in db.session.execute(select(BuildingSurveyContext.building_id, SurveyArea).join(SurveyArea).where(BuildingSurveyContext.building_id.in_(ids))):
        links[building_id].append({"code": area.code, "source": area.source, "date": area.observed_on.isoformat(), "status": area.review_status, "synthetic": area.is_synthetic})
    survey = defaultdict(list)
    point_evidence = defaultdict(list)
    for measurement in db.session.scalars(select(Measurement).where(Measurement.survey_location_id.in_([p.id for p in points])).order_by(Measurement.started_at.desc())):
        point_evidence[measurement.survey_location_id].append(evidence(measurement))
    for area_id, measurement in db.session.execute(select(SurveyLocation.area_id, Measurement).join(Measurement, Measurement.survey_location_id == SurveyLocation.id).where(SurveyLocation.area_id.in_(area_ids)).order_by(Measurement.started_at.desc())):
        survey[area_id].append(evidence(measurement))
    result = []
    for b in buildings:
        c, records = cases.get(b.id), measurements[b.id]
        reviewed = any(m.value is not None and m.record_status == "submitted" and m.quality_status == "accepted" for m in records)
        missing = [label for field, label in (("latitude", "Coordinates"), ("construction_year", "Construction year"), ("approximate_occupancy", "Occupancy"), ("ground_contact_rooms", "Ground-contact rooms")) if getattr(b, field) is None]
        if b.ventilation == "unknown":
            missing.append("Ventilation")
        if not reviewed:
            missing.append("Reviewed, submitted building measurement in this track")
        result.append({"id": b.id, "code": b.code, "name": b.name, "ward": b.ward.name, "synthetic": b.is_synthetic,
            "latitude": float(b.latitude) if b.latitude is not None else None, "longitude": float(b.longitude) if b.longitude is not None else None,
            "priority": c.priority_band if c else "unknown", "reason": c.priority_reason if c else "Not assessed.",
            "next_action": c.next_action if c else "Assign an officer to assess the available evidence.",
            "workflow": c.workflow_status if c else "awaiting_assessment", "missing": missing, "coverage_gap": not reviewed,
            "evidence": [evidence(m) for m in records], "contexts": links[b.id], "url": url_for("buildings.detail", building_id=b.id)})
    area_data = []
    for area in areas:
        try:
            validate_geometry(area.geometry)
            geometry = area.geometry
        except ValueError:
            geometry = None
        area_data.append({"code": area.code, "name": area.name, "geometry": geometry, "context": area.geological_context,
            "source": area.source, "date": area.observed_on.isoformat(), "quality": area.review_status, "synthetic": area.is_synthetic, "evidence": survey[area.id]})
    point_data = [{"code": p.code, "latitude": float(p.latitude), "longitude": float(p.longitude), "synthetic": p.is_synthetic,
                   "evidence": point_evidence[p.id]} for p in points]
    return {"track": track, "provenance": provenance, "buildings": result, "areas": area_data, "points": point_data, "truncated": truncated,
        "unmapped": sum(b["latitude"] is None for b in result), "gaps": sum(b["coverage_gap"] for b in result),
        "synthetic": any(b["synthetic"] for b in result) or any(a["synthetic"] for a in area_data) or any(p["synthetic"] for p in point_data)}


@bp.get("/")
@login_required
def index():
    data = map_data()
    return render_template("maps/index.html", data=data)


@bp.get("/data")
@login_required
def data():
    return jsonify(map_data())
