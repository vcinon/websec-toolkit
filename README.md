# Web Security Toolkit

A Flask GUI for **authorized** web application security testing. It currently drives two tools:

| Tool | Purpose |
| --- | --- |
| [ffuf](https://github.com/ffuf/ffuf) | HTTP fuzzing — directories, files, parameters, virtual hosts |
| [katana](https://github.com/projectdiscovery/katana) | Crawling and endpoint discovery |

> **Only scan systems you own or have explicit permission to test.**

## Features

- Dashboard with per-tool detection (installed / version / binary path) and scan counters
- Dedicated ffuf and Katana configuration pages with Basic / Advanced / Expert disclosure
- **Independent wordlist libraries per tool** (`wordlists/ffuf`, `wordlists/katana`) with upload,
  rename, delete, categories, default selection, entry counts and last-used memory
- Read-only command preview with copy-to-clipboard, updated live as you edit the form
- Live scan console over Server-Sent Events (pause / resume / stop), never blocking the web worker
- Process manager with `QUEUED / RUNNING / COMPLETED / FAILED / STOPPED` states, start, stop,
  restart, delete, save; child processes run in their own process group and are cleaned up
- Parsed result viewers (ffuf status/URL/size/words/lines/redirect, Katana URL/method/status/
  content-type/source) with search, sort, filters, copy, open and JSON/CSV/TXT export
- Scan history in SQLite with configuration, generated command, timings, results and raw output
- Settings for theme, concurrency, timeouts, binary paths and binary re-detection

## Requirements

- Python 3.10+
- `ffuf` and/or `katana` on your `PATH` (or an explicit path configured in Settings).
  Binaries are **never** installed automatically.

```bash
go install github.com/ffuf/ffuf/v2@latest
go install github.com/projectdiscovery/katana/cmd/katana@latest
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # optional, but set SECRET_KEY for anything shared
python run.py
```

Open http://127.0.0.1:5000. On first start the app creates the instance/scan directories,
initialises SQLite, creates both wordlist directories and detects the tools; the result is shown
on the **Setup status** page.

## Layout

```text
app/
├── routes/      dashboard, ffuf, katana, scans, wordlists, settings (pages + JSON API)
├── tools/       SecurityTool base class + FfufTool / KatanaTool integrations
├── services/    process_manager, scan_manager, wordlist_manager, parser
├── models/      SQLAlchemy Scan and Setting models
├── templates/   Jinja2 templates
└── static/      CSS and vanilla JS
wordlists/
├── ffuf/        directories, files, parameters, subdomains, custom
└── katana/      crawl, extensions, headers, custom
```

### Katana wordlists

Katana is a crawler, not a fuzzer, so its lists map to real katana inputs only:

| Category | Katana flag | Use |
| --- | --- | --- |
| `crawl` | `-list` | seed URL lists |
| `extensions` | `-extension-match` | extensions to keep |
| `headers` | `-headers` | header/cookie file for authorized authenticated crawling |
| `custom` | — | anything else you keep around |

## API

```text
GET    /api/tools                       GET  /api/tools/<slug>          GET /api/stats
POST   /api/scans                       GET  /api/scans                 GET /api/scans/<id>
POST   /api/scans/preview               POST /api/scans/<id>/stop       POST /api/scans/<id>/pause
POST   /api/scans/<id>/resume           POST /api/scans/<id>/restart    POST /api/scans/<id>/save
DELETE /api/scans/<id>                  GET  /api/scans/<id>/results    GET /api/scans/<id>/export?format=json|csv|txt
GET    /api/scans/<id>/raw              GET  /api/scans/<id>/stream     (Server-Sent Events)
GET    /api/wordlists/<tool>            POST /api/wordlists/<tool>      POST /api/wordlists/<tool>/categories
GET    /api/wordlists/<tool>/<id>       PATCH /api/wordlists/<tool>/<id>  DELETE /api/wordlists/<tool>/<id>
POST   /api/wordlists/<tool>/default    POST /settings/detect
```

State-changing endpoints require the CSRF token (`X-CSRFToken` header; the UI sends it automatically).

## Security design

- Commands are built as argument arrays and executed with `subprocess.Popen([...])`.
  There is no code path that passes a user string to a shell — the GUI cannot be used as a
  generic command runner.
- Every field is validated server-side (URL scheme, integer ranges, status/size lists, regexes,
  header syntax, HTTP method allow-list).
- Wordlists are resolved as `category/name` inside the tool's own root; filenames are sanitised
  and resolved paths are asserted to stay inside that root, so path traversal is rejected.
  Uploads are extension- and size-limited and may not be empty.
- Subprocesses get a minimal environment (`PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`) and run in
  their own process group so the whole tree can be signalled; the app stops all children on exit.
- Tool output is stripped of ANSI/control characters server-side and inserted with `textContent`
  in the browser.
- Cookies and `Authorization` values are redacted in the stored configuration view and never logged.
- Errors are rendered as readable messages with a reason and a next step, never as tracebacks.

## Adding another tool

1. Add `app/tools/<tool>.py` with a `SecurityTool` subclass implementing `validate_config`,
   `build_command` and `parse_output`.
2. Register it in `TOOL_CLASSES` in `app/tools/__init__.py`.
3. Add `app/routes/<tool>.py` plus `app/templates/<tool>/index.html`, and register the blueprint.

The process manager, scan manager, history, exports and live console work unchanged.

## Deploying

`python run.py` starts Flask's threaded development server, which is fine for local use. Behind a
production server use a threaded worker and disable response buffering so SSE keeps streaming, e.g.

```bash
gunicorn --threads 8 --timeout 0 'app:create_app()'
```

Bind to localhost unless the host is trusted: the GUI executes scanning tools on the machine it
runs on.
