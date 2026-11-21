from ..extensions import db
from .common import Record


class OfficerSession(Record, db.Model):
    __tablename__ = "officer_sessions"
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    officer_id = db.Column(db.Integer, db.ForeignKey("officers.id"), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)


class LoginThrottle(db.Model):
    __tablename__ = "login_throttles"
    key = db.Column(db.String(64), primary_key=True)
    started_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False)

