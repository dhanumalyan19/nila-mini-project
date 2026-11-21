"""Private, auditable workflow transitions. No action is a safety conclusion."""
from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth.security import login_required
from ..extensions import db
from ..models import Action, AssessmentCase, AuditEvent, Building, FollowUpReview, GuidanceEntry, Measurement, MeasurementKind, MeasurementReview, Officer, PublicRequest
from ..models.common import utcnow
from .forms import ActionForm, CompletionForm, FollowUpForm, MeasurementEntryForm, MeasurementReviewForm

bp = Blueprint("workflow", __name__, url_prefix="/workflow")


def case_for_measurement(measurement):
    return db.session.scalar(select(AssessmentCase).where(
        AssessmentCase.building_id == measurement.building_id, AssessmentCase.track == measurement.track).with_for_update())


def record_audit(event_type, entity_type, entity_key, reason, before=None, after=None, *, synthetic=False):
    db.session.add(AuditEvent(actor_id=g.officer.id, event_type=event_type, entity_type=entity_type,
        entity_key=str(entity_key), reason=reason, before=before, after=after, is_synthetic=synthetic))


def measurement_choices(form):
    buildings = list(db.session.scalars(select(Building).order_by(Building.code)))
    kinds = list(db.session.scalars(select(MeasurementKind).order_by(MeasurementKind.track, MeasurementKind.measurement_type, MeasurementKind.unit)))
    form.building_id.choices = [(row.id, f"{row.code} · {row.name}{' · synthetic' if row.is_synthetic else ''}") for row in buildings]
    form.kind.choices = [(f"{row.track}|{row.measurement_type}|{row.unit}", f"{row.track.replace('_', ' ')} · {row.measurement_type.replace('_', ' ')} · {row.unit}") for row in kinds]
    return buildings, kinds


@bp.get("/")
@login_required
def index():
    measurements = list(db.session.scalars(select(Measurement).order_by(Measurement.created_at.desc(), Measurement.id.desc()).limit(60)))
    actions = list(db.session.scalars(select(Action).order_by(Action.created_at.desc(), Action.id.desc()).limit(60)))
    public_requests = list(db.session.scalars(select(PublicRequest).order_by(PublicRequest.created_at.desc(), PublicRequest.id.desc()).limit(40)))
    guidance = list(db.session.scalars(select(GuidanceEntry).order_by(GuidanceEntry.track, GuidanceEntry.code)))
    cases = {case.id: case for case in db.session.scalars(select(AssessmentCase))}
    cases_by_building_track = {(case.building_id, case.track): case for case in cases.values()}
    officers = {officer.id: officer for officer in db.session.scalars(select(Officer))}
    return render_template("workflow/index.html", measurements=measurements, actions=actions, guidance=guidance, cases=cases,
        cases_by_building_track=cases_by_building_track, officers=officers, public_requests=public_requests)


@bp.post("/requests/<int:request_id>/status")
@login_required
def public_request_status(request_id):
    row = db.session.scalar(select(PublicRequest).where(PublicRequest.id == request_id).with_for_update())
    if not row:
        abort(404)
    from .forms import RequestStatusForm
    form = RequestStatusForm()
    if not form.validate_on_submit():
        flash("Choose a status and provide a reason for the request update.", "errors")
        return redirect(url_for("workflow.index"))
    before = {"status": row.status}
    row.status = form.status.data
    record_audit("public_request_status_updated", "public_request", row.id, form.reason.data, before=before, after={"status": row.status})
    db.session.commit()
    flash("Public request status updated. Contact details remain private.", "success")
    return redirect(url_for("workflow.index"))


@bp.route("/measurements/new", methods=["GET", "POST"])
@login_required
def measurement_new():
    form = MeasurementEntryForm()
    buildings, kinds = measurement_choices(form)
    kind_map = {f"{row.track}|{row.measurement_type}|{row.unit}": row for row in kinds}
    if form.validate_on_submit():
        building = db.session.get(Building, form.building_id.data)
        kind = kind_map.get(form.kind.data)
        case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.building_id == form.building_id.data, AssessmentCase.track == (kind.track if kind else None)).with_for_update()) if kind else None
        if not building or not kind or not case:
            form.kind.errors.append("Choose an existing building and a supported measurement kind.")
        elif case.workflow_status == "outcome_reviewed":
            form.kind.errors.append("This assessment outcome is already reviewed. Start a new assessment cycle before adding further evidence.")
        else:
            duration = int((form.ended_at.data - form.started_at.data).total_seconds())
            measurement = Measurement(record_key=form.record_key.data, building_id=building.id, track=kind.track,
                measurement_type=kind.measurement_type, unit=kind.unit, value=form.value.data,
                started_at=form.started_at.data, ended_at=form.ended_at.data, duration_seconds=duration,
                instrument=form.instrument.data, source=form.source.data, notes=form.notes.data,
                record_status="submitted", quality_status="unreviewed", submitted_by_id=g.officer.id,
                is_synthetic=building.is_synthetic)
            before = {"workflow_status": case.workflow_status, "evidence_status": case.evidence_status, "next_action": case.next_action}
            case.evidence_status, case.workflow_status = "measured", "awaiting_review"
            case.next_action = "Qualified officer review of the submitted measurement record."
            db.session.add(measurement)
            try:
                db.session.flush()
                record_audit("measurement_submitted", "measurement", measurement.id, form.reason.data, before=None,
                    after={"record_key": measurement.record_key, "building_id": building.id, "track": measurement.track, "unit": measurement.unit, "workflow_before": before, "workflow_after": case.workflow_status}, synthetic=measurement.is_synthetic)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.record_key.errors.append("Could not save this measurement. That record ID may already exist.")
            else:
                flash("Measurement submitted for record-quality review. It has not created an action or safety conclusion.", "success")
                return redirect(url_for("workflow.index"))
    return render_template("workflow/measurement_form.html", form=form), 400 if form.is_submitted() else 200


@bp.post("/measurements/<int:measurement_id>/review")
@login_required
def measurement_review(measurement_id):
    measurement = db.session.scalar(select(Measurement).where(Measurement.id == measurement_id).with_for_update())
    if not measurement:
        abort(404)
    form = MeasurementReviewForm()
    if not form.validate_on_submit():
        flash("Choose a record-quality decision and explain it before saving.", "errors")
        return redirect(url_for("workflow.index"))
    if measurement.record_status != "submitted" or measurement.building_id is None:
        flash("Only a complete building measurement can receive this review. Complete the record first.", "errors")
        return redirect(url_for("workflow.index"))
    case = case_for_measurement(measurement)
    if not case:
        abort(409)
    before = {"quality_status": measurement.quality_status, "workflow_status": case.workflow_status, "next_action": case.next_action}
    measurement.quality_status = form.decision.data
    if form.decision.data == "accepted":
        case.workflow_status = "action_required"
        case.next_action = "Qualified officer to decide whether any action is appropriate; no mitigation is prescribed automatically."
    else:
        case.workflow_status = "awaiting_assessment"
        case.next_action = "Collect or correct assessment information, then submit it for review."
    review = MeasurementReview(measurement_id=measurement.id, reviewer_id=g.officer.id, decision=form.decision.data,
        rationale=form.rationale.data, is_synthetic=measurement.is_synthetic)
    db.session.add(review)
    db.session.flush()
    record_audit("measurement_reviewed", "measurement", measurement.id, form.rationale.data, before=before,
        after={"quality_status": measurement.quality_status, "workflow_status": case.workflow_status}, synthetic=measurement.is_synthetic)
    db.session.commit()
    flash("Record-quality review saved. This review does not prescribe an action or certify an outcome.", "success")
    return redirect(url_for("workflow.index"))


def action_choices(form):
    eligible = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.workflow_status == "action_required").order_by(AssessmentCase.id)))
    guidance = list(db.session.scalars(select(GuidanceEntry).where(GuidanceEntry.review_status != "retired").order_by(GuidanceEntry.code)))
    officers = list(db.session.scalars(select(Officer).where(Officer.is_active.is_(True)).order_by(Officer.display_name)))
    form.case_id.choices = [(row.id, f"Case {row.id} · {row.track.replace('_', ' ')} · building {row.building_id}") for row in eligible]
    form.guidance_entry_id.choices = [(0, "No guidance reference selected")] + [(row.id, f"{row.code} · {row.review_status.replace('_', ' ')}") for row in guidance]
    form.assigned_to_id.choices = [(row.id, row.display_name) for row in officers]
    return {row.id: row for row in eligible}, {row.id: row for row in guidance}, {row.id: row for row in officers}


@bp.route("/actions/new", methods=["GET", "POST"])
@login_required
def action_new():
    form = ActionForm()
    cases, guidance, officers = action_choices(form)
    if form.validate_on_submit():
        case = db.session.scalar(select(AssessmentCase).where(AssessmentCase.id == form.case_id.data).with_for_update())
        entry = guidance.get(form.guidance_entry_id.data)
        officer = officers.get(form.assigned_to_id.data)
        if not case or case.workflow_status != "action_required" or not officer or (entry and (entry.track != case.track or entry.is_synthetic != case.is_synthetic)):
            form.case_id.errors.append("Choose an action-required case, matching guidance, and active responsible officer.")
        else:
            action = Action(code=f"NILA-ACTION-{utcnow().strftime('%Y%m%d%H%M%S%f')}", case_id=case.id,
                guidance_entry_id=entry.id if entry else None, assigned_to_id=officer.id, description=form.description.data,
                due_at=form.due_at.data, status="assigned", is_synthetic=case.is_synthetic)
            before = {"workflow_status": case.workflow_status, "next_action": case.next_action}
            case.workflow_status, case.next_action = "action_assigned", "Track the assigned action and obtain follow-up evidence after any reported completion."
            db.session.add(action)
            db.session.flush()
            record_audit("action_assigned", "action", action.id, form.reason.data, before=before,
                after={"case_id": case.id, "guidance_entry_id": action.guidance_entry_id, "assigned_to_id": action.assigned_to_id, "workflow_status": case.workflow_status}, synthetic=action.is_synthetic)
            db.session.commit()
            flash("Action assigned. Guidance is a reference, not an automatic prescription.", "success")
            return redirect(url_for("workflow.index"))
    return render_template("workflow/action_form.html", form=form), 400 if form.is_submitted() else 200


@bp.post("/actions/<int:action_id>/complete")
@login_required
def action_complete(action_id):
    action = db.session.scalar(select(Action).where(Action.id == action_id).with_for_update())
    if not action:
        abort(404)
    form = CompletionForm()
    if not form.validate_on_submit() or action.status != "assigned":
        flash("Only an assigned action can be reported complete; include details and a reason.", "errors")
        return redirect(url_for("workflow.index"))
    case = db.session.get(AssessmentCase, action.case_id)
    before = {"action_status": action.status, "workflow_status": case.workflow_status}
    action.status, action.reported_complete_at, action.completion_notes = "reported_complete", utcnow(), form.completion_notes.data
    case.workflow_status, case.next_action = "action_reported_complete", "Obtain follow-up evidence and record a separate reviewer decision."
    record_audit("action_reported_complete", "action", action.id, form.reason.data, before=before,
        after={"action_status": action.status, "workflow_status": case.workflow_status}, synthetic=action.is_synthetic)
    db.session.commit()
    flash("Completion was reported. It does not establish that the concern is resolved.", "success")
    return redirect(url_for("workflow.follow_up", action_id=action.id))


@bp.route("/actions/<int:action_id>/follow-up", methods=["GET", "POST"])
@login_required
def follow_up(action_id):
    action = db.get_or_404(Action, action_id)
    case = db.get_or_404(AssessmentCase, action.case_id)
    form = FollowUpForm()
    records = list(db.session.scalars(select(Measurement).where(Measurement.building_id == case.building_id, Measurement.track == case.track,
        Measurement.record_status == "submitted").order_by(Measurement.started_at.desc())))
    form.measurement_id.choices = [(row.id, f"{row.record_key} · {row.value} {row.unit} · {row.quality_status.replace('_', ' ')}") for row in records]
    if form.validate_on_submit():
        if action.status not in ("reported_complete", "follow_up_pending"):
            form.measurement_id.errors.append("Report the action complete before recording follow-up evidence.")
        else:
            measurement = next((row for row in records if row.id == form.measurement_id.data), None)
            if not measurement or measurement.is_synthetic != action.is_synthetic:
                form.measurement_id.errors.append("Choose matching follow-up measurement evidence.")
            else:
                before = {"action_status": action.status, "workflow_status": case.workflow_status}
                review = FollowUpReview(action_id=action.id, measurement_id=measurement.id, reviewer_id=g.officer.id,
                    evidence_notes=form.evidence_notes.data, decision=form.decision.data, rationale=form.rationale.data,
                    is_synthetic=action.is_synthetic)
                action.status = "outcome_reviewed" if form.decision.data == "outcome_reviewed" else "follow_up_pending"
                case.workflow_status = "outcome_reviewed" if form.decision.data == "outcome_reviewed" else "follow_up_pending"
                case.follow_up_required = form.decision.data != "outcome_reviewed"
                case.next_action = "Outcome recorded by qualified reviewer." if form.decision.data == "outcome_reviewed" else "Arrange additional evidence or further action as documented by the reviewer."
                db.session.add(review)
                db.session.flush()
                record_audit("follow_up_reviewed", "follow_up_review", review.id, form.rationale.data, before=before,
                    after={"action_status": action.status, "workflow_status": case.workflow_status, "decision": review.decision, "measurement_id": measurement.id}, synthetic=action.is_synthetic)
                db.session.commit()
                flash("Follow-up evidence and reviewer decision recorded separately from the completion report.", "success")
                return redirect(url_for("workflow.index"))
    return render_template("workflow/follow_up_form.html", action=action, case=case, form=form), 400 if form.is_submitted() else 200


@bp.get("/audit")
@login_required
def audit():
    events = list(db.session.scalars(select(AuditEvent).where(AuditEvent.event_type.in_(("measurement_submitted", "measurement_reviewed", "action_assigned", "action_reported_complete", "follow_up_reviewed"))).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(100)))
    officers = {officer.id: officer for officer in db.session.scalars(select(Officer))}
    return render_template("workflow/audit.html", events=events, officers=officers)
