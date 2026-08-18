"""Coordinates tools, the process manager and scan persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, current_app

from app.models import Scan, ScanStatus, Setting, db
from app.services import parser
from app.services.process_manager import process_manager
from app.services.wordlist_manager import WordlistError, get_wordlist_manager
from app.tools import SecurityTool, ToolError, get_tool

# ffuf/katana config keys holding a 'category/name' wordlist reference and the
# validated key the resolved absolute path is written to.
WORDLIST_FIELDS = {
    "ffuf": {"wordlist": "wordlist_path"},
    "katana": {
        "url_list": "url_list_path",
        "header_list": "header_file_path",
        "extension_list": "extension_file_path",
    },
}


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def tool_binary(slug: str) -> str:
    return Setting.get(f"{slug}_binary", slug) or slug


def build_tool(slug: str) -> SecurityTool:
    return get_tool(slug, binary=tool_binary(slug))


def resolve_wordlists(slug: str, config: dict) -> dict:
    """Turn 'category/name' references into validated absolute paths."""
    config = dict(config)
    manager = get_wordlist_manager(slug)
    for source_key, path_key in WORDLIST_FIELDS.get(slug, {}).items():
        reference = (config.get(source_key) or "").strip()
        config[path_key] = str(manager.resolve(reference)) if reference else ""
    return config


def prepare(slug: str, raw_config: dict) -> tuple[SecurityTool, dict, list[str]]:
    """Validate a configuration and build the command that would be executed."""
    tool = build_tool(slug)
    config = resolve_wordlists(slug, raw_config)
    validated = tool.validate_config(config)
    scan_dir = Path(current_app.config["SCAN_DIR"]) / "preview"
    built = tool.build_command(validated, scan_dir)
    return tool, validated, built.argv


def scan_dir_for(scan_id: int) -> Path:
    path = Path(current_app.config["SCAN_DIR"]) / str(scan_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_scan_count() -> int:
    return (
        db.session.query(Scan)
        .filter(Scan.status.in_([ScanStatus.RUNNING.value, ScanStatus.QUEUED.value]))
        .count()
    )


def start_scan(slug: str, raw_config: dict, name: str | None = None) -> Scan:
    tool = build_tool(slug)
    if not tool.is_installed():
        raise ToolError(
            f"{tool.name} could not be started because the binary was not found.",
            hint=tool.install_hint,
        )

    max_concurrent = int(Setting.get("max_concurrent_scans", "3") or 3)
    if active_scan_count() >= max_concurrent:
        raise ToolError(
            "Maximum number of concurrent scans reached.",
            hint=f"Limit is {max_concurrent}; stop a running scan or raise the limit in Settings.",
        )

    config = resolve_wordlists(slug, raw_config)
    validated = tool.validate_config(config)

    target = validated.get("url") or ", ".join(validated.get("urls", [])) or "(list)"
    scan = Scan(
        tool=slug,
        target=target,
        status=ScanStatus.QUEUED.value,
        name=(name or "").strip() or None,
    )
    scan.config = validated
    db.session.add(scan)
    db.session.commit()

    output_dir = scan_dir_for(scan.id)
    built = tool.build_command(validated, output_dir)
    scan.command = built.argv
    scan.output_file = str(output_dir / "output.log")
    scan.result_file = str(built.result_file) if built.result_file else None
    db.session.commit()

    app = current_app._get_current_object()
    try:
        process = process_manager.start(
            scan_id=scan.id,
            argv=built.argv,
            log_path=Path(scan.output_file),
            on_exit=lambda scan_id, code: _finalize(app, scan_id, code),
            cwd=output_dir,
        )
    except FileNotFoundError as exc:
        scan.status = ScanStatus.FAILED.value
        scan.error = f"{tool.name} binary not found: {tool.binary}"
        scan.end_time = utcnow_naive()
        db.session.commit()
        raise ToolError(scan.error, hint=tool.install_hint) from exc
    except (OSError, RuntimeError) as exc:
        scan.status = ScanStatus.FAILED.value
        scan.error = f"Could not start {tool.name}: {exc}"
        scan.end_time = utcnow_naive()
        db.session.commit()
        raise ToolError(scan.error) from exc

    scan.status = ScanStatus.RUNNING.value
    scan.pid = process.pid
    scan.start_time = utcnow_naive()
    db.session.commit()

    Setting.set(f"{slug}_last_wordlist", raw_config.get("wordlist", "") or "")
    db.session.commit()
    return scan


def _finalize(app: Flask, scan_id: int, exit_code: int) -> None:
    """Runs on the reader thread once the process exits."""
    with app.app_context():
        scan = db.session.get(Scan, scan_id)
        if scan is None:
            return
        scan.exit_code = exit_code
        scan.end_time = utcnow_naive()
        scan.pid = None
        if scan.status == ScanStatus.STOPPED.value:
            pass
        elif exit_code == 0:
            scan.status = ScanStatus.COMPLETED.value
        elif exit_code in (-15, -9, 143, 137):
            scan.status = ScanStatus.STOPPED.value
        else:
            scan.status = ScanStatus.FAILED.value
            tail = parser.read_raw_output(scan, max_bytes=4096).strip().splitlines()
            scan.error = tail[-1] if tail else f"Process exited with code {exit_code}"
        try:
            scan.result_count = len(parser.load_results(scan))
        except (OSError, ValueError):
            scan.result_count = 0
        db.session.commit()


def stop_scan(scan: Scan) -> bool:
    if scan.status != ScanStatus.RUNNING.value:
        return False
    scan.status = ScanStatus.STOPPED.value
    db.session.commit()
    stopped = process_manager.stop(scan.id)
    if not stopped:
        scan.end_time = utcnow_naive()
        scan.pid = None
        db.session.commit()
    return True


def pause_scan(scan: Scan) -> bool:
    return process_manager.pause(scan.id)


def resume_scan(scan: Scan) -> bool:
    return process_manager.resume(scan.id)


def restart_scan(scan: Scan) -> Scan:
    return start_scan(scan.tool, scan.config, name=scan.name)


def delete_scan(scan: Scan) -> None:
    if scan.status == ScanStatus.RUNNING.value:
        stop_scan(scan)
    directory = Path(current_app.config["SCAN_DIR"]) / str(scan.id)
    if directory.is_dir():
        for path in sorted(directory.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        directory.rmdir()
    db.session.delete(scan)
    db.session.commit()


def reconcile_orphans() -> None:
    """Mark scans left RUNNING by a previous process as stopped."""
    stale = (
        db.session.query(Scan)
        .filter(Scan.status.in_([ScanStatus.RUNNING.value, ScanStatus.QUEUED.value]))
        .all()
    )
    for scan in stale:
        if process_manager.get(scan.id) is None:
            scan.status = ScanStatus.STOPPED.value
            scan.pid = None
            scan.end_time = scan.end_time or utcnow_naive()
            scan.error = scan.error or "Interrupted by application restart."
    if stale:
        db.session.commit()


__all__ = [
    "WordlistError",
    "active_scan_count",
    "build_tool",
    "delete_scan",
    "pause_scan",
    "prepare",
    "reconcile_orphans",
    "restart_scan",
    "resume_scan",
    "start_scan",
    "stop_scan",
    "tool_binary",
]
