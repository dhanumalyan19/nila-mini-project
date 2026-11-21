from decimal import Decimal

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from ..auth.security import login_required
from ..extensions import db
from ..geography import associate_building
from ..models import AssessmentCase, AuditEvent, Building, BuildingSurveyContext, Measurement, Officer, ScreeningRuleVersion, SurveyArea, SurveyLocation, Ward
from ..models.common import TRACKS, utcnow
from .forms import AssignmentForm, BuildingForm

bp = Blueprint("buildings", __name__, url_prefix="/buildings")
FIELDS = ("code", "name", "ward_id", "address", "latitude", "longitude", "building_use", "construction_year",
          "occupied_floors", "ground_contact_rooms", "ventilation", "approximate_occupancy", "hours_of_use_per_day", "private_notes")


def snapshot(building):
    return {key: str(value) if isinstance(value := getattr(building, key), Decimal) else value for key in (*FIELDS, "is_synthetic", "version_id")}


def ward_choices(form):
    form.ward_id.choices = [(w.id, w.name + (" · synthetic" if w.is_synthetic else "")) for w in db.session.scalars(select(Ward).order_by(Ward.name))]


@bp.get("/")
@login_required
def index():
    q = request.args.get("q", "").strip()[:160]
    ward_id = request.args.get("ward", type=int)
    query = select(Building).options(joinedload(Building.ward)).order_by(Building.code)
    if q:
        query = query.where(or_(Building.code.contains(q, autoescape=True), Building.name.contains(q, autoescape=True), Building.address.contains(q, autoescape=True)))
    if ward_id:
        query = query.where(Building.ward_id == ward_id)
    page = db.paginate(query, page=max(1, request.args.get("page", 1, type=int)), per_page=20, error_out=False)
    return render_template("buildings/index.html", page=page, q=q, ward_id=ward_id,
        wards=list(db.session.scalars(select(Ward).order_by(Ward.name))))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    return save_building()


@bp.route("/<int:building_id>/edit", methods=["GET", "POST"])
@login_required
def edit(building_id):
    return save_building(db.get_or_404(Building, building_id))


def save_building(building=None):
    editing = building is not None
    form = BuildingForm(obj=building)
    ward_choices(form)
    if form.validate_on_submit():
        ward = db.session.get(Ward, form.ward_id.data)
        if ward.is_synthetic and not form.is_synthetic.data:
            form.is_synthetic.errors.append("A real building cannot be registered in a fictional ward. Select a real ward or mark this record synthetic.")
        elif building and form.is_synthetic.data != building.is_synthetic:
            form.is_synthetic.errors.append("Synthetic provenance cannot be changed after creation.")
        elif building and form.version_id.data != building.version_id:
            return render_template("buildings/form.html", form=form, building=building, conflict=True), 409
        else:
            before = snapshot(building) if building else None
            created = building is None
            building = building or Building(is_synthetic=form.is_synthetic.data)
            changed_location = not created and any(getattr(building, field) != getattr(form, field).data for field in ("latitude", "longitude"))
            for key in FIELDS:
                value = getattr(form, key).data
                setattr(building, key, None if value == "" else value)
            db.session.add(building)
            try:
                db.session.flush()
                if created:
                    for track in TRACKS:
                        db.session.add(AssessmentCase(building_id=building.id, track=track, priority_band="unknown",
                            evidence_status="insufficient_information", workflow_status="awaiting_assessment",
                            priority_reason="New record; screening has not been performed.",
                            evidence_snapshot={"missing": ["assessment", "reviewed_measurements"]},
                            waiting_since=utcnow(), responsible_officer_id=g.officer.id,
                            next_action="Collect assessment information and review the applicable evidence.", is_synthetic=building.is_synthetic))
                if changed_location:
                    # Remove stale context associations only; retain survey measurements.
                    links = list(db.session.scalars(select(BuildingSurveyContext).where(BuildingSurveyContext.building_id == building.id)))
                    for link in links:
                        db.session.delete(link)
                    if links:
                        flash("Coordinates changed. Previous survey context links were removed; matching polygon contexts were recalculated. Survey measurements were retained.", "notice")
                if created or changed_location:
                    db.session.flush()
                    associate_building(building)
                db.session.add(AuditEvent(actor_id=g.officer.id, event_type="building_created" if created else "building_updated",
                    entity_type="building", entity_key=str(building.id), reason=form.change_reason.data,
                    before=before, after=snapshot(building), is_synthetic=building.is_synthetic))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.code.errors.append("Could not save this record. The building ID may already exist; check the entered values.")
            except StaleDataError:
                db.session.rollback()
                return render_template("buildings/form.html", form=form, building=building, conflict=True), 409
            else:
                flash("Building registered." if created else "Building changes saved.", "success")
                return redirect(url_for("buildings.detail", building_id=building.id))
    return render_template("buildings/form.html", form=form, building=building if editing else None), 400 if form.is_submitted() else 200


@bp.get("/<int:building_id>")
@login_required
def detail(building_id):
    building = db.get_or_404(Building, building_id)
    cases = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.building_id == building.id).order_by(AssessmentCase.track)))
    measurements = list(db.session.scalars(select(Measurement).where(Measurement.building_id == building.id).order_by(Measurement.track, Measurement.started_at.desc())))
    links = db.session.execute(select(BuildingSurveyContext, SurveyArea).join(SurveyArea).where(BuildingSurveyContext.building_id == building.id)).all()
    area_ids = [area.id for _, area in links]
    survey_measurements = list(db.session.scalars(select(Measurement).join(SurveyLocation).where(SurveyLocation.area_id.in_(area_ids)).order_by(Measurement.started_at.desc()))) if area_ids else []
    officers = {o.id: o for o in db.session.scalars(select(Officer))}
    forms = {}
    for case in cases:
        form = AssignmentForm(data={"responsible_officer_id": case.responsible_officer_id or 0, "next_action": case.next_action})
        form.responsible_officer_id.choices = [(0, "Unassigned")] + [(o.id, o.display_name + (" · inactive" if not o.is_active else "")) for o in officers.values() if o.is_active or o.id == case.responsible_officer_id]
        forms[case.track] = form
    rules = {r.id: r for r in db.session.scalars(select(ScreeningRuleVersion))}
    audits = list(db.session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "building", AuditEvent.entity_key == str(building.id)).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(10)))
    missing = [label for key, label in (("construction_year", "Construction year"), ("occupied_floors", "Occupied floors"), ("ground_contact_rooms", "Ground-contact rooms"), ("approximate_occupancy", "Occupancy"), ("hours_of_use_per_day", "Hours of use"), ("latitude", "Coordinates")) if getattr(building, key) is None]
    if building.ventilation == "unknown":
        missing.append("Ventilation")
    return render_template("buildings/detail.html", building=building, cases=cases, measurements=measurements,
        links=links, survey_measurements=survey_measurements, officers=officers, forms=forms, rules=rules, audits=audits, missing=missing)


@bp.post("/<int:building_id>/assignment/<track>")
@login_required
def assignment(building_id, track):
    if track not in TRACKS:
        abort(404)
    building = db.get_or_404(Building, building_id)
    case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.building_id == building.id, AssessmentCase.track == track).with_for_update())
    if not case:
        abort(404)
    form = AssignmentForm()
    officers = db.session.scalars(select(Officer).where(or_(Officer.is_active.is_(True), Officer.id == case.responsible_officer_id)))
    form.responsible_officer_id.choices = [(0, "Unassigned")] + [(o.id, o.display_name) for o in officers]
    if not form.validate_on_submit():
        return render_template("error.html", title="Assignment could not be saved", message="Choose a valid officer and supply both the next action and a reason. Return to the building and try again."), 400
    before = {"track": track, "responsible_officer_id": case.responsible_officer_id, "next_action": case.next_action}
    case.responsible_officer_id = form.responsible_officer_id.data or None
    case.next_action = form.next_action.data
    db.session.add(AuditEvent(actor_id=g.officer.id, event_type="assignment_updated", entity_type="building", entity_key=str(building.id),
        reason=form.reason.data, before=before, after={"track": track, "responsible_officer_id": case.responsible_officer_id, "next_action": case.next_action}, is_synthetic=building.is_synthetic))
    db.session.commit()
    flash("Assignment updated. Screening priority and review status are unchanged.", "success")
    return redirect(url_for("buildings.detail", building_id=building.id))
