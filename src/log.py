"""Logging setup.

Two destinations:
  - logs/app.log         — rotating, all app events
  - runs/<run_id>/run.log — per-run, attached by the orchestrator

Format is one line per event with a stable prefix so logs are grep-friendly
and machine-readable without needing a parser.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
APP_LOG = LOG_DIR / "app.log"

_FORMAT = "%(asctime)s %(levelname)-5s %(name)-20s %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"

_configured = False


def setup(level: int = logging.INFO) -> None:
    """Idempotent. Configure root logger with a console handler and a rotating
    file handler. Safe to call from FastAPI startup and from tests."""
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any pre-existing handlers (uvicorn installs its own) so output
    # has one consistent format.
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(_FORMAT, _DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(level)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        APP_LOG, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    # Quiet down very chatty third-party loggers — keep ours visible.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    _configured = True


def attach_run_log(run_id: str, run_dir: Path) -> logging.Handler:
    """Attach a per-run file handler. The caller must detach it on completion."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    # Tag every record with the run_id so the rotating app.log can be filtered.
    handler.addFilter(lambda rec: setattr(rec, "run_id", run_id) or True)
    logging.getLogger().addHandler(handler)
    return handler


def detach_handler(handler: logging.Handler) -> None:
    logging.getLogger().removeHandler(handler)
    handler.close()


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
