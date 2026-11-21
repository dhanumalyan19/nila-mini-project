from flask import Blueprint, g, jsonify, redirect, render_template, url_for

from ..database import check_database

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    if g.officer:
        return redirect(url_for("buildings.index"))
    return render_template("main/index.html")


@bp.get("/health/live")
def live():
    """Liveness means Flask responds; it does not mean MySQL is ready."""
    return jsonify(application="nila", status="ok", phase=8)


@bp.get("/health/ready")
def ready():
    """Only a generic status is public; terminal diagnostics offer recovery steps."""
    status = check_database()
    return jsonify(database=status.state, scope="connection_only"), 200 if status.connected else 503
