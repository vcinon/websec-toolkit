"""Application configuration.

Values can be overridden with environment variables (see .env.example).
"""

import os
from pathlib import Path
from typing import ClassVar

BASE_DIR = Path(__file__).resolve().parent


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    BASE_DIR = BASE_DIR
    INSTANCE_DIR = _env_path("WST_INSTANCE_DIR", BASE_DIR / "instance")
    SCAN_DIR = _env_path("WST_SCAN_DIR", INSTANCE_DIR / "scans")
    WORDLIST_DIR = _env_path("WST_WORDLIST_DIR", BASE_DIR / "wordlists")

    FFUF_WORDLIST_DIR = _env_path("WST_FFUF_WORDLIST_DIR", WORDLIST_DIR / "ffuf")
    KATANA_WORDLIST_DIR = _env_path("WST_KATANA_WORDLIST_DIR", WORDLIST_DIR / "katana")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'toolkit.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Uploaded wordlists
    MAX_CONTENT_LENGTH = int(os.environ.get("WST_MAX_UPLOAD_BYTES", str(32 * 1024 * 1024)))
    ALLOWED_WORDLIST_EXTENSIONS: ClassVar[set[str]] = {
        ".txt",
        ".lst",
        ".list",
        ".dic",
        ".words",
        "",
    }

    # Live console ring buffer size (lines kept in memory per scan)
    CONSOLE_BUFFER_LINES = int(os.environ.get("WST_CONSOLE_BUFFER_LINES", "5000"))

    # Defaults, overridable at runtime from the Settings page
    DEFAULT_SETTINGS: ClassVar[dict[str, str]] = {
        "theme": "dark",
        "max_concurrent_scans": "3",
        "default_timeout": "10",
        "auto_save_results": "true",
        "ffuf_binary": "ffuf",
        "katana_binary": "katana",
        "ffuf_default_wordlist": "",
        "katana_default_wordlist": "",
        "ffuf_last_wordlist": "",
        "katana_last_wordlist": "",
    }

    WTF_CSRF_TIME_LIMIT = None


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
