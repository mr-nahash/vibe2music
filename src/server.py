"""GPU-box API server -- backend for the Cloudflare control panel.

Run on the RunPod pod:  API_TOKEN=<secret> uvicorn server:app --host 0.0.0.0 --port 8000
Expose the port via RunPod's proxy (it gives you an https URL); paste that URL
plus your token into the Cloudflare UI settings.

Endpoints (all require Authorization: Bearer <API_TOKEN>):
  POST /jobs {vibe, instruments, tracks}  -> start a pipeline run (background)
  GET  /jobs                              -> list jobs + status
  GET  /jobs/{id}/audio                   -> stream mix.wav for review
  GET  /jobs/{id}/metadata  /  PUT ...    -> read / edit metadata before publish
  POST /jobs/{id}/upload                  -> upload to YouTube (private)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

HERE = Path(__file__).parent
JOBS_DIR = Path(os.environ.get("JOBS_DIR", "jobs"))
JOBS_DIR.mkdir(exist_ok=True)
API_TOKEN = os.environ.get("API_TOKEN") or sys.exit("set API_TOKEN env var")

app = FastAPI(title="vibe2music")
app.add_middleware(  # UI is on a different origin (Cloudflare Pages)
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def auth(request: Request) -> None:
    if request.headers.get("authorization") != f"Bearer {API_TOKEN}":
        raise HTTPException(401, "bad token")


class JobIn(BaseModel):
    vibe: str
    instruments: str = ""
    tracks: int = 8


def _job_path(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{8}", job_id):
        raise HTTPException(400, "bad job id")
    return JOBS_DIR / job_id


def _state(job_dir: Path) -> dict:
    f = job_dir / "state.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _set_state(job_dir: Path, **kw) -> None:
    s = _state(job_dir)
    s.update(kw)
    (job_dir / "state.json").write_text(json.dumps(s), encoding="utf-8")


def _run_pipeline(job_dir: Path, spec: JobIn) -> None:
    """Background thread: compile -> generate -> qc -> mix -> render -> metadata."""
    def step(name: str, *args: str) -> bool:
        _set_state(job_dir, status=f"running:{name}")
        r = subprocess.run([sys.executable, str(HERE / name), *args],
                           capture_output=True, text=True)
        (job_dir / "log.txt").open("a").write(f"\n=== {name} ===\n{r.stdout}{r.stderr}")
        if r.returncode != 0:
            _set_state(job_dir, status=f"failed:{name}")
            return False
        return True

    prompts = job_dir / "prompts.json"
    if not step("prompt_compiler.py", spec.vibe, "--instruments", spec.instruments,
                "--tracks", str(spec.tracks), "--out", str(prompts)):
        return
    if not step("generate.py", str(prompts), "--out", str(job_dir)):
        return
    plan = json.loads(prompts.read_text(encoding="utf-8"))
    set_dir = job_dir / re.sub(r"[^a-z0-9]+", "-", plan["set_title"].lower()).strip("-")[:60]
    _set_state(job_dir, set_dir=str(set_dir), set_title=plan["set_title"])
    for name, args in [("qc.py", [str(set_dir)]), ("mix.py", [str(set_dir)]),
                       ("metadata.py", [str(set_dir)])]:
        if not step(name, *args):
            return
    # Video needs a cover image; use image.jpg dropped into the job dir, else skip.
    img = job_dir / "image.jpg"
    if img.exists():
        if not step("render.py", str(set_dir), "--image", str(img)):
            return
    _set_state(job_dir, status="ready_for_review")


@app.post("/jobs", dependencies=[Depends(auth)])
def create_job(spec: JobIn) -> dict:
    job_id = uuid.uuid4().hex[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()
    _set_state(job_dir, id=job_id, vibe=spec.vibe, status="queued")
    threading.Thread(target=_run_pipeline, args=(job_dir, spec), daemon=True).start()
    return {"id": job_id}


@app.get("/jobs", dependencies=[Depends(auth)])
def list_jobs() -> list[dict]:
    return sorted((_state(d) for d in JOBS_DIR.iterdir() if d.is_dir()),
                  key=lambda s: s.get("id", ""), reverse=True)


@app.get("/jobs/{job_id}/audio", dependencies=[Depends(auth)])
def get_audio(job_id: str) -> FileResponse:
    s = _state(_job_path(job_id))
    mix = Path(s.get("set_dir", "")) / "mix.wav"
    if not mix.exists():
        raise HTTPException(404, "mix not ready")
    return FileResponse(mix, media_type="audio/wav")


@app.get("/jobs/{job_id}/metadata", dependencies=[Depends(auth)])
def get_metadata(job_id: str) -> dict:
    s = _state(_job_path(job_id))
    f = Path(s.get("set_dir", "")) / "metadata.json"
    if not f.exists():
        raise HTTPException(404, "metadata not ready")
    return json.loads(f.read_text(encoding="utf-8"))


@app.put("/jobs/{job_id}/metadata", dependencies=[Depends(auth)])
async def put_metadata(job_id: str, request: Request) -> dict:
    s = _state(_job_path(job_id))
    body = await request.json()
    (Path(s["set_dir"]) / "metadata.json").write_text(
        json.dumps(body, indent=2), encoding="utf-8")
    return {"ok": True}


@app.post("/jobs/{job_id}/upload", dependencies=[Depends(auth)])
def do_upload(job_id: str) -> dict:
    job_dir = _job_path(job_id)
    s = _state(job_dir)
    r = subprocess.run([sys.executable, str(HERE / "upload.py"), s["set_dir"],
                        "--privacy", "private"], capture_output=True, text=True)
    (job_dir / "log.txt").open("a").write(f"\n=== upload ===\n{r.stdout}{r.stderr}")
    if r.returncode != 0:
        raise HTTPException(500, r.stderr[-500:])
    _set_state(job_dir, status="uploaded_private")
    return {"ok": True, "note": "uploaded private -- publish from YouTube Studio"}
