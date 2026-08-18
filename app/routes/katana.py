"""Katana configuration page."""

from __future__ import annotations

from flask import Blueprint, render_template

from app.models import Scan, Setting, db
from app.services.scan_manager import build_tool
from app.services.wordlist_manager import get_wordlist_manager

bp = Blueprint("katana", __name__, url_prefix="/tools/katana")


@bp.route("/")
def index():
    tool = build_tool("katana")
    manager = get_wordlist_manager("katana")
    wordlists = [item.to_dict() for item in manager.list_all()]
    recent = (
        db.session.query(Scan)
        .filter(Scan.tool == "katana")
        .order_by(Scan.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "katana/index.html",
        tool=tool,
        status=tool.status(),
        wordlists=wordlists,
        categories=manager.list_categories(),
        last_wordlist=Setting.get("katana_last_wordlist", ""),
        default_wordlist=Setting.get("katana_default_wordlist", ""),
        default_timeout=Setting.get("default_timeout", "10"),
        recent_scans=recent,
    )
