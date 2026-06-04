"""FastAPI server: serves the UI and exposes a Server-Sent Events trace stream."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import log
from .orchestrator import Orchestrator


ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "ui"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"


log.setup()
_logger = log.get("app")
_logger.info("startup root=%s logs=%s", ROOT, LOGS_DIR)

app = FastAPI(title="Multi-Agent Orchestration — Case Study C")


class RunRequest(BaseModel):
    request: str
    sources: list[dict[str, Any]] = []


@app.get("/api/samples")
def list_samples() -> JSONResponse:
    """List every sample file in data/."""
    samples = []
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        samples.append(
            {
                "name": path.stem,
                "title": data.get("title", path.stem.replace("_", " ").title()),
                "description": data.get("description", ""),
                "tag": data.get("tag", "happy"),
            }
        )
    return JSONResponse(samples)


@app.get("/api/samples/{name}")
def get_sample(name: str) -> JSONResponse:
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="sample not found")
    return JSONResponse(json.loads(path.read_text()))


@app.post("/api/run")
async def run_pipeline(body: RunRequest) -> StreamingResponse:
    """Server-Sent Events: each line is one trace event from the orchestrator."""
    orch = Orchestrator(body.model_dump())

    async def event_stream():
        async for event in orch.stream():
            payload = json.dumps(event.to_dict())
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/logs/{run_id}")
def get_run_log(run_id: str) -> JSONResponse:
    """Return the per-run log so the UI (or curl) can show what happened."""
    if "/" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="invalid run_id")
    path = ROOT / "runs" / run_id / "run.log"
    if not path.exists():
        raise HTTPException(status_code=404, detail="log not found")
    return JSONResponse({"run_id": run_id, "log": path.read_text(encoding="utf-8")})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


# Static UI assets (styles.css, app.js, etc.)
app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
