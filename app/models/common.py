"""Shared storage conventions: UTC timestamps and explicit synthetic provenance."""

from datetime import datetime, timezone

from ..extensions import db


def utcnow():
    # MySQL DATETIME has no timezone; every stored datetime is UTC without tzinfo.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Record:
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class Synthetic:
    is_synthetic = db.Column(db.Boolean, nullable=False, default=False)
    seed_batch_id = db.Column(db.Integer, db.ForeignKey("seed_batches.id"), nullable=True)


def choice(column, values, name):
    literals = ", ".join(repr(value) for value in values)
    return db.CheckConstraint(f"{column} IN ({literals})", name=name)


TRACKS = ("regional_radiation", "indoor_radon")
QUALITY = ("unreviewed", "accepted", "needs_information", "rejected")
WORKFLOW = (
    "awaiting_assessment", "measurement_submitted", "incomplete_record",
    "awaiting_review", "action_required", "action_assigned",
    "action_reported_complete", "follow_up_pending", "outcome_reviewed",
)


class SeedBatch(Record, db.Model):
    __tablename__ = "seed_batches"
    key = db.Column(db.String(80), nullable=False, unique=True)
    anchor_date = db.Column(db.Date, nullable=False)
    random_seed = db.Column(db.Integer, nullable=False)
    manifest = db.Column(db.JSON, nullable=False)


class Officer(Record, Synthetic, db.Model):
    __tablename__ = "officers"
    username = db.Column(db.String(80), nullable=False, unique=True)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    # Demo officers are disabled and receive hashes of unretained random secrets.


class AuditEvent(Record, Synthetic, db.Model):
    __tablename__ = "audit_events"
    actor_id = db.Column(db.Integer, db.ForeignKey("officers.id"))
    event_type = db.Column(db.String(64), nullable=False)
    entity_type = db.Column(db.String(64), nullable=False)
    entity_key = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    before = db.Column(db.JSON)
    after = db.Column(db.JSON)
    __table_args__ = (db.CheckConstraint("CHAR_LENGTH(TRIM(reason)) > 0", name="reason_required"),)

