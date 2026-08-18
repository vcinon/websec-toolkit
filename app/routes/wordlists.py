"""Independent wordlist libraries for each tool."""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from app.models import Setting, db
from app.services.wordlist_manager import WordlistError, get_wordlist_manager
from app.tools import TOOL_CLASSES

bp = Blueprint("wordlists", __name__)


def _require_tool(slug: str) -> str:
    if slug not in TOOL_CLASSES:
        raise WordlistError(f"Unknown tool: {slug}")
    return slug


@bp.route("/wordlists")
def index():
    return redirect(url_for("wordlists.library", slug="ffuf"))


@bp.route("/wordlists/<slug>")
def library(slug: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    return render_template(
        "wordlists/index.html",
        slug=slug,
        tool_name=TOOL_CLASSES[slug].name,
        root=str(manager.root),
        categories=manager.list_categories(),
        wordlists=[item.to_dict() for item in manager.list_all()],
        default_wordlist=Setting.get(f"{slug}_default_wordlist", ""),
    )


@bp.route("/api/wordlists/<slug>", methods=["GET"])
def api_list(slug: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    return jsonify(
        {
            "tool": slug,
            "root": str(manager.root),
            "categories": manager.list_categories(),
            "wordlists": [item.to_dict() for item in manager.list_all()],
            "default": Setting.get(f"{slug}_default_wordlist", ""),
        }
    )


@bp.route("/api/wordlists/<slug>", methods=["POST"])
def api_upload(slug: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    category = request.form.get("category", "custom")
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise WordlistError("No file was uploaded.")
    wordlist = manager.save_upload(category, upload.filename, upload)
    return jsonify(wordlist.to_dict()), 201


@bp.route("/api/wordlists/<slug>/categories", methods=["POST"])
def api_create_category(slug: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    if not name:
        raise WordlistError("Category name is required.")
    created = manager.create_category(name)
    return jsonify({"category": created, "categories": manager.list_categories()}), 201


@bp.route("/api/wordlists/<slug>/<path:wordlist_id>", methods=["GET"])
def api_preview(slug: str, wordlist_id: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    return jsonify({"id": wordlist_id, "preview": manager.preview(wordlist_id)})


@bp.route("/api/wordlists/<slug>/<path:wordlist_id>", methods=["PATCH"])
def api_rename(slug: str, wordlist_id: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    data = request.get_json(silent=True) or {}
    new_name = (data.get("name") or "").strip()
    if not new_name:
        raise WordlistError("A new name is required.")
    wordlist = manager.rename(wordlist_id, new_name)
    if Setting.get(f"{slug}_default_wordlist", "") == wordlist_id:
        Setting.set(f"{slug}_default_wordlist", wordlist.id)
        db.session.commit()
    return jsonify(wordlist.to_dict())


@bp.route("/api/wordlists/<slug>/<path:wordlist_id>", methods=["DELETE"])
def api_delete(slug: str, wordlist_id: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    manager.delete(wordlist_id)
    for key in (f"{slug}_default_wordlist", f"{slug}_last_wordlist"):
        if Setting.get(key, "") == wordlist_id:
            Setting.set(key, "")
    db.session.commit()
    return jsonify({"deleted": wordlist_id})


@bp.route("/api/wordlists/<slug>/default", methods=["POST"])
def api_set_default(slug: str):
    _require_tool(slug)
    manager = get_wordlist_manager(slug)
    data = request.get_json(silent=True) or {}
    wordlist_id = (data.get("id") or "").strip()
    if wordlist_id:
        manager.resolve(wordlist_id)
    Setting.set(f"{slug}_default_wordlist", wordlist_id)
    db.session.commit()
    return jsonify({"default": wordlist_id})
