from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth.security import login_required
from ..extensions import db
from ..models import AssessmentCase, AuditEvent, Campaign, CampaignCandidate, Equipment, EquipmentBooking, Escalation, OfficerOverride, PlanRun, PlanSelection
from .forms import BookingForm, CampaignForm, CandidateForm, GeneratePlanForm, OverrideForm
from .service import PlanningError, active_overlap, generate, planning_rule

bp = Blueprint("planner", __name__, url_prefix="/planner")


def campaign_or_404(campaign_id):
    return db.get_or_404(Campaign, campaign_id)


def choices_for_campaign(form, campaign):
    candidates = list(db.session.scalars(select(CampaignCandidate).where(CampaignCandidate.campaign_id == campaign.id)))
    member_ids = {candidate.case_id for candidate in candidates}
    cases = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.track == campaign.track,
        AssessmentCase.is_synthetic == campaign.is_synthetic).order_by(AssessmentCase.waiting_since, AssessmentCase.id)))
    available = [case for case in cases if case.id not in member_ids and case.workflow_status != "outcome_reviewed"]
    form.case_id.choices = [(case.id, f"Case {case.id} · {case.priority_band.replace('_', ' ')} · waiting since {case.waiting_since.date()} · building {case.building_id}") for case in available]
    return candidates, cases


@bp.get("/")
@login_required
def index():
    campaigns = list(db.session.scalars(select(Campaign).order_by(Campaign.starts_on.desc(), Campaign.id.desc())))
    latest = {campaign.id: db.session.scalar(select(PlanRun).where(PlanRun.campaign_id == campaign.id).order_by(PlanRun.id.desc())) for campaign in campaigns}
    return render_template("planner/index.html", campaigns=campaigns, latest=latest)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = CampaignForm()
    if form.validate_on_submit():
        campaign = Campaign(code=form.code.data, name=form.name.data, track=form.track.data, starts_on=form.starts_on.data,
            ends_on=form.ends_on.data, available_slots=form.available_slots.data, staff_slots=form.staff_slots.data,
            equipment_slots=form.equipment_slots.data,
            queue_weights={"required_follow_up": form.follow_up_weight.data, "priority_screening": form.priority_weight.data, "coverage_gap": form.coverage_weight.data},
            notes=form.notes.data, is_synthetic=False)
        db.session.add(campaign)
        try:
            db.session.flush()
            db.session.add(AuditEvent(actor_id=g.officer.id, event_type="campaign_created", entity_type="campaign", entity_key=str(campaign.id),
                reason=form.reason.data, after={"code": campaign.code, "track": campaign.track, "available_slots": campaign.available_slots,
                "queue_weights": campaign.queue_weights}, is_synthetic=False))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.code.errors.append("Could not create this campaign. The campaign ID may already exist.")
        else:
            flash("Campaign created. Add explicit eligible cases before generating a plan.", "success")
            return redirect(url_for("planner.detail", campaign_id=campaign.id))
    return render_template("planner/form.html", form=form), 400 if form.is_submitted() else 200


@bp.route("/<int:campaign_id>", methods=["GET", "POST"])
@login_required
def detail(campaign_id):
    campaign = campaign_or_404(campaign_id)
    form = CandidateForm()
    candidates, cases = choices_for_campaign(form, campaign)
    if form.validate_on_submit():
        case = db.session.get(AssessmentCase, form.case_id.data)
        if not case or case.track != campaign.track or case.is_synthetic != campaign.is_synthetic or case.workflow_status == "outcome_reviewed":
            form.case_id.errors.append("Choose a currently eligible case with the same track and data origin.")
        else:
            db.session.add(CampaignCandidate(campaign_id=campaign.id, case_id=case.id, is_synthetic=campaign.is_synthetic))
            try:
                db.session.flush()
                db.session.add(AuditEvent(actor_id=g.officer.id, event_type="campaign_candidate_added", entity_type="campaign", entity_key=str(campaign.id),
                    reason=form.reason.data, after={"case_id": case.id}, is_synthetic=campaign.is_synthetic))
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.case_id.errors.append("This case is already in the campaign. Reload the page and choose another case.")
            else:
                flash("Candidate added. Membership alone does not schedule or change its priority.", "success")
                return redirect(url_for("planner.detail", campaign_id=campaign.id))
    plans = list(db.session.scalars(select(PlanRun).where(PlanRun.campaign_id == campaign.id).order_by(PlanRun.id.desc())))
    return render_template("planner/detail.html", campaign=campaign, candidates=candidates, cases={case.id: case for case in cases},
        form=form, plans=plans), 400 if form.is_submitted() else 200


@bp.post("/<int:campaign_id>/generate")
@login_required
def generate_plan(campaign_id):
    campaign = campaign_or_404(campaign_id)
    form = GeneratePlanForm()
    if not form.validate_on_submit():
        flash("Supply a reason before generating a plan.", "errors")
        return redirect(url_for("planner.detail", campaign_id=campaign.id))
    try:
        plan, selected, unselected = generate(campaign.id, g.officer.id, form.reason.data, form.random_seed.data)
        db.session.add(AuditEvent(actor_id=g.officer.id, event_type="plan_generated", entity_type="plan_run", entity_key=str(plan.id),
            reason=form.reason.data, after={"campaign_id": campaign.id, "selected": len(selected), "unmet": len(unselected),
            "deadline_feasible": plan.deadline_feasible, "random_seed": plan.random_seed}, is_synthetic=plan.is_synthetic))
        db.session.commit()
    except PlanningError as error:
        db.session.rollback()
        flash(str(error), "errors")
        return redirect(url_for("planner.detail", campaign_id=campaign.id))
    flash(f"Plan {plan.id} generated: {plan.selected_count} selected and {plan.unmet_demand} still unmet. Priorities were not changed.", "success")
    return redirect(url_for("planner.plan", plan_id=plan.id))


@bp.get("/plans/<int:plan_id>")
@login_required
def plan(plan_id):
    plan = db.get_or_404(PlanRun, plan_id)
    campaign = campaign_or_404(plan.campaign_id)
    selections = list(db.session.scalars(select(PlanSelection).where(PlanSelection.plan_run_id == plan.id).order_by(PlanSelection.selection_order)))
    selection_ids = {selection.case_id for selection in selections}
    candidates = list(db.session.scalars(select(CampaignCandidate).where(CampaignCandidate.campaign_id == campaign.id)))
    case_ids = [candidate.case_id for candidate in candidates]
    cases = {case.id: case for case in db.session.scalars(select(AssessmentCase).where(AssessmentCase.id.in_(case_ids)))} if case_ids else {}
    unmet = sorted((case for case_id, case in cases.items() if case_id not in selection_ids), key=lambda item: item.waiting_since)
    override = OverrideForm()
    override.replacement_case_id.choices = [(case.id, f"Case {case.id} · {case.priority_band} · waiting since {case.waiting_since.date()}") for case in unmet]
    override.selection_order.choices = [(selection.selection_order, f"Position {selection.selection_order}: case {selection.case_id}") for selection in selections]
    escalations = list(db.session.scalars(select(Escalation).where(Escalation.plan_run_id == plan.id)))
    return render_template("planner/plan.html", plan=plan, campaign=campaign, selections=selections, cases=cases, unmet=unmet,
        override=override, escalations=escalations)


@bp.post("/plans/<int:plan_id>/override")
@login_required
def override(plan_id):
    plan = db.session.scalar(select(PlanRun).where(PlanRun.id == plan_id).with_for_update())
    if not plan:
        abort(404)
    campaign = campaign_or_404(plan.campaign_id)
    form = OverrideForm()
    selections = list(db.session.scalars(select(PlanSelection).where(PlanSelection.plan_run_id == plan.id).with_for_update().order_by(PlanSelection.selection_order)))
    selected_ids = {selection.case_id for selection in selections}
    candidates = list(db.session.scalars(select(CampaignCandidate).where(CampaignCandidate.campaign_id == campaign.id)))
    cases = {case.id: case for case in db.session.scalars(select(AssessmentCase).where(AssessmentCase.id.in_([row.case_id for row in candidates])).with_for_update())}
    form.replacement_case_id.choices = [(case.id, f"Case {case.id}") for case in cases.values() if case.id not in selected_ids]
    form.selection_order.choices = [(selection.selection_order, f"Position {selection.selection_order}: case {selection.case_id}") for selection in selections]
    if not form.validate_on_submit():
        flash("Choose a valid replacement, plan position, and reason.", "errors")
        return redirect(url_for("planner.plan", plan_id=plan.id))
    old = next((selection for selection in selections if selection.selection_order == form.selection_order.data), None)
    replacement = cases.get(form.replacement_case_id.data)
    if not old or not replacement or replacement.id in selected_ids or replacement.track != campaign.track or replacement.is_synthetic != campaign.is_synthetic:
        flash("The requested override is no longer valid. Reload and try again.", "errors")
        return redirect(url_for("planner.plan", plan_id=plan.id))
    rule, label = planning_rule(replacement)
    before = {"case_id": old.case_id, "category": old.category, "selection_order": old.selection_order}
    old_case = cases[old.case_id]
    old.case_id = replacement.id
    old.category = "required_follow_up" if replacement.follow_up_required else "priority_screening" if replacement.priority_band == "priority" else "coverage_gap"
    old.applicable_rule = label
    old.rule_version_id = rule.id
    old.evidence_used = {"override": True, "case": replacement.evidence_snapshot, "priority_reason": replacement.priority_reason}
    old.tie_break_reason = "Officer override; see linked override record and required reason."
    old_case.scheduling_status = "waiting"
    replacement.scheduling_status = "planned"
    db.session.add(OfficerOverride(plan_run_id=plan.id, case_id=replacement.id, officer_id=g.officer.id, reason=form.reason.data,
        before=before, after={"case_id": replacement.id, "category": old.category, "selection_order": old.selection_order}, is_synthetic=plan.is_synthetic))
    db.session.add(AuditEvent(actor_id=g.officer.id, event_type="plan_override", entity_type="plan_run", entity_key=str(plan.id),
        reason=form.reason.data, before=before, after={"case_id": replacement.id, "selection_order": old.selection_order}, is_synthetic=plan.is_synthetic))
    db.session.commit()
    flash("Officer override recorded. Capacity and screening priorities are unchanged.", "success")
    return redirect(url_for("planner.plan", plan_id=plan.id))


@bp.route("/equipment", methods=["GET", "POST"])
@login_required
def equipment():
    form = BookingForm()
    equipment_rows = list(db.session.scalars(select(Equipment).order_by(Equipment.code)))
    case_rows = list(db.session.scalars(select(AssessmentCase).where(AssessmentCase.workflow_status != "outcome_reviewed").order_by(AssessmentCase.id)))
    form.equipment_id.choices = [(row.id, f"{row.code} · {row.track.replace('_', ' ')} · {row.status.replace('_', ' ')}") for row in equipment_rows]
    form.case_id.choices = [(row.id, f"Case {row.id} · {row.track.replace('_', ' ')} · {row.priority_band}") for row in case_rows]
    if form.validate_on_submit():
        equipment_row = db.session.scalar(select(Equipment).where(Equipment.id == form.equipment_id.data).with_for_update())
        case = db.session.get(AssessmentCase, form.case_id.data)
        if not equipment_row or not case or equipment_row.status != "available" or equipment_row.track != case.track or equipment_row.is_synthetic != case.is_synthetic:
            form.equipment_id.errors.append("Choose available equipment with the same track and data origin as the case.")
        elif active_overlap(equipment_row.id, form.starts_at.data, form.ends_at.data):
            form.starts_at.errors.append("This equipment already has an active overlapping booking. Choose another time or resource.")
        else:
            booking = EquipmentBooking(equipment_id=equipment_row.id, case_id=case.id, starts_at=form.starts_at.data, ends_at=form.ends_at.data,
                status="reserved", notes=form.notes.data, is_synthetic=case.is_synthetic)
            db.session.add(booking)
            db.session.flush()
            db.session.add(AuditEvent(actor_id=g.officer.id, event_type="equipment_booked", entity_type="equipment_booking", entity_key=str(booking.id),
                reason=form.reason.data, after={"equipment_id": equipment_row.id, "case_id": case.id, "starts_at": booking.starts_at.isoformat(), "ends_at": booking.ends_at.isoformat()}, is_synthetic=booking.is_synthetic))
            db.session.commit()
            flash("Equipment reserved. Nila blocked overlapping active reservations for this resource.", "success")
            return redirect(url_for("planner.equipment"))
    bookings = list(db.session.execute(select(EquipmentBooking, Equipment, AssessmentCase).join(Equipment).join(AssessmentCase).order_by(EquipmentBooking.starts_at.desc())).all())
    return render_template("planner/equipment.html", form=form, bookings=bookings), 400 if form.is_submitted() else 200
