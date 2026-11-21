"""Storage for later action/review and public workflows; no routes yet."""

from ..extensions import db
from .common import TRACKS, Record, Synthetic, choice


class GuidanceEntry(Record, Synthetic, db.Model):
    __tablename__ = "guidance_entries"
    code = db.Column(db.String(80), nullable=False, unique=True)
    title = db.Column(db.String(160), nullable=False)
    track = db.Column(db.String(24), nullable=False)
    content = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(255), nullable=False)
    applicability = db.Column(db.Text, nullable=False)
    review_status = db.Column(db.String(32), nullable=False)
    __table_args__ = (
        choice("track", TRACKS, "track_values"),
        choice("review_status", ("unvalidated_demo", "pending_review", "locally_approved", "retired"), "review_values"),
    )


class Action(Record, Synthetic, db.Model):
    __tablename__ = "actions"
    code = db.Column(db.String(80), nullable=False, unique=True)
    case_id = db.Column(db.Integer, db.ForeignKey("assessment_cases.id"), nullable=False)
    guidance_entry_id = db.Column(db.Integer, db.ForeignKey("guidance_entries.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("officers.id"))
    description = db.Column(db.Text, nullable=False)
    due_at = db.Column(db.DateTime)
    status = db.Column(db.String(32), nullable=False, default="assigned")
    reported_complete_at = db.Column(db.DateTime)
    completion_notes = db.Column(db.Text)
    __table_args__ = (
        choice("status", ("assigned", "reported_complete", "follow_up_pending", "outcome_reviewed"), "status_values"),
    )


class FollowUpReview(Record, Synthetic, db.Model):
    __tablename__ = "follow_up_reviews"
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), nullable=False)
    measurement_id = db.Column(db.Integer, db.ForeignKey("measurements.id"))
    reviewer_id = db.Column(db.Integer, db.ForeignKey("officers.id"), nullable=False)
    evidence_notes = db.Column(db.Text, nullable=False)
    decision = db.Column(db.String(32), nullable=False)
    rationale = db.Column(db.Text, nullable=False)
    __table_args__ = (
        choice("decision", ("more_evidence_needed", "further_action_required", "outcome_reviewed"), "decision_values"),
        db.CheckConstraint("CHAR_LENGTH(TRIM(evidence_notes)) > 0 AND CHAR_LENGTH(TRIM(rationale)) > 0", name="review_evidence_required"),
    )


class PublicRequest(Record, Synthetic, db.Model):
    __tablename__ = "public_requests"
    reference = db.Column(db.String(80), nullable=False, unique=True)
    locality = db.Column(db.String(160), nullable=False)
    contact = db.Column(db.String(255))
    request_text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="submitted")
    # Private intake table; later public pages must use a curated aggregate query.
    __table_args__ = (choice("status", ("submitted", "under_review", "assigned", "closed"), "status_values"),)

