"""ffuf configuration page."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from app.models import Scan, Setting, db
from app.services.scan_manager import build_tool
from app.services.wordlist_manager import get_wordlist_manager
from app.tools.ffuf import FfufTool

bp = Blueprint("ffuf", __name__, url_prefix="/tools/ffuf")


@bp.route("/")
def index():
    tool = build_tool("ffuf")
    manager = get_wordlist_manager("ffuf")
    wordlists = [item.to_dict() for item in manager.list_all()]
    recent = (
        db.session.query(Scan)
        .filter(Scan.tool == "ffuf")
        .order_by(Scan.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "ffuf/index.html",
        tool=tool,
        status=tool.status(),
        wordlists=wordlists,
        categories=manager.list_categories(),
        presets=FfufTool.PRESETS,
        last_wordlist=Setting.get("ffuf_last_wordlist", ""),
        default_wordlist=Setting.get("ffuf_default_wordlist", ""),
        default_timeout=Setting.get("default_timeout", "10"),
        recent_scans=recent,
    )


@bp.route("/presets")
def presets():
    return jsonify(
        {
            key: {"label": value["label"], "config": value["config"]}
            for key, value in FfufTool.PRESETS.items()
        }
    )
