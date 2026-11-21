from ..extensions import db
from .common import Record, choice


class ImportBatch(Record, db.Model):
    """Owner-bound preview. No private upload content is stored in cookies."""
    __tablename__ = "import_batches"
    officer_id = db.Column(db.Integer, db.ForeignKey("officers.id"), nullable=False, index=True)
    kind = db.Column(db.String(24), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="preview")
    payload = db.Column(db.JSON, nullable=False)
    result = db.Column(db.JSON)
    __table_args__ = (
        choice("kind", ("measurements", "locations", "areas"), "kind_values"),
        choice("status", ("preview", "committed"), "status_values"),
    )
