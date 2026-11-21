from ..extensions import db
from .common import QUALITY, TRACKS, Record, Synthetic, choice


class MeasurementKind(db.Model):
    """The composite key binds the scientific track, measured quantity and unit."""
    __tablename__ = "measurement_kinds"
    track = db.Column(db.String(24), primary_key=True)
    measurement_type = db.Column(db.String(40), primary_key=True)
    unit = db.Column(db.String(16), primary_key=True)
    description = db.Column(db.String(255), nullable=False)
    __table_args__ = (choice("track", TRACKS, "track_values"),)


class Measurement(Record, Synthetic, db.Model):
    __tablename__ = "measurements"
    record_key = db.Column(db.String(100), nullable=False, unique=True)
    # Later import code can compute a canonical content hash for duplicate detection.
    deduplication_hash = db.Column(db.String(64), unique=True)
    building_id = db.Column(db.Integer, db.ForeignKey("buildings.id"), index=True)
    survey_location_id = db.Column(db.Integer, db.ForeignKey("survey_locations.id"), index=True)
    track = db.Column(db.String(24), nullable=False)
    measurement_type = db.Column(db.String(40), nullable=False)
    unit = db.Column(db.String(16), nullable=False)
    value = db.Column(db.Numeric(14, 6))
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)
    instrument = db.Column(db.String(160))
    source = db.Column(db.String(255), nullable=False)
    quality_status = db.Column(db.String(24), nullable=False, default="unreviewed")
    record_status = db.Column(db.String(24), nullable=False, default="incomplete")
    notes = db.Column(db.Text, nullable=False)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("officers.id"))
    __table_args__ = (
        db.ForeignKeyConstraint(["track", "measurement_type", "unit"], ["measurement_kinds.track", "measurement_kinds.measurement_type", "measurement_kinds.unit"], name="fk_measurements_kind"),
        db.CheckConstraint("(building_id IS NOT NULL AND survey_location_id IS NULL) OR (building_id IS NULL AND survey_location_id IS NOT NULL)", name="exactly_one_location"),
        db.CheckConstraint("track <> 'indoor_radon' OR building_id IS NOT NULL", name="radon_is_indoor"),
        db.CheckConstraint("value >= 0", name="nonnegative_value"),
        db.CheckConstraint("duration_seconds > 0", name="positive_duration"),
        db.CheckConstraint("ended_at IS NULL OR (started_at IS NOT NULL AND ended_at >= started_at)", name="time_order"),
        db.CheckConstraint("record_status = 'incomplete' OR (value IS NOT NULL AND started_at IS NOT NULL AND (ended_at IS NOT NULL OR duration_seconds IS NOT NULL) AND instrument IS NOT NULL AND CHAR_LENGTH(TRIM(instrument)) > 0)", name="submitted_fields"),
        db.CheckConstraint("started_at IS NULL OR ended_at IS NULL OR duration_seconds IS NULL OR TIMESTAMPDIFF(SECOND, started_at, ended_at) = duration_seconds", name="duration_consistent"),
        choice("record_status", ("incomplete", "submitted"), "record_status_values"),
        choice("quality_status", QUALITY, "quality_values"),
    )


class MeasurementReview(Record, Synthetic, db.Model):
    __tablename__ = "measurement_reviews"
    measurement_id = db.Column(db.Integer, db.ForeignKey("measurements.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("officers.id"), nullable=False)
    decision = db.Column(db.String(24), nullable=False)
    rationale = db.Column(db.Text, nullable=False)
    # Quality acceptance is not a health assessment or an exposure-duration claim.
    __table_args__ = (
        choice("decision", QUALITY[1:], "decision_values"),
        db.CheckConstraint("CHAR_LENGTH(TRIM(rationale)) > 0", name="rationale_required"),
    )


class ScreeningRuleVersion(Record, Synthetic, db.Model):
    __tablename__ = "screening_rule_versions"
    key = db.Column(db.String(80), nullable=False, unique=True)
    track = db.Column(db.String(24), nullable=False)
    label = db.Column(db.String(160), nullable=False)
    validation_status = db.Column(db.String(32), nullable=False)
    configuration = db.Column(db.JSON, nullable=False)
    source = db.Column(db.String(255), nullable=False)
    applicability = db.Column(db.Text, nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    __table_args__ = (
        db.UniqueConstraint("id", "track", name="uq_rule_version_track"),
        choice("track", TRACKS, "track_values"),
        choice("validation_status", ("unvalidated_demo", "pending_review", "locally_approved", "retired"), "validation_values"),
    )

