from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError

from .config import PROJECT_ROOT, build_config
from .extensions import csrf, db, migrate


def create_app(test_config=None, *, environ=None, load_env=True):
    app = Flask(__name__, instance_path=str(PROJECT_ROOT / "instance"))
    app.config.from_mapping(build_config(environ, load_env=load_env))
    if test_config:
        app.config.update(test_config)

    # Without credentials, serve the foundation page without any database engine.
    # No SQLite fallback, schema creation, or attempted login happens at startup.
    if app.config["NILA_DATABASE_CONFIGURED"]:
        db.init_app(app)
    from . import models  # Register metadata before commands/migrations use it.
    migrate.init_app(app, db, directory=str(PROJECT_ROOT / "migrations"), render_as_batch=False)
    csrf.init_app(app)

    from .main.routes import bp
    from .cli import register_commands
    from .auth.routes import bp as auth_bp
    from .auth.security import load_officer
    from .buildings.routes import bp as buildings_bp
    from .imports.routes import bp as imports_bp
    from .maps.routes import bp as maps_bp
    from .planner.routes import bp as planner_bp
    from .workflow.routes import bp as workflow_bp
    from .public.routes import bp as public_bp

    app.register_blueprint(bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(buildings_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(maps_bp)
    app.register_blueprint(planner_bp)
    app.register_blueprint(workflow_bp)
    app.register_blueprint(public_bp)
    app.before_request(load_officer)
    register_commands(app)

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.warning("Database operation failed; private error details suppressed.")
        return render_template("error.html", title="Database unavailable", message="The database could not complete this request. Check the connection and apply pending migrations, then retry."), 503

    @app.template_filter("known")
    def known(value):
        return "Unknown" if value is None or value == "" else value

    @app.template_filter("label")
    def label(value):
        return value.replace("_", " ").capitalize() if value else "Unknown"

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; img-src 'self' data:; "
            "script-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        if request.endpoint == "maps.index":
            response.headers["Content-Security-Policy"] = response.headers["Content-Security-Policy"].replace("img-src 'self' data:;", "img-src 'self' data: https://tile.openstreetmap.org;")
            # Optional browser tile requests carry only this site's origin.
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template("error.html", title="Form could not be submitted", message="Your form token is missing or expired. Reload the page and try again."), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", title="Page not found", message="This address is unavailable. Return to the Nila start page."), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template("error.html", title="Request too large", message="The request exceeds the current 2 MB limit. Reduce its size and try again."), 413

    if app.config["NILA_EPHEMERAL_SECRET"]:
        app.logger.warning("NILA_SECRET_KEY is unset. Using a temporary development key; sessions will reset when the app restarts.")
    if not app.config["NILA_DATABASE_CONFIGURED"]:
        app.logger.warning("MySQL is not configured. The foundation page works; run flask --app app db-check for setup guidance.")
    return app
