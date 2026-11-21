import secrets

from flask import Blueprint, current_app, flash, g, redirect, render_template, session, url_for
from sqlalchemy import select
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models import AuditEvent, Officer, OfficerSession
from ..models.common import utcnow
from .forms import LoginForm
from .security import DUMMY_HASH, auth_configured, consume_login_attempt, login_required, token_digest

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.officer:
        return redirect(url_for("buildings.index"))
    form = LoginForm()
    if not auth_configured():
        return render_template("auth/login.html", form=form, setup_needed=True), 503
    if form.validate_on_submit():
        if not consume_login_attempt():
            return render_template("auth/login.html", form=form, error="Too many sign-in attempts. Wait 10 minutes, then try again."), 429, {"Retry-After": "600"}
        officer = db.session.scalar(select(Officer).where(Officer.username == form.username.data))
        valid_password = check_password_hash(officer.password_hash if officer else DUMMY_HASH, form.password.data)
        if not valid_password or officer is None or not officer.is_active or officer.is_synthetic:
            return render_template("auth/login.html", form=form, error="Username or password is incorrect."), 401
        token = secrets.token_urlsafe(48)
        db.session.add(OfficerSession(token_hash=token_digest(token), officer_id=officer.id,
            expires_at=utcnow() + current_app.permanent_session_lifetime))
        db.session.add(AuditEvent(actor_id=officer.id, event_type="officer_login", entity_type="officer",
            entity_key=str(officer.id), reason="Officer signed in."))
        db.session.commit()
        session.clear()
        session["officer_token"] = token
        session.permanent = True
        return redirect(url_for("buildings.index"))
    return render_template("auth/login.html", form=form), 400 if form.is_submitted() else 200


@bp.post("/logout")
@login_required
def logout():
    g.officer_session.revoked_at = utcnow()
    db.session.add(AuditEvent(actor_id=g.officer.id, event_type="officer_logout", entity_type="officer",
        entity_key=str(g.officer.id), reason="Officer signed out; server session revoked."))
    db.session.commit()
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("auth.login"))

