"""Dashboard pages and tool detection API."""

from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, jsonify, render_template

from app.models import Scan, ScanStatus, db
from app.services.scan_manager import build_tool
from app.tools import TOOL_CLASSES

bp = Blueprint("dashboard", __name__)


def tool_overview() -> list[dict]:
    counts = dict(db.session.query(Scan.tool, db.func.count(Scan.id)).group_by(Scan.tool).all())
    overview = []
    for slug, tool_class in TOOL_CLASSES.items():
        tool = build_tool(slug)
        overview.append(
            {
                "slug": slug,
                "name": tool_class.name,
                "description": tool_class.description,
                "accent": tool_class.accent,
                "scan_count": counts.get(slug, 0),
                "status": asdict(tool.status()),
            }
        )
    return overview


def scan_stats() -> dict:
    counts = dict(db.session.query(Scan.status, db.func.count(Scan.id)).group_by(Scan.status).all())
    return {
        "active": counts.get(ScanStatus.RUNNING.value, 0) + counts.get(ScanStatus.QUEUED.value, 0),
        "completed": counts.get(ScanStatus.COMPLETED.value, 0),
        "failed": counts.get(ScanStatus.FAILED.value, 0),
        "stopped": counts.get(ScanStatus.STOPPED.value, 0),
        "saved": db.session.query(Scan).filter(Scan.saved.is_(True)).count(),
        "total": sum(counts.values()),
    }


@bp.route("/")
def index():
    recent = db.session.query(Scan).order_by(Scan.created_at.desc()).limit(8).all()
    return render_template(
        "dashboard.html",
        tools=tool_overview(),
        stats=scan_stats(),
        recent_scans=recent,
    )


@bp.route("/setup")
def setup():
    from app import SETUP_STATE

    return render_template("setup.html", setup=SETUP_STATE)


@bp.route("/api/tools")
def api_tools():
    return jsonify({"tools": tool_overview(), "stats": scan_stats()})


@bp.route("/api/tools/<slug>")
def api_tool(slug: str):
    tool = build_tool(slug)  # raises ToolError for unknown slugs
    return jsonify(
        {
            "slug": slug,
            "name": tool.name,
            "description": tool.description,
            "wordlist_categories": list(tool.wordlist_categories),
            "status": asdict(tool.status()),
        }
    )


@bp.route("/api/stats")
def api_stats():
    return jsonify(scan_stats())
