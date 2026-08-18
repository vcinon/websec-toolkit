"""Abstract base class every security tool integration derives from."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

VERSION_PATTERN = re.compile(r"v?(\d+\.\d+(?:\.\d+)?)")


class ToolError(Exception):
    """Raised when a tool configuration is invalid or the tool is unusable."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class ToolStatus:
    installed: bool
    binary: str
    path: str | None = None
    version: str | None = None
    install_hint: str = ""


@dataclass
class BuiltCommand:
    argv: list[str]
    result_file: Path | None = None
    result_format: str = "json"
    env: dict[str, str] = field(default_factory=dict)


class SecurityTool:
    """Base class for tool integrations.

    Subclasses implement validation, command construction and output parsing.
    Adding a new tool means adding a subclass plus its routes/templates; no
    changes to the process manager or scan manager are required.
    """

    name = ""
    slug = ""
    description = ""
    binary = ""
    version_flag = "-version"
    accent = "#7c5cff"
    install_hint = ""
    wordlist_categories: tuple[str, ...] = ("custom",)

    def __init__(self, binary: str | None = None):
        if binary:
            self.binary = binary

    # -- discovery ---------------------------------------------------
    def resolve_binary(self) -> str | None:
        candidate = Path(self.binary).expanduser()
        if candidate.is_absolute():
            return str(candidate) if candidate.is_file() else None
        return shutil.which(self.binary)

    def is_installed(self) -> bool:
        return self.resolve_binary() is not None

    def get_version(self) -> str | None:
        path = self.resolve_binary()
        if not path:
            return None
        try:
            proc = subprocess.run(
                [path, self.version_flag],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        output = f"{proc.stdout}\n{proc.stderr}"
        match = VERSION_PATTERN.search(output)
        return match.group(1) if match else None

    def status(self) -> ToolStatus:
        path = self.resolve_binary()
        return ToolStatus(
            installed=path is not None,
            binary=self.binary,
            path=path,
            version=self.get_version() if path else None,
            install_hint=self.install_hint,
        )

    # -- lifecycle ---------------------------------------------------
    def validate_config(self, config: dict) -> dict:
        raise NotImplementedError

    def build_command(self, config: dict, output_dir: Path) -> BuiltCommand:
        raise NotImplementedError

    def parse_output(self, result_file: Path | None, raw_output: str) -> list[dict]:
        raise NotImplementedError

    # -- shared helpers ----------------------------------------------
    @staticmethod
    def validate_url(url: str, field_name: str = "Target URL") -> str:
        url = (url or "").strip()
        if not url:
            raise ToolError(f"{field_name} is required.")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ToolError(
                f"{field_name} must start with http:// or https://.",
                hint=f"Received: {url}",
            )
        if not parsed.netloc:
            raise ToolError(f"{field_name} is missing a hostname.")
        return url

    @staticmethod
    def validate_int(
        value, field_name: str, minimum: int, maximum: int, default: int | None = None
    ) -> int | None:
        if value in (None, ""):
            return default
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ToolError(f"{field_name} must be a whole number.") from exc
        if not minimum <= number <= maximum:
            raise ToolError(f"{field_name} must be between {minimum} and {maximum}.")
        return number

    @staticmethod
    def parse_headers(raw) -> list[dict[str, str]]:
        """Accept a list of {name, value} dicts or newline separated 'Name: value'."""
        headers: list[dict[str, str]] = []
        if isinstance(raw, str):
            entries = [line for line in raw.splitlines() if line.strip()]
            for line in entries:
                if ":" not in line:
                    raise ToolError(
                        "Headers must use the format 'Name: value'.",
                        hint=f"Invalid header: {line.strip()}",
                    )
                name, value = line.split(":", 1)
                headers.append({"name": name.strip(), "value": value.strip()})
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                value = str(item.get("value", "")).strip()
                if name:
                    headers.append({"name": name, "value": value})
        for header in headers:
            if "\n" in header["name"] or "\n" in header["value"]:
                raise ToolError("Header values may not contain newlines.")
            if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", header["name"]):
                raise ToolError("Invalid header name.", hint=f"Invalid header: {header['name']}")
        return headers
