"""Public pages expose curated locality aggregates, never private records."""
from datetime import datetime, timedelta
import secrets

from flask import Blueprint, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..auth.security import login_required
from ..models import AuditEvent, Building, Measurement, PublicRequest, SurveyArea, SurveyLocation, Ward
from ..models.common import utcnow
from .forms import PublicRequestForm

bp = Blueprint("public", __name__, url_prefix="/public")


@bp.get("/")
def index():
    return localities()


@bp.get("/localities")
def localities():
    query = request.args.get("q", "").strip()[:160]
    wards = list(db.session.scalars(select(Ward).where(Ward.locality.ilike(f"%{query}%")) if query else select(Ward).order_by(Ward.locality, Ward.name)))
    localities = sorted({ward.locality for ward in wards})
    coverage = []
    if query and wards:
        for ward in wards:
            building_count = db.session.scalar(select(func.count(Building.id)).where(Building.ward_id == ward.id)) or 0
            reviewed_count = db.session.scalar(select(func.count(func.distinct(Measurement.building_id))).join(Building, Building.id == Measurement.building_id).where(Building.ward_id == ward.id, Measurement.track == "indoor_radon", Measurement.record_status == "submitted", Measurement.quality_status == "accepted")) or 0
            coverage.append({"locality": ward.locality, "ward": ward.name, "reviewed": int(reviewed_count), "buildings": int(building_count), "synthetic": ward.is_synthetic})
    areas = []
    if query and wards:
        area_rows = list(db.session.scalars(select(SurveyArea).where(SurveyArea.name.ilike(f"%{query}%"))))
        if not area_rows:
            area_rows = list(db.session.scalars(select(SurveyArea).order_by(SurveyArea.name)))
        area_ids = [area.id for area in area_rows]
        counts = dict(db.session.execute(select(SurveyLocation.area_id, func.count(Measurement.id)).join(Measurement, Measurement.survey_location_id == SurveyLocation.id).where(SurveyLocation.area_id.in_(area_ids), Measurement.track == "regional_radiation", Measurement.record_status == "submitted").group_by(SurveyLocation.area_id)).all()) if area_ids else {}
        for area in area_rows:
            count = int(counts.get(area.id, 0))
            areas.append({"name": area.name, "observed_on": area.observed_on, "source": area.source,
                "coverage": "Measured regional observations available" if count else "No measured regional observations available",
                "measurement_count": count,
                "limitations": "Regional observations provide context only. They are not measurements taken inside a home and are not converted into indoor radon."})
    return render_template("public/localities.html", query=query, localities=localities, areas=areas, coverage=coverage)


@bp.route("/requests/new", methods=["GET", "POST"])
def request_new():
    form = PublicRequestForm()
    if form.validate_on_submit():
        if form.website.data:
            return redirect(url_for("public.request_received"))
        last = session.get("public_request_submitted_at")
        if last:
            try:
                if utcnow() - datetime.fromisoformat(last) < timedelta(minutes=5):
                    form.request_text.errors.append("Please wait a few minutes before sending another request.")
            except ValueError:
                session.pop("public_request_submitted_at", None)
        if not form.request_text.errors:
            reference = f"NILA-REQ-{secrets.token_hex(6).upper()}"
            row = PublicRequest(reference=reference, locality=form.locality.data, contact=form.contact.data or None,
                request_text=form.request_text.data, status="submitted", is_synthetic=False)
            db.session.add(row)
            db.session.flush()
            db.session.add(AuditEvent(actor_id=None, event_type="public_request_submitted", entity_type="public_request",
                entity_key=str(row.id), reason="Public assessment request received.", after={"reference": reference, "locality": row.locality}, is_synthetic=False))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.request_text.errors.append("The request could not be recorded. Please submit again.")
            else:
                session["public_request_submitted_at"] = utcnow().isoformat()
                session["public_request_reference"] = reference
                return redirect(url_for("public.request_received"))
    return render_template("public/request_form.html", form=form), 400 if form.is_submitted() else 200


@bp.get("/requests/received")
def request_received():
    reference = session.pop("public_request_reference", None)
    return render_template("public/request_received.html", reference=reference)


@bp.get("/requests")
@login_required
def requests():
    records = list(db.session.scalars(select(PublicRequest).order_by(PublicRequest.created_at.desc(), PublicRequest.id.desc()).limit(100)))
    return render_template("public/requests.html", records=records)
