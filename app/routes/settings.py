"""Settings page."""

from __future__ import annotations

from dataclasses import asdict

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models import Setting, db
from app.services.scan_manager import build_tool
from app.tools import ToolError

bp = Blueprint("settings", __name__, url_prefix="/settings")

EDITABLE = {
    "theme": {"choices": {"dark", "midnight", "matrix"}},
    "max_concurrent_scans": {"int": (1, 20)},
    "default_timeout": {"int": (1, 3600)},
    "auto_save_results": {"choices": {"true", "false"}},
    "ffuf_binary": {"text": 200},
    "katana_binary": {"text": 200},
}


def _validate(key: str, value: str) -> str:
    rule = EDITABLE[key]
    value = (value or "").strip()
    if "choices" in rule:
        if value not in rule["choices"]:
            raise ToolError(f"Invalid value for {key}.")
        return value
    if "int" in rule:
        minimum, maximum = rule["int"]
        try:
            number = int(value)
        except ValueError as exc:
            raise ToolError(f"{key} must be a whole number.") from exc
        if not minimum <= number <= maximum:
            raise ToolError(f"{key} must be between {minimum} and {maximum}.")
        return str(number)
    if not value:
        raise ToolError(f"{key} cannot be empty.")
    return value[: rule["text"]]


@bp.route("/", methods=["GET"])
def index():
    return render_template(
        "settings.html",
        settings=Setting.as_dict(),
        tool_status={slug: asdict(build_tool(slug).status()) for slug in ("ffuf", "katana")},
        paths={
            "instance": str(current_app.config["INSTANCE_DIR"]),
            "scans": str(current_app.config["SCAN_DIR"]),
            "ffuf_wordlists": str(current_app.config["FFUF_WORDLIST_DIR"]),
            "katana_wordlists": str(current_app.config["KATANA_WORDLIST_DIR"]),
        },
        max_upload_mb=current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
    )


@bp.route("/", methods=["POST"])
def update():
    for key in EDITABLE:
        if key in request.form:
            Setting.set(key, _validate(key, request.form[key]))
    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/detect", methods=["POST"])
def detect():
    statuses = {slug: asdict(build_tool(slug).status()) for slug in ("ffuf", "katana")}
    return jsonify(statuses)
