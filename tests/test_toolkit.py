import json
from pathlib import Path

import pytest

from app import create_app
from app.models import Scan, ScanStatus, db
from app.services import parser
from app.services.wordlist_manager import WordlistError, get_wordlist_manager
from app.tools import get_tool
from app.tools.base import ToolError


class _Upload:
    """Minimal stand-in for a Werkzeug FileStorage."""

    def __init__(self, data: bytes):
        self.data = data

    def save(self, destination):
        Path(destination).write_bytes(self.data)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("WST_INSTANCE_DIR", str(tmp_path / "instance"))
    monkeypatch.setenv("WST_SCAN_DIR", str(tmp_path / "instance" / "scans"))
    monkeypatch.setenv("WST_WORDLIST_DIR", str(tmp_path / "wordlists"))
    monkeypatch.setenv("WST_FFUF_WORDLIST_DIR", str(tmp_path / "wordlists" / "ffuf"))
    monkeypatch.setenv("WST_KATANA_WORDLIST_DIR", str(tmp_path / "wordlists" / "katana"))
    import importlib

    import config as config_module

    importlib.reload(config_module)
    application = create_app(config_module.TestConfig)
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def test_tool_detection_reports_status(client):
    payload = client.get("/api/tools").get_json()
    slugs = {tool["slug"] for tool in payload["tools"]}
    assert slugs == {"ffuf", "katana"}
    for tool in payload["tools"]:
        assert "installed" in tool["status"]
        assert "install_hint" in tool["status"]


def test_missing_binary_is_reported_not_installed(app):
    with app.app_context():
        tool = get_tool("ffuf", binary="definitely-not-a-real-binary")
        assert tool.status().installed is False


def test_ffuf_requires_fuzz_keyword(app):
    with app.app_context(), pytest.raises(ToolError):
        get_tool("ffuf").validate_config({"url": "http://127.0.0.1/", "wordlist_path": "/tmp/w"})


def test_ffuf_rejects_invalid_url(app):
    with app.app_context(), pytest.raises(ToolError):
        get_tool("ffuf").validate_config({"url": "ftp://x/FUZZ", "wordlist_path": "/tmp/w"})


def test_ffuf_command_is_an_argv_list(app, tmp_path):
    wordlist = tmp_path / "w.txt"
    wordlist.write_text("admin\n")
    with app.app_context():
        tool = get_tool("ffuf")
        config = tool.validate_config(
            {"url": "http://127.0.0.1/FUZZ", "wordlist_path": str(wordlist)}
        )
        built = tool.build_command(config, tmp_path)
    assert isinstance(built.argv, list)
    assert all(isinstance(part, str) for part in built.argv)
    assert "-u" in built.argv and "http://127.0.0.1/FUZZ" in built.argv


def test_katana_command_is_an_argv_list(app, tmp_path):
    with app.app_context():
        tool = get_tool("katana")
        config = tool.validate_config({"urls": "http://127.0.0.1", "depth": 2})
        built = tool.build_command(config, tmp_path)
    assert isinstance(built.argv, list)
    assert "-jsonl" in built.argv


def test_wordlist_roots_are_independent(app):
    with app.app_context():
        ffuf = get_wordlist_manager("ffuf")
        katana = get_wordlist_manager("katana")
        assert ffuf.root != katana.root
        ffuf.save_upload("directories", "list.txt", _Upload(b"a\nb\n"))
        assert [w.id for w in ffuf.list_all()] == ["directories/list.txt"]
        assert katana.list_all() == []


def test_wordlist_upload_and_delete(app):
    with app.app_context():
        manager = get_wordlist_manager("ffuf")
        item = manager.save_upload("custom", "my list.txt", _Upload(b"one\ntwo\nthree\n"))
        assert item.entries == 3
        assert manager.preview(item.id)[0] == "one"
        manager.delete(item.id)
        assert manager.list_all() == []


@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "custom/../../etc/passwd", "/etc/passwd"])
def test_wordlist_path_traversal_is_rejected(app, bad_id):
    with app.app_context(), pytest.raises(WordlistError):
        get_wordlist_manager("ffuf").resolve(bad_id)


def test_ffuf_result_parsing_and_export(app, tmp_path):
    result_file = tmp_path / "results.json"
    result_file.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "input": {"FUZZ": "admin"},
                        "url": "http://t/admin",
                        "status": 200,
                        "length": 12,
                        "words": 3,
                        "lines": 1,
                        "content-type": "text/html",
                        "redirectlocation": "",
                        "duration": 1200000,
                        "host": "t",
                    }
                ]
            }
        )
    )
    with app.app_context():
        rows = get_tool("ffuf").parse_output(result_file, "")
    assert rows[0]["status"] == 200
    assert rows[0]["url"] == "http://t/admin"
    assert "http://t/admin" in parser.to_csv(rows, "ffuf")
    assert "http://t/admin" in parser.to_txt(rows)


def test_katana_result_parsing(app, tmp_path):
    result_file = tmp_path / "results.jsonl"
    result_file.write_text(
        json.dumps(
            {
                "request": {"method": "GET", "endpoint": "http://t/a", "source": "http://t/"},
                "response": {"status_code": 200, "headers": {"content_type": "text/html"}},
            }
        )
        + "\n"
    )
    with app.app_context():
        rows = get_tool("katana").parse_output(result_file, "")
    assert rows[0]["url"] == "http://t/a"
    assert rows[0]["method"] == "GET"
    assert rows[0]["status"] == 200


def test_scan_history_and_export_endpoints(app, client, tmp_path):
    with app.app_context():
        result_file = Path(tmp_path) / "results.jsonl"
        result_file.write_text(
            json.dumps({"request": {"endpoint": "http://t/a", "method": "GET"}}) + "\n"
        )
        scan = Scan(tool="katana", target="http://t", status=ScanStatus.COMPLETED.value)
        scan.command = ["katana", "-u", "http://t"]
        scan.config = {"urls": "http://t", "cookies": "session=secret"}
        scan.result_file = str(result_file)
        db.session.add(scan)
        db.session.commit()
        scan_id = scan.id
        assert "secret" not in json.dumps(scan.safe_config())

    assert client.get("/scans/history").status_code == 200
    assert client.get(f"/api/scans/{scan_id}/results").get_json()["results"][0]["url"] == (
        "http://t/a"
    )
    for fmt in ("json", "csv", "txt"):
        response = client.get(f"/api/scans/{scan_id}/export?format={fmt}")
        assert response.status_code == 200
        assert b"http://t/a" in response.data
