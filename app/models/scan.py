import json
from datetime import datetime, timezone
from enum import Enum

from app.models.db import db

SENSITIVE_CONFIG_KEYS = {"cookies", "authorization", "auth_header"}
REDACTED = "<redacted>"


class ScanStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"

    @property
    def is_terminal(self) -> bool:
        return self in {ScanStatus.COMPLETED, ScanStatus.FAILED, ScanStatus.STOPPED}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Scan(db.Model):
    __tablename__ = "scans"

    id = db.Column(db.Integer, primary_key=True)
    tool = db.Column(db.String(32), nullable=False, index=True)
    target = db.Column(db.String(2048), nullable=False)
    status = db.Column(db.String(16), nullable=False, default=ScanStatus.QUEUED.value)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    pid = db.Column(db.Integer, nullable=True)
    exit_code = db.Column(db.Integer, nullable=True)
    error = db.Column(db.Text, nullable=True)
    command_json = db.Column(db.Text, nullable=False, default="[]")
    config_json = db.Column(db.Text, nullable=False, default="{}")
    output_file = db.Column(db.String(1024), nullable=True)
    result_file = db.Column(db.String(1024), nullable=True)
    result_count = db.Column(db.Integer, nullable=False, default=0)
    saved = db.Column(db.Boolean, nullable=False, default=False)
    name = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def command(self) -> list[str]:
        return json.loads(self.command_json)

    @command.setter
    def command(self, value: list[str]) -> None:
        self.command_json = json.dumps(value)

    @property
    def config(self) -> dict:
        return json.loads(self.config_json)

    @config.setter
    def config(self, value: dict) -> None:
        self.config_json = json.dumps(value)

    @property
    def command_string(self) -> str:
        from shlex import quote

        return " ".join(quote(part) for part in self.command)

    @property
    def duration_seconds(self) -> float | None:
        if not self.start_time:
            return None
        end = self.end_time or utcnow().replace(tzinfo=None)
        return max(0.0, (end - self.start_time).total_seconds())

    def safe_config(self) -> dict:
        """Configuration with authentication material removed."""
        config = self.config
        for key in SENSITIVE_CONFIG_KEYS:
            if config.get(key):
                config[key] = REDACTED
        headers = config.get("headers")
        if isinstance(headers, list):
            config["headers"] = [
                {
                    "name": header.get("name", ""),
                    "value": REDACTED
                    if header.get("name", "").lower() in {"authorization", "cookie", "x-api-key"}
                    else header.get("value", ""),
                }
                for header in headers
            ]
        return config

    def to_dict(self, include_config: bool = True) -> dict:
        data = {
            "id": self.id,
            "tool": self.tool,
            "target": self.target,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "error": self.error,
            "command": self.command,
            "command_string": self.command_string,
            "output_file": self.output_file,
            "result_file": self.result_file,
            "result_count": self.result_count,
            "saved": self.saved,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_config:
            data["config"] = self.safe_config()
        return data
