"""ffuf integration — HTTP fuzzing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from app.tools.base import BuiltCommand, SecurityTool, ToolError

STATUS_LIST_CHARS = set("0123456789,-*")


class FfufTool(SecurityTool):
    name = "ffuf"
    slug = "ffuf"
    description = "Fast web fuzzer for directories, files, parameters and vhosts."
    binary = "ffuf"
    version_flag = "-V"
    accent = "#00d38a"
    install_hint = (
        "Install with: go install github.com/ffuf/ffuf/v2@latest "
        "(or download a release from https://github.com/ffuf/ffuf/releases)"
    )
    wordlist_categories = (
        "directories",
        "files",
        "parameters",
        "subdomains",
        "custom",
    )

    PRESETS: ClassVar[dict[str, dict]] = {
        "directory": {
            "label": "Directory Discovery",
            "config": {
                "method": "GET",
                "threads": 40,
                "match_status": "200,204,301,302,307,401,403",
                "follow_redirects": False,
                "category": "directories",
            },
        },
        "file": {
            "label": "File Discovery",
            "config": {
                "method": "GET",
                "threads": 40,
                "match_status": "200,204,403",
                "extensions": ".php,.bak,.txt,.zip",
                "category": "files",
            },
        },
        "parameter": {
            "label": "Parameter Discovery",
            "config": {
                "method": "GET",
                "threads": 40,
                "match_status": "200",
                "filter_size": "",
                "category": "parameters",
            },
        },
        "vhost": {
            "label": "Virtual Host Discovery",
            "config": {
                "method": "GET",
                "threads": 40,
                "match_status": "200,204,301,302,307,401,403",
                "headers": [{"name": "Host", "value": "FUZZ.example.com"}],
                "category": "subdomains",
            },
        },
        "custom": {"label": "Custom", "config": {}},
    }

    # -- validation ---------------------------------------------------
    def validate_config(self, config: dict) -> dict:
        url = self.validate_url(config.get("url", ""))
        method = (config.get("method") or "GET").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ToolError(f"Unsupported HTTP method: {method}")

        headers = self.parse_headers(config.get("headers"))
        body = (config.get("body") or "").strip()
        cookies = (config.get("cookies") or "").strip()

        fuzz_locations = [url, body, cookies] + [h["value"] for h in headers]
        if not any("FUZZ" in value for value in fuzz_locations):
            raise ToolError(
                "The FUZZ keyword is missing.",
                hint="Place FUZZ in the URL, a header value, the cookie string or the request body.",
            )

        wordlist_path = config.get("wordlist_path")
        if not wordlist_path:
            raise ToolError(
                "No wordlist selected.",
                hint="Pick a wordlist from the ffuf wordlist library or upload a new one.",
            )
        if not Path(wordlist_path).is_file():
            raise ToolError(
                "The selected wordlist does not exist.",
                hint=str(wordlist_path),
            )

        proxy = (config.get("proxy") or "").strip()
        if proxy:
            self.validate_url(proxy, "Proxy URL")

        validated = {
            "url": url,
            "method": method,
            "headers": headers,
            "body": body,
            "cookies": cookies,
            "wordlist": config.get("wordlist", ""),
            "wordlist_path": str(wordlist_path),
            "category": config.get("category", ""),
            "preset": config.get("preset", "custom"),
            "extensions": (config.get("extensions") or "").strip(),
            "follow_redirects": bool(config.get("follow_redirects")),
            "tls_verify": bool(config.get("tls_verify", True)),
            "stop_on_error": bool(config.get("stop_on_error")),
            "auto_calibrate": bool(config.get("auto_calibrate")),
            "recursion": bool(config.get("recursion")),
            "proxy": proxy,
            "threads": self.validate_int(config.get("threads"), "Threads", 1, 500, 40),
            "rate": self.validate_int(config.get("rate"), "Rate limit", 0, 100000, 0),
            "delay": (config.get("delay") or "").strip(),
            "timeout": self.validate_int(config.get("timeout"), "Timeout", 1, 3600, 10),
            "recursion_depth": self.validate_int(
                config.get("recursion_depth"), "Recursion depth", 0, 20, 0
            ),
            "output_format": (config.get("output_format") or "json").lower(),
        }

        for key, label in (
            ("match_status", "Match status codes"),
            ("filter_status", "Filter status codes"),
        ):
            value = (config.get(key) or "").strip()
            if value and not set(value) <= STATUS_LIST_CHARS:
                raise ToolError(f"{label} must be a comma separated list, e.g. 200,301.")
            validated[key] = value

        for key, label in (
            ("match_size", "Match size"),
            ("match_words", "Match words"),
            ("match_lines", "Match lines"),
            ("filter_size", "Filter size"),
            ("filter_words", "Filter words"),
            ("filter_lines", "Filter lines"),
        ):
            value = (config.get(key) or "").strip()
            if value and not set(value) <= set("0123456789,-"):
                raise ToolError(f"{label} must be a comma separated list of numbers.")
            validated[key] = value

        validated["match_regex"] = (config.get("match_regex") or "").strip()
        validated["filter_regex"] = (config.get("filter_regex") or "").strip()

        if validated["delay"] and not set(validated["delay"]) <= set("0123456789.-"):
            raise ToolError("Delay must be a number or a range such as 0.1-2.0.")

        if validated["output_format"] not in {"json", "csv", "html"}:
            raise ToolError("Output format must be json, csv or html.")

        return validated

    # -- command ------------------------------------------------------
    def build_command(self, config: dict, output_dir: Path) -> BuiltCommand:
        binary = self.resolve_binary() or self.binary
        # ffuf always writes machine readable JSON so results can be parsed;
        # an extra export in the requested format is produced on demand.
        result_file = output_dir / "results.json"
        argv: list[str] = [
            binary,
            "-u",
            config["url"],
            "-w",
            config["wordlist_path"],
            "-t",
            str(config["threads"]),
            "-timeout",
            str(config["timeout"]),
            "-of",
            "json",
            "-o",
            str(result_file),
            "-noninteractive",
        ]

        if config["method"] != "GET":
            argv += ["-X", config["method"]]
        for header in config["headers"]:
            argv += ["-H", f"{header['name']}: {header['value']}"]
        if config["cookies"]:
            argv += ["-b", config["cookies"]]
        if config["body"]:
            argv += ["-d", config["body"]]
        if config["extensions"]:
            argv += ["-e", config["extensions"]]
        if config["follow_redirects"]:
            argv.append("-r")
        if not config["tls_verify"]:
            argv.append("-k")
        if config["proxy"]:
            argv += ["-x", config["proxy"]]
        if config["rate"]:
            argv += ["-rate", str(config["rate"])]
        if config["delay"]:
            argv += ["-p", config["delay"]]
        if config["auto_calibrate"]:
            argv.append("-ac")
        if config["stop_on_error"]:
            argv.append("-sa")
        if config["recursion"]:
            argv.append("-recursion")
            if config["recursion_depth"]:
                argv += ["-recursion-depth", str(config["recursion_depth"])]

        matchers = (
            ("-mc", config["match_status"]),
            ("-ms", config["match_size"]),
            ("-mw", config["match_words"]),
            ("-ml", config["match_lines"]),
            ("-mr", config["match_regex"]),
            ("-fc", config["filter_status"]),
            ("-fs", config["filter_size"]),
            ("-fw", config["filter_words"]),
            ("-fl", config["filter_lines"]),
            ("-fr", config["filter_regex"]),
        )
        for flag, value in matchers:
            if value:
                argv += [flag, value]

        return BuiltCommand(argv=argv, result_file=result_file, result_format="json")

    # -- parsing ------------------------------------------------------
    def parse_output(self, result_file: Path | None, raw_output: str) -> list[dict]:
        if not result_file or not result_file.is_file():
            return []
        try:
            data = json.loads(result_file.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            return []
        rows = []
        for item in data.get("results", []) or []:
            rows.append(
                {
                    "status": item.get("status"),
                    "url": item.get("url", ""),
                    "input": (item.get("input") or {}).get("FUZZ", ""),
                    "length": item.get("length"),
                    "words": item.get("words"),
                    "lines": item.get("lines"),
                    "content_type": item.get("content-type", ""),
                    "redirect": item.get("redirectlocation", ""),
                    "duration_ms": round((item.get("duration") or 0) / 1_000_000, 1),
                    "host": item.get("host", ""),
                }
            )
        rows.sort(key=lambda row: (row["status"] or 0, row["url"]))
        return rows
