"""Planner storage only. Allocation and booking services arrive in Phase 6."""

from ..extensions import db
from .common import TRACKS, WORKFLOW, Record, Synthetic, choice


class AssessmentCase(Record, Synthetic, db.Model):
    __tablename__ = "assessment_cases"
    building_id = db.Column(db.Integer, db.ForeignKey("buildings.id"), nullable=False)
    track = db.Column(db.String(24), nullable=False)
    priority_band = db.Column(db.String(24), nullable=False, default="unknown")
    evidence_status = db.Column(db.String(32), nullable=False, default="insufficient_information")
    workflow_status = db.Column(db.String(32), nullable=False, default="awaiting_assessment")
    rule_version_id = db.Column(db.Integer)
    priority_reason = db.Column(db.Text, nullable=False)
    evidence_snapshot = db.Column(db.JSON, nullable=False)
    waiting_since = db.Column(db.DateTime, nullable=False)
    required_by = db.Column(db.DateTime)
    follow_up_required = db.Column(db.Boolean, nullable=False, default=False)
    waiting_allowed = db.Column(db.Boolean)
    waiting_reviewed_by_id = db.Column(db.Integer, db.ForeignKey("officers.id"))
    waiting_review_reason = db.Column(db.Text)
    responsible_officer_id = db.Column(db.Integer, db.ForeignKey("officers.id"))
    scheduling_status = db.Column(db.String(24), nullable=False, default="unscheduled")
    next_action = db.Column(db.Text, nullable=False)
    building = db.relationship("Building")
    __table_args__ = (
        db.UniqueConstraint("building_id", "track"),
        db.ForeignKeyConstraint(["rule_version_id", "track"], ["screening_rule_versions.id", "screening_rule_versions.track"], name="fk_cases_rule_track"),
        choice("track", TRACKS, "track_values"),
        choice("priority_band", ("priority", "standard", "unknown"), "priority_values"),
        choice("evidence_status", ("measured", "screening_only", "insufficient_information"), "evidence_values"),
        choice("workflow_status", WORKFLOW, "workflow_values"),
        choice("scheduling_status", ("unscheduled", "planned", "booked", "waiting", "escalated", "completed"), "scheduling_values"),
        db.CheckConstraint("waiting_allowed IS NULL OR (waiting_reviewed_by_id IS NOT NULL AND waiting_review_reason IS NOT NULL AND CHAR_LENGTH(TRIM(waiting_review_reason)) > 0)", name="waiting_review_required"),
        db.CheckConstraint("priority_band = 'unknown' OR rule_version_id IS NOT NULL", name="priority_has_rule"),
    )


class Campaign(Record, Synthetic, db.Model):
    __tablename__ = "campaigns"
    code = db.Column(db.String(80), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date, nullable=False)
    available_slots = db.Column(db.Integer, nullable=False)
    track = db.Column(db.String(24), nullable=False)
    staff_slots = db.Column(db.Integer)
    equipment_slots = db.Column(db.Integer)
    queue_weights = db.Column(db.JSON, nullable=False)
    notes = db.Column(db.Text, nullable=False)
    __table_args__ = (
        choice("track", TRACKS, "track_values"),
        db.CheckConstraint("ends_on >= starts_on", name="date_order"),
        db.CheckConstraint("available_slots >= 0 AND staff_slots >= 0 AND equipment_slots >= 0", name="nonnegative_capacity"),
    )


class CampaignCandidate(Record, Synthetic, db.Model):
    """Explicit eligibility fixtures; membership does not mean selection."""
    __tablename__ = "campaign_candidates"
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey("assessment_cases.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("campaign_id", "case_id"),)


class PlanRun(Record, Synthetic, db.Model):
    __tablename__ = "plan_runs"
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    generated_by_id = db.Column(db.Integer, db.ForeignKey("officers.id"), nullable=False)
    random_seed = db.Column(db.BigInteger, nullable=False)
    algorithm_version = db.Column(db.String(64), nullable=False)
    input_snapshot = db.Column(db.JSON, nullable=False)
    rule_snapshot = db.Column(db.JSON, nullable=False)
    total_demand = db.Column(db.Integer, nullable=False)
    effective_capacity = db.Column(db.Integer, nullable=False)
    selected_count = db.Column(db.Integer, nullable=False)
    unmet_demand = db.Column(db.Integer, nullable=False)
    deadline_feasible = db.Column(db.Boolean)
    __table_args__ = (
        db.CheckConstraint("total_demand >= 0 AND effective_capacity >= 0 AND selected_count >= 0 AND unmet_demand >= 0", name="nonnegative_counts"),
        db.CheckConstraint("selected_count <= effective_capacity AND selected_count <= total_demand AND unmet_demand = total_demand - selected_count", name="capacity_arithmetic"),
    )


class PlanSelection(Record, Synthetic, db.Model):
    __tablename__ = "plan_selections"
    plan_run_id = db.Column(db.Integer, db.ForeignKey("plan_runs.id"), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey("assessment_cases.id"), nullable=False)
    category = db.Column(db.String(32), nullable=False)
    applicable_rule = db.Column(db.String(100), nullable=False)
    rule_version_id = db.Column(db.Integer, db.ForeignKey("screening_rule_versions.id"), nullable=False)
    evidence_used = db.Column(db.JSON, nullable=False)
    tie_break_reason = db.Column(db.Text, nullable=False)
    selection_order = db.Column(db.Integer, nullable=False)
    __table_args__ = (
        db.UniqueConstraint("plan_run_id", "case_id", name="uq_plan_selection_case"),
        db.UniqueConstraint("plan_run_id", "selection_order", name="uq_plan_selection_order"),
        choice("category", ("required_follow_up", "priority_screening", "coverage_gap"), "category_values"),
        db.CheckConstraint("selection_order > 0", name="positive_order"),
    )


class Equipment(Record, Synthetic, db.Model):
    __tablename__ = "equipment"
    code = db.Column(db.String(60), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    track = db.Column(db.String(24), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="out_of_service")
    notes = db.Column(db.Text, nullable=False)
    __table_args__ = (
        choice("track", TRACKS, "track_values"),
        choice("status", ("available", "out_of_service", "maintenance"), "status_values"),
    )


class EquipmentBooking(Record, Synthetic, db.Model):
    __tablename__ = "equipment_bookings"
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey("assessment_cases.id"), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(24), nullable=False)
    notes = db.Column(db.Text, nullable=False)
    __table_args__ = (
        db.CheckConstraint("ends_at > starts_at", name="time_order"),
        choice("status", ("reserved", "in_use", "returned", "cancelled"), "status_values"),
        db.Index("ix_bookings_equipment_interval", "equipment_id", "starts_at", "ends_at"),
    )


class Escalation(Record, Synthetic, db.Model):
    __tablename__ = "escalations"
    plan_run_id = db.Column(db.Integer, db.ForeignKey("plan_runs.id"), nullable=False)
    responsible_officer_id = db.Column(db.Integer, db.ForeignKey("officers.id"))
    reason = db.Column(db.Text, nullable=False)
    affected_case_ids = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="open")
    review_notes = db.Column(db.Text)
    __table_args__ = (choice("status", ("open", "under_review", "closed"), "status_values"),)


class OfficerOverride(Record, Synthetic, db.Model):
    __tablename__ = "officer_overrides"
    plan_run_id = db.Column(db.Integer, db.ForeignKey("plan_runs.id"), nullable=False)
    case_id = db.Column(db.Integer, db.ForeignKey("assessment_cases.id"), nullable=False)
    officer_id = db.Column(db.Integer, db.ForeignKey("officers.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    before = db.Column(db.JSON, nullable=False)
    after = db.Column(db.JSON, nullable=False)
    __table_args__ = (db.CheckConstraint("CHAR_LENGTH(TRIM(reason)) > 0", name="reason_required"),)
