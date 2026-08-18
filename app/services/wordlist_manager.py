"""Per-tool wordlist libraries.

Each tool owns an independent root directory (``wordlists/ffuf`` and
``wordlists/katana`` by default) and its own set of categories. Nothing is
shared between tools.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from flask import current_app

from app.tools import get_tool

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_COUNT_BYTES = 8 * 1024 * 1024


class WordlistError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class Wordlist:
    tool: str
    category: str
    name: str
    path: Path
    size_bytes: int
    entries: int | None

    @property
    def id(self) -> str:
        return f"{self.category}/{self.name}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool": self.tool,
            "category": self.category,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "size_human": human_size(self.size_bytes),
            "entries": self.entries,
        }


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = Path(name.replace("\\", "/")).name
    name = SAFE_NAME.sub("_", name).strip("._")
    if not name:
        raise WordlistError("Invalid file name.")
    return name[:120]


class WordlistManager:
    """Filesystem backed wordlist library scoped to a single tool."""

    def __init__(self, tool_slug: str, root: Path):
        self.tool_slug = tool_slug
        self.root = Path(root).resolve()
        self.categories = list(get_tool(tool_slug).wordlist_categories)

    # -- paths --------------------------------------------------------
    def ensure_dirs(self) -> None:
        for category in self.categories:
            (self.root / category).mkdir(parents=True, exist_ok=True)

    def category_dir(self, category: str) -> Path:
        category = sanitize_filename(category)
        path = (self.root / category).resolve()
        if path != self.root and self.root not in path.parents:
            raise WordlistError("Invalid category.")
        return path

    def resolve(self, wordlist_id: str) -> Path:
        """Resolve 'category/name' to an absolute path inside this tool's root."""
        if not wordlist_id:
            raise WordlistError("No wordlist selected.")
        parts = [part for part in wordlist_id.split("/") if part not in ("", ".", "..")]
        if len(parts) != 2:
            raise WordlistError("Invalid wordlist reference.", hint=f"Received: {wordlist_id}")
        category, name = sanitize_filename(parts[0]), sanitize_filename(parts[1])
        path = (self.root / category / name).resolve()
        if self.root not in path.parents:
            raise WordlistError("Wordlist path is outside the library.")
        if not path.is_file():
            raise WordlistError("The selected wordlist does not exist.", hint=wordlist_id)
        return path

    # -- queries ------------------------------------------------------
    def list_categories(self) -> list[str]:
        self.ensure_dirs()
        existing = {p.name for p in self.root.iterdir() if p.is_dir()}
        return sorted(existing | set(self.categories))

    def list_all(self) -> list[Wordlist]:
        self.ensure_dirs()
        items: list[Wordlist] = []
        for category in self.list_categories():
            items.extend(self.list_category(category))
        return items

    def list_category(self, category: str) -> list[Wordlist]:
        directory = self.category_dir(category)
        if not directory.is_dir():
            return []
        items = []
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            size = path.stat().st_size
            items.append(
                Wordlist(
                    tool=self.tool_slug,
                    category=category,
                    name=path.name,
                    path=path,
                    size_bytes=size,
                    entries=self._count_entries(path, size),
                )
            )
        return items

    @staticmethod
    def _count_entries(path: Path, size: int) -> int | None:
        if size > MAX_COUNT_BYTES:
            return None
        try:
            with path.open("rb") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return None

    def preview(self, wordlist_id: str, limit: int = 50) -> list[str]:
        path = self.resolve(wordlist_id)
        lines = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= limit:
                    break
                lines.append(line.rstrip("\n"))
        return lines

    # -- mutations ----------------------------------------------------
    def create_category(self, category: str) -> str:
        directory = self.category_dir(category)
        directory.mkdir(parents=True, exist_ok=True)
        return directory.name

    def save_upload(self, category: str, filename: str, stream) -> Wordlist:
        allowed = current_app.config["ALLOWED_WORDLIST_EXTENSIONS"]
        name = sanitize_filename(filename)
        if Path(name).suffix.lower() not in allowed:
            raise WordlistError(
                "Unsupported file type.",
                hint=f"Allowed extensions: {', '.join(sorted(e for e in allowed if e))}",
            )
        directory = self.category_dir(category)
        directory.mkdir(parents=True, exist_ok=True)
        destination = (directory / name).resolve()
        if self.root not in destination.parents:
            raise WordlistError("Invalid destination path.")
        if destination.exists():
            stem, suffix = destination.stem, destination.suffix
            counter = 2
            while destination.exists():
                destination = directory / f"{stem}-{counter}{suffix}"
                counter += 1
        stream.save(destination)
        size = destination.stat().st_size
        if size == 0:
            destination.unlink(missing_ok=True)
            raise WordlistError("The uploaded wordlist is empty.")
        return Wordlist(
            tool=self.tool_slug,
            category=directory.name,
            name=destination.name,
            path=destination,
            size_bytes=size,
            entries=self._count_entries(destination, size),
        )

    def delete(self, wordlist_id: str) -> None:
        path = self.resolve(wordlist_id)
        path.unlink()

    def rename(self, wordlist_id: str, new_name: str) -> Wordlist:
        path = self.resolve(wordlist_id)
        name = sanitize_filename(new_name)
        destination = (path.parent / name).resolve()
        if self.root not in destination.parents:
            raise WordlistError("Invalid destination path.")
        if destination.exists():
            raise WordlistError("A wordlist with that name already exists.")
        path.rename(destination)
        size = destination.stat().st_size
        return Wordlist(
            tool=self.tool_slug,
            category=destination.parent.name,
            name=destination.name,
            path=destination,
            size_bytes=size,
            entries=self._count_entries(destination, size),
        )


def get_wordlist_manager(tool_slug: str) -> WordlistManager:
    roots = {
        "ffuf": current_app.config["FFUF_WORDLIST_DIR"],
        "katana": current_app.config["KATANA_WORDLIST_DIR"],
    }
    if tool_slug not in roots:
        raise WordlistError(f"Unknown tool: {tool_slug}")
    manager = WordlistManager(tool_slug, Path(roots[tool_slug]))
    manager.ensure_dirs()
    return manager
