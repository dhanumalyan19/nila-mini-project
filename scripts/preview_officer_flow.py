"""Temporary local demonstration: real MySQL, fictional buildings, random login.

Uses a disposable database, never .env. Press Ctrl+C to stop. No real records.
"""

import argparse
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from flask_migrate import upgrade
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from app import create_app
from app.extensions import db
from app.models import Officer
from app.seed import seed_demo
from mysql_server import disposable_mysql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5012)
    args = parser.parse_args()
    with disposable_mysql() as settings:
        app = create_app(environ=settings)
        with app.app_context():
            upgrade()
            seed_demo()
            password = secrets.token_urlsafe(18)
            db.session.add(Officer(username="preview-officer", display_name="Preview Officer", password_hash=generate_password_hash(password), is_active=True))
            db.session.commit()
        try:
            with make_server("127.0.0.1", args.port, app) as server:
                print(f"FICTIONAL PREVIEW ONLY: http://127.0.0.1:{args.port}/auth/login", flush=True)
                print(f"Temporary officer: preview-officer\nTemporary password: {password}", flush=True)
                print("Press Ctrl+C to stop. Nothing here is your regular Nila database.", flush=True)
                server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    main()
