from datetime import timedelta
from pathlib import Path

from flask import Blueprint, abort, flash, g, redirect, render_template, send_file, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..auth.security import login_required
from ..config import PROJECT_ROOT
from ..extensions import db
from ..geography import associate_building
from ..models import AuditEvent, Building, ImportBatch, Measurement, MeasurementKind, SurveyArea, SurveyLocation
from ..models.common import utcnow
from .forms import CommitForm, UploadForm
from .validation import parse_upload, validate_rows

bp = Blueprint("imports", __name__, url_prefix="/imports")
SAMPLES = {"measurements": "measurements.csv", "invalid-measurements": "measurements-with-errors.csv", "locations": "survey-locations.csv", "areas": "survey-areas.geojson"}


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = UploadForm()
    if form.validate_on_submit():
        active = db.session.scalar(select(func.count()).select_from(ImportBatch).where(ImportBatch.officer_id == g.officer.id, ImportBatch.status == "preview", ImportBatch.expires_at > utcnow()))
        if active >= 20:
            form.upload.errors.append("You have 20 active previews. Commit one or wait until a preview expires (30 minutes).")
        else:
            try:
                rows = parse_upload(form.kind.data, form.upload.data.read())
                report, _ = validate_rows(form.kind.data, rows)
            except ValueError as error:
                form.upload.errors.append(str(error))
            else:
                batch = ImportBatch(officer_id=g.officer.id, kind=form.kind.data, expires_at=utcnow() + timedelta(minutes=30), payload=report)
                db.session.add(batch)
                db.session.commit()
                return redirect(url_for("imports.preview", batch_id=batch.id))
    history = db.session.scalars(select(ImportBatch).where(ImportBatch.officer_id == g.officer.id).order_by(ImportBatch.id.desc()).limit(10))
    return render_template("imports/index.html", form=form, history=history,
        catalogue=list(db.session.scalars(select(MeasurementKind)))), 400 if form.is_submitted() else 200


def owned_batch(batch_id, lock=False):
    query = select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.officer_id == g.officer.id)
    if lock:
        query = query.with_for_update()
    batch = db.session.scalar(query)
    if batch is None:
        abort(404)
    return batch


@bp.get("/<int:batch_id>")
@login_required
def preview(batch_id):
    batch = owned_batch(batch_id)
    return render_preview(batch, CommitForm())


def render_preview(batch, form, message=None, status=200):
    valid = sum(not row["error"] for row in batch.payload)
    expired = batch.expires_at <= utcnow()
    return render_template("imports/preview.html", batch=batch, form=form, valid=valid, expired=expired, message=message), status


@bp.post("/<int:batch_id>/commit")
@login_required
def commit(batch_id):
    batch = owned_batch(batch_id, lock=True)
    form = CommitForm()
    if batch.status != "preview":
        return render_preview(batch, form, "This preview was already committed. Nothing was imported again.", 409)
    if batch.expires_at <= utcnow():
        return render_preview(batch, form, "This preview expired. Upload the file again to recheck current records.", 409)
    if not form.validate_on_submit():
        return render_preview(batch, form, "Check the confirmation and reason below.", 400)
    # The browser sends only confirmation/reason; accepted content stays in MySQL.
    accepted = [(row["row"], row["raw"]) for row in batch.payload if not row["error"]]
    if not accepted:
        return render_preview(batch, form, "No valid records to import. Correct the file and upload it again.", 400)
    report, objects = validate_rows(batch.kind, accepted)
    if any(row["error"] for row in report):
        return render_preview(batch, form, "Records changed since this preview (for example a duplicate was imported). Nothing was saved. Upload again for current row-specific errors.", 409)
    model = {"measurements": Measurement, "locations": SurveyLocation, "areas": SurveyArea}[batch.kind]
    records = [model(**values) for values in objects]
    for record in records:
        if batch.kind == "measurements":
            record.submitted_by_id = g.officer.id
        db.session.add(record)
    try:
        db.session.flush()
        associations = 0
        if batch.kind == "areas":
            # Serialize changes to existing buildings during area association.
            for building in db.session.scalars(select(Building).order_by(Building.id).with_for_update()):
                associations += associate_building(building, records)
        result = {"created": [{"id": r.id, "key": getattr(r, "record_key", None) or r.code} for r in records],
                  "count": len(records), "skipped": len(batch.payload) - len(records), "associations": associations}
        batch.status, batch.result = "committed", result
        db.session.add(AuditEvent(actor_id=g.officer.id, event_type="import_committed", entity_type="import_batch", entity_key=str(batch.id),
            reason=form.reason.data, after={"kind": batch.kind, **result}, is_synthetic=all(r.is_synthetic for r in records)))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return render_preview(owned_batch(batch_id), form, "A conflicting record was saved during this import. Nothing from this batch was saved. Upload again to recheck duplicates.", 409)
    flash(f"Saved {len(records)} records. Priority, assessment decisions and measurement review status were not changed.", "success")
    return redirect(url_for("imports.preview", batch_id=batch.id))


@bp.get("/samples/<sample>")
@login_required
def sample(sample):
    filename = SAMPLES.get(sample)
    if not filename:
        abort(404)
    return send_file(Path(PROJECT_ROOT) / "samples" / filename, as_attachment=True, download_name=filename)
