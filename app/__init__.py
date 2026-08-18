"""Application factory for the Web Security Toolkit."""

from __future__ import annotations

import atexit
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from app.models import Setting, db
from app.services.process_manager import process_manager
from app.services.wordlist_manager import WordlistError
from app.tools import ToolError

csrf = CSRFProtect()

SETUP_STATE: dict[str, object] = {}


def create_app(config_object: str | type = "config.Config") -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    db.init_app(app)
    csrf.init_app(app)
    process_manager._buffer_lines = app.config["CONSOLE_BUFFER_LINES"]

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_template_globals(app)

    with app.app_context():
        SETUP_STATE.update(first_run_setup(app))

    atexit.register(process_manager.stop_all)
    return app


def _register_blueprints(app: Flask) -> None:
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.ffuf import bp as ffuf_bp
    from app.routes.katana import bp as katana_bp
    from app.routes.scans import bp as scans_bp
    from app.routes.settings import bp as settings_bp
    from app.routes.wordlists import bp as wordlists_bp

    for blueprint in (
        dashboard_bp,
        ffuf_bp,
        katana_bp,
        scans_bp,
        wordlists_bp,
        settings_bp,
    ):
        app.register_blueprint(blueprint)


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == ("application/json")


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ToolError)
    @app.errorhandler(WordlistError)
    def handle_tool_error(error):
        payload = {"error": error.message, "hint": getattr(error, "hint", None)}
        if _wants_json():
            return jsonify(payload), 400
        return render_template("error.html", status=400, **payload), 400

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        payload = {
            "error": "Your session expired or the request was blocked by CSRF protection.",
            "hint": "Reload the page and try again.",
        }
        if _wants_json():
            return jsonify(payload), 400
        return render_template("error.html", status=400, **payload), 400

    @app.errorhandler(RequestEntityTooLarge)
    def handle_large_upload(error):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        payload = {
            "error": "The uploaded file is too large.",
            "hint": f"Maximum upload size is {limit} MB.",
        }
        if _wants_json():
            return jsonify(payload), 413
        return render_template("error.html", status=413, **payload), 413

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        payload = {"error": error.description, "hint": None}
        if _wants_json():
            return jsonify(payload), error.code or 500
        return (
            render_template("error.html", status=error.code, **payload),
            error.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        app.logger.exception("Unhandled error: %s", error)
        payload = {
            "error": "Something went wrong while handling the request.",
            "hint": "Check the application log for details.",
        }
        if _wants_json():
            return jsonify(payload), 500
        return render_template("error.html", status=500, **payload), 500


def _register_template_globals(app: Flask) -> None:
    from app.services.scan_manager import active_scan_count

    @app.context_processor
    def inject_globals():
        theme = Setting.get("theme", "dark")
        return {
            "current_year": datetime.now(timezone.utc).year,
            "theme": theme,
            "active_scans": active_scan_count(),
            "setup_state": SETUP_STATE,
        }

    @app.template_filter("datetime")
    def format_datetime(value):
        if not value:
            return "—"
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @app.template_filter("duration")
    def format_duration(seconds):
        if seconds is None:
            return "—"
        minutes, secs = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m {secs}s"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"


def first_run_setup(app: Flask) -> dict:
    """Create directories, initialise the database and detect the tools."""
    from app.services.scan_manager import build_tool, reconcile_orphans
    from app.services.wordlist_manager import get_wordlist_manager

    steps: list[dict] = []

    for label, key in (
        ("Instance directory", "INSTANCE_DIR"),
        ("Scan directory", "SCAN_DIR"),
    ):
        path = Path(app.config[key])
        path.mkdir(parents=True, exist_ok=True)
        steps.append({"label": label, "ok": path.is_dir(), "detail": str(path)})

    db.create_all()
    steps.append(
        {"label": "SQLite database", "ok": True, "detail": app.config["SQLALCHEMY_DATABASE_URI"]}
    )

    for key, value in app.config["DEFAULT_SETTINGS"].items():
        if db.session.get(Setting, key) is None:
            Setting.set(key, value)
    db.session.commit()

    for slug, label in (("ffuf", "ffuf wordlists"), ("katana", "Katana wordlists")):
        manager = get_wordlist_manager(slug)
        manager.ensure_dirs()
        steps.append({"label": label, "ok": manager.root.is_dir(), "detail": str(manager.root)})

    tools = []
    for slug in ("ffuf", "katana"):
        status = build_tool(slug).status()
        tools.append({"slug": slug, "status": status})
        steps.append(
            {
                "label": f"{slug} binary",
                "ok": status.installed,
                "detail": f"{status.path} ({status.version})" if status.installed else "not found",
            }
        )

    reconcile_orphans()
    return {"steps": steps, "tools": tools, "ready": all(step["ok"] for step in steps)}
