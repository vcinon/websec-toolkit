"""Scan pages, scan control API and the live output stream."""

from __future__ import annotations

import json

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

from app.models import Scan, ScanStatus, db
from app.services import parser
from app.services.process_manager import process_manager
from app.services.scan_manager import (
    delete_scan,
    pause_scan,
    prepare,
    restart_scan,
    resume_scan,
    start_scan,
    stop_scan,
)
from app.tools import TOOL_CLASSES, ToolError

bp = Blueprint("scans", __name__)


def get_scan_or_404(scan_id: int) -> Scan:
    scan = db.session.get(Scan, scan_id)
    if scan is None:
        raise ToolError(f"Scan {scan_id} does not exist.")
    return scan


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ToolError("Expected a JSON request body.")
    return data


def _require_tool(slug: str) -> str:
    if slug not in TOOL_CLASSES:
        raise ToolError(f"Unknown tool: {slug}")
    return slug


# -- pages ------------------------------------------------------------
@bp.route("/scans")
def active():
    scans = (
        db.session.query(Scan)
        .filter(Scan.status.in_([ScanStatus.RUNNING.value, ScanStatus.QUEUED.value]))
        .order_by(Scan.created_at.desc())
        .all()
    )
    return render_template("scans/active.html", scans=scans)


@bp.route("/scans/history")
def history():
    tool = request.args.get("tool", "")
    status = request.args.get("status", "")
    query = db.session.query(Scan)
    if tool in TOOL_CLASSES:
        query = query.filter(Scan.tool == tool)
    if status in {item.value for item in ScanStatus}:
        query = query.filter(Scan.status == status)
    scans = query.order_by(Scan.created_at.desc()).limit(500).all()
    return render_template(
        "scans/history.html",
        scans=scans,
        tools=list(TOOL_CLASSES),
        statuses=[item.value for item in ScanStatus],
        selected_tool=tool,
        selected_status=status,
    )


@bp.route("/scans/<int:scan_id>")
def detail(scan_id: int):
    scan = get_scan_or_404(scan_id)
    results = parser.load_results(scan)
    return render_template(
        "scans/detail.html",
        scan=scan,
        results=results,
        columns=parser.COLUMNS.get(scan.tool, []),
        raw_output=parser.read_raw_output(scan),
        is_running=scan.status == ScanStatus.RUNNING.value,
    )


# -- API --------------------------------------------------------------
@bp.route("/api/scans", methods=["GET"])
def api_list():
    query = db.session.query(Scan)
    tool = request.args.get("tool")
    status = request.args.get("status")
    if tool:
        query = query.filter(Scan.tool == tool)
    if status:
        query = query.filter(Scan.status == status)
    limit = min(int(request.args.get("limit", 100)), 500)
    scans = query.order_by(Scan.created_at.desc()).limit(limit).all()
    return jsonify({"scans": [scan.to_dict(include_config=False) for scan in scans]})


@bp.route("/api/scans", methods=["POST"])
def api_create():
    data = _json_body()
    slug = _require_tool(str(data.get("tool", "")))
    config = data.get("config")
    if not isinstance(config, dict):
        raise ToolError("Missing scan configuration.")
    scan = start_scan(slug, config, name=data.get("name"))
    return jsonify(scan.to_dict()), 201


@bp.route("/api/scans/preview", methods=["POST"])
def api_preview():
    data = _json_body()
    slug = _require_tool(str(data.get("tool", "")))
    config = data.get("config")
    if not isinstance(config, dict):
        raise ToolError("Missing scan configuration.")
    _, validated, argv = prepare(slug, config)
    from shlex import quote

    return jsonify(
        {
            "argv": argv,
            "command": " ".join(quote(part) for part in argv),
            "config": validated,
        }
    )


@bp.route("/api/scans/<int:scan_id>", methods=["GET"])
def api_get(scan_id: int):
    scan = get_scan_or_404(scan_id)
    return jsonify(scan.to_dict())


@bp.route("/api/scans/<int:scan_id>", methods=["DELETE"])
def api_delete(scan_id: int):
    scan = get_scan_or_404(scan_id)
    delete_scan(scan)
    return jsonify({"deleted": scan_id})


@bp.route("/api/scans/<int:scan_id>/stop", methods=["POST"])
def api_stop(scan_id: int):
    scan = get_scan_or_404(scan_id)
    if not stop_scan(scan):
        raise ToolError("This scan is not running.")
    db.session.refresh(scan)
    return jsonify(scan.to_dict(include_config=False))


@bp.route("/api/scans/<int:scan_id>/pause", methods=["POST"])
def api_pause(scan_id: int):
    scan = get_scan_or_404(scan_id)
    if not pause_scan(scan):
        raise ToolError("This scan cannot be paused.")
    return jsonify({"paused": True})


@bp.route("/api/scans/<int:scan_id>/resume", methods=["POST"])
def api_resume(scan_id: int):
    scan = get_scan_or_404(scan_id)
    if not resume_scan(scan):
        raise ToolError("This scan is not paused.")
    return jsonify({"paused": False})


@bp.route("/api/scans/<int:scan_id>/restart", methods=["POST"])
def api_restart(scan_id: int):
    scan = get_scan_or_404(scan_id)
    new_scan = restart_scan(scan)
    return jsonify(new_scan.to_dict()), 201


@bp.route("/api/scans/<int:scan_id>/save", methods=["POST"])
def api_save(scan_id: int):
    scan = get_scan_or_404(scan_id)
    data = request.get_json(silent=True) or {}
    scan.saved = bool(data.get("saved", True))
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        scan.name = name.strip()[:200]
    db.session.commit()
    return jsonify(scan.to_dict(include_config=False))


@bp.route("/api/scans/<int:scan_id>/results", methods=["GET"])
def api_results(scan_id: int):
    scan = get_scan_or_404(scan_id)
    rows = parser.load_results(scan)
    return jsonify(
        {
            "scan": scan.to_dict(include_config=False),
            "columns": parser.COLUMNS.get(scan.tool, []),
            "results": rows,
        }
    )


@bp.route("/api/scans/<int:scan_id>/export", methods=["GET"])
def api_export(scan_id: int):
    scan = get_scan_or_404(scan_id)
    export_format = request.args.get("format", "json").lower()
    rows = parser.load_results(scan)
    if export_format == "csv":
        body, mimetype, extension = parser.to_csv(rows, scan.tool), "text/csv", "csv"
    elif export_format == "txt":
        body, mimetype, extension = parser.to_txt(rows), "text/plain", "txt"
    elif export_format == "json":
        body, mimetype, extension = parser.to_json(rows), "application/json", "json"
    else:
        raise ToolError("Export format must be json, csv or txt.")
    filename = f"{scan.tool}-scan-{scan.id}.{extension}"
    return Response(
        body,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/api/scans/<int:scan_id>/raw", methods=["GET"])
def api_raw(scan_id: int):
    scan = get_scan_or_404(scan_id)
    return Response(parser.read_raw_output(scan), mimetype="text/plain")


@bp.route("/api/scans/<int:scan_id>/stream")
def api_stream(scan_id: int):
    scan = get_scan_or_404(scan_id)
    scan_id = scan.id

    @stream_with_context
    def generate():
        yield "retry: 3000\n\n"
        if process_manager.get(scan_id) is None:
            yield f"event: exit\ndata: {json.dumps({'line': 'not running'})}\n\n"
            return
        for event, line in process_manager.stream(scan_id):
            if event == "ping":
                yield ": keep-alive\n\n"
                continue
            yield f"event: {event}\ndata: {json.dumps({'line': line})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
