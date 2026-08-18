"""Result loading, filtering and export helpers."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from app.models import Scan
from app.tools import get_tool

FFUF_COLUMNS = [
    "status",
    "url",
    "input",
    "length",
    "words",
    "lines",
    "content_type",
    "redirect",
    "duration_ms",
]
KATANA_COLUMNS = [
    "url",
    "method",
    "status",
    "content_type",
    "source",
    "tag",
    "host",
    "extension",
]

COLUMNS = {"ffuf": FFUF_COLUMNS, "katana": KATANA_COLUMNS}


def load_results(scan: Scan) -> list[dict]:
    tool = get_tool(scan.tool)
    result_file = Path(scan.result_file) if scan.result_file else None
    raw = read_raw_output(scan)
    try:
        return tool.parse_output(result_file, raw)
    except (OSError, ValueError):
        return []


def read_raw_output(scan: Scan, max_bytes: int = 512 * 1024) -> str:
    if not scan.output_file:
        return ""
    path = Path(scan.output_file)
    if not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
            handle.readline()
        return handle.read()


def to_csv(rows: list[dict], tool: str) -> str:
    columns = COLUMNS.get(tool) or (list(rows[0].keys()) if rows else [])
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def to_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2)


def to_txt(rows: list[dict]) -> str:
    return "\n".join(str(row.get("url", "")) for row in rows if row.get("url"))
