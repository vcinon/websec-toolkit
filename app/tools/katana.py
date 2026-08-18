"""Katana integration — crawling and endpoint discovery."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from app.tools.base import BuiltCommand, SecurityTool, ToolError

SCOPES = {
    "": None,
    "rdn": "rdn",
    "dn": "dn",
    "fqdn": "fqdn",
}


class KatanaTool(SecurityTool):
    name = "katana"
    slug = "katana"
    description = "Next generation crawler for endpoint and asset discovery."
    binary = "katana"
    accent = "#4aa8ff"
    install_hint = (
        "Install with: go install github.com/projectdiscovery/katana/cmd/katana@latest "
        "(or download a release from https://github.com/projectdiscovery/katana/releases)"
    )
    # Katana has no fuzzing wordlist; these lists map to real katana inputs:
    #   crawl      -> seed URL lists  (-list)
    #   extensions -> extension match list (-em)
    #   headers    -> header/cookie file (-H)
    wordlist_categories = ("crawl", "extensions", "headers", "custom")

    # -- validation ---------------------------------------------------
    def validate_config(self, config: dict) -> dict:
        urls_raw = config.get("urls") or config.get("url") or ""
        candidates = urls_raw if isinstance(urls_raw, list) else re.split(r"[\s,]+", str(urls_raw))
        urls = [self.validate_url(url) for url in candidates if url.strip()]

        url_list_path = config.get("url_list_path") or ""
        if url_list_path and not Path(url_list_path).is_file():
            raise ToolError("The selected URL list does not exist.", hint=str(url_list_path))
        if not urls and not url_list_path:
            raise ToolError(
                "At least one target URL is required.",
                hint="Enter a URL or select a seed URL list from the Katana crawl wordlists.",
            )

        header_file = config.get("header_file_path") or ""
        if header_file and not Path(header_file).is_file():
            raise ToolError("The selected header list does not exist.", hint=str(header_file))

        extension_file = config.get("extension_file_path") or ""
        if extension_file and not Path(extension_file).is_file():
            raise ToolError("The selected extension list does not exist.", hint=str(extension_file))

        scope = (config.get("scope") or "").strip()
        if scope not in SCOPES:
            raise ToolError("Scope must be one of: rdn, dn, fqdn or empty.")

        for key, label in (
            ("include_regex", "Include pattern"),
            ("exclude_regex", "Exclude pattern"),
        ):
            pattern = (config.get(key) or "").strip()
            if pattern:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ToolError(
                        f"{label} is not a valid regular expression.", hint=str(exc)
                    ) from exc

        proxy = (config.get("proxy") or "").strip()
        if proxy:
            self.validate_url(proxy, "Proxy URL")

        return {
            "urls": urls,
            "url_list": config.get("url_list", ""),
            "url_list_path": url_list_path,
            "header_list": config.get("header_list", ""),
            "header_file_path": header_file,
            "extension_list": config.get("extension_list", ""),
            "extension_file_path": extension_file,
            "headers": self.parse_headers(config.get("headers")),
            "cookies": (config.get("cookies") or "").strip(),
            "authorization": (config.get("authorization") or "").strip(),
            "scope": scope,
            "include_regex": (config.get("include_regex") or "").strip(),
            "exclude_regex": (config.get("exclude_regex") or "").strip(),
            "depth": self.validate_int(config.get("depth"), "Depth", 1, 50, 3),
            "concurrency": self.validate_int(config.get("concurrency"), "Concurrency", 1, 200, 10),
            "parallelism": self.validate_int(config.get("parallelism"), "Parallelism", 1, 200, 10),
            "rate_limit": self.validate_int(config.get("rate_limit"), "Rate limit", 0, 10000, 0),
            "timeout": self.validate_int(config.get("timeout"), "Timeout", 1, 3600, 10),
            "delay": self.validate_int(config.get("delay"), "Delay", 0, 600, 0),
            "crawl_duration": (config.get("crawl_duration") or "").strip(),
            "js_crawl": bool(config.get("js_crawl")),
            "headless": bool(config.get("headless")),
            "known_files": (config.get("known_files") or "").strip(),
            "form_extraction": bool(config.get("form_extraction")),
            "automatic_form_fill": bool(config.get("automatic_form_fill")),
            "proxy": proxy,
            "strategy": (config.get("strategy") or "depth-first").strip(),
        }

    # -- command ------------------------------------------------------
    def build_command(self, config: dict, output_dir: Path) -> BuiltCommand:
        binary = self.resolve_binary() or self.binary
        result_file = output_dir / "results.jsonl"
        argv: list[str] = [binary]

        for url in config["urls"]:
            argv += ["-u", url]
        if config["url_list_path"]:
            argv += ["-list", config["url_list_path"]]

        argv += [
            "-depth",
            str(config["depth"]),
            "-concurrency",
            str(config["concurrency"]),
            "-parallelism",
            str(config["parallelism"]),
            "-timeout",
            str(config["timeout"]),
            "-jsonl",
            "-output",
            str(result_file),
            "-no-color",
            "-disable-update-check",
        ]

        if config["strategy"] in {"depth-first", "breadth-first"}:
            argv += ["-strategy", config["strategy"]]
        if config["rate_limit"]:
            argv += ["-rate-limit", str(config["rate_limit"])]
        if config["delay"]:
            argv += ["-delay", str(config["delay"])]
        if config["crawl_duration"]:
            argv += ["-crawl-duration", config["crawl_duration"]]
        if config["scope"]:
            argv += ["-field-scope", config["scope"]]
        if config["include_regex"]:
            argv += ["-crawl-scope", config["include_regex"]]
        if config["exclude_regex"]:
            argv += ["-crawl-out-scope", config["exclude_regex"]]
        if config["js_crawl"]:
            argv.append("-js-crawl")
        if config["headless"]:
            argv.append("-headless")
        if config["known_files"] in {"robotstxt", "sitemapxml", "all"}:
            argv += ["-known-files", config["known_files"]]
        if config["form_extraction"]:
            argv.append("-form-extraction")
        if config["automatic_form_fill"]:
            argv.append("-automatic-form-fill")
        if config["proxy"]:
            argv += ["-proxy", config["proxy"]]
        if config["extension_file_path"]:
            extensions = self._read_extensions(Path(config["extension_file_path"]))
            if extensions:
                argv += ["-extension-match", ",".join(extensions)]
        if config["header_file_path"]:
            argv += ["-headers", config["header_file_path"]]
        for header in config["headers"]:
            argv += ["-headers", f"{header['name']}: {header['value']}"]
        if config["cookies"]:
            argv += ["-headers", f"Cookie: {config['cookies']}"]
        if config["authorization"]:
            argv += ["-headers", f"Authorization: {config['authorization']}"]

        return BuiltCommand(argv=argv, result_file=result_file, result_format="jsonl")

    @staticmethod
    def _read_extensions(path: Path) -> list[str]:
        extensions = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            value = line.strip().lstrip(".")
            if value and not value.startswith("#"):
                extensions.append(value)
        return extensions[:200]

    # -- parsing ------------------------------------------------------
    def parse_output(self, result_file: Path | None, raw_output: str) -> list[dict]:
        rows: list[dict] = []
        seen: set[str] = set()
        lines: list[str] = []
        if result_file and result_file.is_file():
            lines = result_file.read_text(encoding="utf-8", errors="replace").splitlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            request = item.get("request") or {}
            response = item.get("response") or {}
            url = request.get("endpoint") or item.get("endpoint") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            parsed = urlparse(url)
            extension = Path(parsed.path).suffix.lstrip(".").lower()
            rows.append(
                {
                    "url": url,
                    "method": request.get("method", ""),
                    "source": request.get("source", "") or item.get("source", ""),
                    "tag": request.get("tag", ""),
                    "attribute": request.get("attribute", ""),
                    "status": response.get("status_code"),
                    "content_type": (response.get("headers") or {}).get("content_type", ""),
                    "host": parsed.netloc,
                    "extension": extension,
                }
            )
        rows.sort(key=lambda row: row["url"])
        return rows
