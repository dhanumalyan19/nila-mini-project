from datetime import timedelta
from functools import wraps
import hashlib
import hmac
import secrets

from flask import current_app, g, redirect, request, session, url_for
from sqlalchemy import case, select
from sqlalchemy.dialects.mysql import insert
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import LoginThrottle, Officer, OfficerSession
from ..models.common import utcnow

DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def auth_configured():
    return current_app.config["NILA_DATABASE_CONFIGURED"] and not current_app.config["NILA_EPHEMERAL_SECRET"]


def load_officer():
    g.officer = None
    g.officer_session = None
    token = session.get("officer_token")
    if not token:
        return
    if not auth_configured() or not isinstance(token, str):
        session.clear()
        return
    record = db.session.scalar(select(OfficerSession).where(
        OfficerSession.token_hash == token_digest(token), OfficerSession.revoked_at.is_(None),
        OfficerSession.expires_at > utcnow()))
    officer = db.session.get(Officer, record.officer_id) if record else None
    if officer and officer.is_active and not officer.is_synthetic:
        g.officer = officer
        g.officer_session = record
    else:
        session.clear()


def login_required(view):
    @wraps(view)
    def protected(*args, **kwargs):
        if g.officer is None:
            # No user-supplied next URL: successful login always goes to the register.
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return protected


def consume_login_attempt():
    """Atomically limit login submissions per peer address across app processes."""
    now = utcnow()
    key = hmac.new(current_app.secret_key.encode(), (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()
    expired = LoginThrottle.started_at <= now - timedelta(minutes=10)
    query = insert(LoginThrottle).values(key=key, started_at=now, attempts=1)
    query = query.on_duplicate_key_update([
        ("attempts", case((expired, 1), else_=LoginThrottle.attempts + 1)),
        ("started_at", case((expired, now), else_=LoginThrottle.started_at)),
    ])
    db.session.execute(query)
    record = db.session.get(LoginThrottle, key, populate_existing=True)
    allowed = record.attempts <= 20
    db.session.commit()
    return allowed

