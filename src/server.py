"""Local API and job queue for the vibe2music web application.

Only one job runs at a time so repeated browser clicks cannot exhaust the paid
provider's concurrency allowance.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .common import atomic_write_json, env_bool, now_iso, ROOT, slugify
except ImportError:  # direct script execution
    from common import atomic_write_json, env_bool, now_iso, ROOT, slugify

HERE = ROOT / "src"
JOBS_DIR = Path(os.environ.get("JOBS_DIR", str(ROOT / "jobs")))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
API_TOKEN = os.environ.get("API_TOKEN", "")
MAX_IMAGE_BYTES = 12 * 1024 * 1024
TERMINAL_STATUSES = {
    "ready_for_review", "uploaded_private", "uploaded_unlisted",
    "uploaded_public", "failed", "cancelled",
}

app = FastAPI(title="vibe2music production API", version="2.0")
allowed_origins = [item.strip() for item in os.environ.get("UI_ORIGINS", "*").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

STATE_LOCK = threading.RLock()
QUEUE: queue.Queue[str] = queue.Queue()
ENQUEUED: set[str] = set()
CANCEL_EVENTS: dict[str, threading.Event] = {}
WORKER_STARTED = False


def auth(request: Request) -> None:
    if not API_TOKEN:
        raise HTTPException(503, "API_TOKEN is not configured")
    if request.headers.get("authorization") != f"Bearer {API_TOKEN}":
        raise HTTPException(401, "bad token")


class JobIn(BaseModel):
    vibe: str = Field(min_length=1, max_length=1000)
    instruments: str = Field(default="", max_length=500)
    tracks: int | None = Field(default=None, ge=3, le=24)
    target_minutes: float = Field(default=45.0, ge=1.0, le=180.0)
    engine: Literal["ace-step", "atlas"] = "atlas"
    atlas_model: str = Field(default="suno/chirp-fenix", min_length=2, max_length=64)
    device: Literal["auto", "cuda", "mps", "cpu"] = "auto"
    device_id: int = Field(default=0, ge=0, le=15)


class UploadIn(BaseModel):
    privacy: Literal["private", "unlisted", "public"] = "private"
    publish_at: str | None = None


def _job_path(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{8}", job_id):
        raise HTTPException(400, "bad job id")
    path = JOBS_DIR / job_id
    if not path.is_dir():
        raise HTTPException(404, "job not found")
    return path


def _state(job_dir: Path) -> dict[str, Any]:
    file = job_dir / "state.json"
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"corrupt job state: {job_dir.name}") from exc


def _set_state(job_dir: Path, **updates: Any) -> dict[str, Any]:
    with STATE_LOCK:
        state = _state(job_dir)
        state.update(updates)
        state["updated_at"] = now_iso()
        atomic_write_json(job_dir / "state.json", state)
        return state


def _append_log(job_dir: Path, text: str) -> None:
    with (job_dir / "log.txt").open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _hardware() -> dict[str, Any]:
    result: dict[str, Any] = {"engines": ["ace-step", "atlas"], "cuda": False, "device": "unknown", "atlas_configured": bool(os.environ.get("ATLASCLOUD_API_KEY"))}
    try:
        import torch

        result["torch"] = torch.__version__
        result["cuda"] = bool(torch.cuda.is_available())
        result["device_count"] = int(torch.cuda.device_count())
        if result["cuda"]:
            result["device"] = torch.cuda.get_device_name(0)
            result["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
    except Exception as exc:  # noqa: BLE001
        result["error"] = type(exc).__name__
    return result


def _queue_job(job_id: str) -> None:
    with STATE_LOCK:
        if job_id in ENQUEUED:
            return
        ENQUEUED.add(job_id)
    QUEUE.put(job_id)


def _recover_jobs() -> None:
    for job_dir in sorted(JOBS_DIR.iterdir()):
        if not job_dir.is_dir() or not (job_dir / "state.json").exists():
            continue
        state = _state(job_dir)
        status = str(state.get("status", ""))
        if status == "queued" or status.startswith("running:"):
            _set_state(job_dir, status="queued", current_step="waiting")
            _queue_job(job_dir.name)


def _start_worker() -> None:
    global WORKER_STARTED
    with STATE_LOCK:
        if WORKER_STARTED:
            return
        WORKER_STARTED = True
    _recover_jobs()
    threading.Thread(target=_worker_loop, name="vibe2music-worker", daemon=True).start()


def _worker_loop() -> None:
    while True:
        job_id = QUEUE.get()
        try:
            _run_job(job_id)
        except Exception as exc:  # noqa: BLE001
            job_dir = JOBS_DIR / job_id
            if job_dir.is_dir():
                _append_log(job_dir, f"\nWORKER ERROR: {type(exc).__name__}: {exc}\n")
                _set_state(job_dir, status="failed", error=f"{type(exc).__name__}: {exc}", progress=0)
        finally:
            with STATE_LOCK:
                ENQUEUED.discard(job_id)
                CANCEL_EVENTS.pop(job_id, None)
            QUEUE.task_done()


def _run_step(job_dir: Path, job_id: str, label: str, index: int,
              total: int, script: str, *args: str) -> bool:
    cancel = CANCEL_EVENTS.setdefault(job_id, threading.Event())
    if cancel.is_set():
        _set_state(job_dir, status="cancelled", current_step=None)
        return False
    _set_state(job_dir, status=f"running:{label}", current_step=label,
               progress=round(index / total * 100))
    command = [sys.executable, str(HERE / script), *args]
    _append_log(job_dir, f"\n=== {label} ===\n$ {' '.join(command)}\n")
    process = subprocess.Popen(
        command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if line:
            _append_log(job_dir, line)
        if cancel.is_set() and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            _set_state(job_dir, status="cancelled", current_step=None)
            return False
        if not line and process.poll() is not None:
            break
    return_code = process.wait()
    if return_code != 0:
        _set_state(job_dir, status=f"failed:{label}", error=f"{label} exited with {return_code}")
        return False
    _set_state(job_dir, progress=round((index + 1) / total * 100))
    return True


def _run_job(job_id: str) -> None:
    job_dir = JOBS_DIR / job_id
    state = _state(job_dir)
    spec_payload = state.get("spec") or {
        "vibe": state.get("vibe", ""),
        "instruments": state.get("instruments", ""),
        "tracks": state.get("tracks"),
        "target_minutes": state.get("target_minutes", 45),
        "engine": "atlas",
        "device": "auto",
        "device_id": 0,
    }
    spec = JobIn.model_validate(spec_payload)
    total = 8
    prompts = job_dir / "prompts.json"
    image_path = Path(state["image_path"]) if state.get("image_path") else None

    compile_args = [
        state["vibe"], "--instruments", spec.instruments,
        "--target-minutes", str(spec.target_minutes), "--out", str(prompts),
    ]
    if spec.tracks is not None:
        compile_args += ["--tracks", str(spec.tracks)]
    if image_path:
        compile_args += ["--image", str(image_path)]
    if not _run_step(job_dir, job_id, "planning", 0, total, "prompt_compiler.py", *compile_args):
        return

    if spec.engine == "atlas":
        generate_script = "generate_atlas.py"
        generate_args = [str(prompts), "--out", str(job_dir), "--model", spec.atlas_model]
    else:
        generate_script = "generate.py"
        generate_args = [str(prompts), "--out", str(job_dir), "--device", spec.device, "--device-id", str(spec.device_id)]
        if spec.device == "cpu":
            generate_args.append("--allow-cpu")
    if not _run_step(job_dir, job_id, "generation", 1, total, generate_script, *generate_args):
        return

    plan = json.loads(prompts.read_text(encoding="utf-8"))
    set_dir = job_dir / slugify(plan["set_title"])
    _set_state(job_dir, set_dir=str(set_dir), set_title=plan["set_title"])
    if not _run_step(job_dir, job_id, "quality_control", 2, total, "qc.py", str(set_dir), "--min-passed", "1"):
        return
    if not _run_step(job_dir, job_id, "assembly", 3, total, "mix.py", str(set_dir), "--target-minutes", str(spec.target_minutes)):
        return
    if not _run_step(job_dir, job_id, "metadata", 4, total, "metadata.py", str(set_dir), "--vibe", state["vibe"]):
        return

    if image_path:
        cover_path = image_path
        _set_state(job_dir, current_step="cover", progress=round(5 / total * 100), cover_path=str(cover_path))
    else:
        cover_path = set_dir / "cover.png"
        if not _run_step(
            job_dir, job_id, "cover", 5, total, "cover.py",
            "--title", plan["set_title"], "--vibe", state["vibe"],
            "--minutes", str(spec.target_minutes), "--out", str(cover_path),
        ):
            return
    _set_state(job_dir, cover_path=str(cover_path))
    video_path: Path | None = None
    if shutil.which("ffmpeg"):
        if not _run_step(job_dir, job_id, "render", 6, total, "render.py", str(set_dir), "--image", str(cover_path)):
            return
        video_path = set_dir / "video.mp4"
    else:
        _append_log(job_dir, "\nFFmpeg not found: audio and cover are ready; MP4 rendering was skipped.\n")

    _set_state(
        job_dir, status="ready_for_review", current_step=None, progress=100,
        artifacts={
            "audio": str(set_dir / "preview.mp3" if (set_dir / "preview.mp3").exists() else set_dir / "mix.wav"),
            "master_audio": str(set_dir / "mix.wav"),
            "video": str(video_path) if video_path else None,
            "metadata": str(set_dir / "metadata.json"),
            "cover": str(cover_path),
        },
        video_available=video_path is not None,
    )


async def _parse_job_request(request: Request) -> tuple[JobIn, UploadFile | None]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload: dict[str, Any] = {
            "vibe": str(form.get("vibe", "")),
            "instruments": str(form.get("instruments", "")),
            "tracks": form.get("tracks") or None,
            "target_minutes": form.get("target_minutes") or 45,
            "engine": str(form.get("engine", "atlas")),
            "atlas_model": str(form.get("atlas_model", "suno/chirp-fenix")),
            "device": str(form.get("device", "auto")),
            "device_id": form.get("device_id") or 0,
        }
        image = form.get("image")
        if image is None or not hasattr(image, "read"):
            image = None
    else:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(400, "expected JSON or multipart form data") from exc
        image = None
    try:
        return JobIn.model_validate(payload), image
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc


async def _save_image(job_dir: Path, image: UploadFile | None) -> Path | None:
    if image is None or not image.filename:
        return None
    suffix = Path(image.filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(415, "cover image must be JPG, PNG, or WEBP")
    contents = await image.read()
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "cover image is larger than 12 MB")
    destination = job_dir / f"image{suffix}"
    destination.write_bytes(contents)
    return destination


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    auth(request)
    return {"ok": True, "worker": WORKER_STARTED, "hardware": _hardware()}




@app.post("/jobs")
async def create_job(request: Request) -> dict[str, Any]:
    auth(request)
    spec, image = await _parse_job_request(request)
    _start_worker()
    job_id = uuid.uuid4().hex[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    image_path = await _save_image(job_dir, image)
    state = {
        "id": job_id,
        "vibe": spec.vibe,
        "spec": spec.model_dump(),
        "target_minutes": spec.target_minutes,
        "tracks": spec.tracks,
        "status": "queued",
        "progress": 0,
        "created_at": now_iso(),
        "image_path": str(image_path) if image_path else None,
    }
    atomic_write_json(job_dir / "state.json", state)
    _append_log(job_dir, f"created {now_iso()}\n")
    CANCEL_EVENTS[job_id] = threading.Event()
    _queue_job(job_id)
    return {"id": job_id, "status": "queued"}


@app.get("/jobs")
def list_jobs(request: Request) -> list[dict[str, Any]]:
    auth(request)
    jobs = []
    for job_dir in JOBS_DIR.iterdir():
        if job_dir.is_dir() and (job_dir / "state.json").exists():
            jobs.append(_state(job_dir))
    return sorted(jobs, key=lambda item: item.get("created_at", ""), reverse=True)


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    auth(request)
    job_dir = _job_path(job_id)
    state = _state(job_dir)
    if state.get("status") in TERMINAL_STATUSES:
        return state
    CANCEL_EVENTS.setdefault(job_id, threading.Event()).set()
    if state.get("status") == "queued":
        _set_state(job_dir, status="cancelled", current_step=None)
    return _state(job_dir)


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, request: Request) -> dict[str, Any]:
    auth(request)
    job_dir = _job_path(job_id)
    state = _state(job_dir)
    if str(state.get("status", "")).startswith("running"):
        raise HTTPException(409, "job is still running")
    _set_state(job_dir, status="queued", progress=0, error=None, current_step="waiting")
    CANCEL_EVENTS[job_id] = threading.Event()
    _start_worker()
    _queue_job(job_id)
    return {"id": job_id, "status": "queued"}


def _artifact(job_id: str, key: str, media_type: str, download: bool = False) -> FileResponse:
    state = _state(_job_path(job_id))
    raw_path = state.get("artifacts", {}).get(key)
    if not raw_path:
        raise HTTPException(404, f"{key} not ready")
    path = Path(raw_path)
    if not path.is_file():
        raise HTTPException(404, f"{key} not ready")
    return FileResponse(path, media_type=media_type, filename=path.name if download else None)


@app.get("/jobs/{job_id}/audio")
def get_audio(job_id: str, request: Request) -> FileResponse:
    auth(request)
    return _artifact(job_id, "audio", "audio/mpeg")


@app.get("/jobs/{job_id}/download/audio")
def download_audio(job_id: str, request: Request) -> FileResponse:
    auth(request)
    return _artifact(job_id, "master_audio", "audio/wav", download=True)


@app.get("/jobs/{job_id}/video")
def get_video(job_id: str, request: Request) -> FileResponse:
    auth(request)
    return _artifact(job_id, "video", "video/mp4")


@app.get("/jobs/{job_id}/download/video")
def download_video(job_id: str, request: Request) -> FileResponse:
    auth(request)
    return _artifact(job_id, "video", "video/mp4", download=True)


@app.get("/jobs/{job_id}/cover")
def get_cover(job_id: str, request: Request) -> FileResponse:
    auth(request)
    return _artifact(job_id, "cover", "image/png")


@app.get("/jobs/{job_id}/download/cover")
def download_cover(job_id: str, request: Request) -> FileResponse:
    auth(request)
    return _artifact(job_id, "cover", "image/png", download=True)


@app.get("/jobs/{job_id}/log")
def get_log(job_id: str, request: Request) -> dict[str, str]:
    auth(request)
    job_dir = _job_path(job_id)
    return {"log": (job_dir / "log.txt").read_text(encoding="utf-8") if (job_dir / "log.txt").exists() else ""}


@app.get("/jobs/{job_id}/metadata")
def get_metadata(job_id: str, request: Request) -> dict[str, Any]:
    auth(request)
    state = _state(_job_path(job_id))
    file = Path(state.get("artifacts", {}).get("metadata", ""))
    if not file.is_file():
        raise HTTPException(404, "metadata not ready")
    return json.loads(file.read_text(encoding="utf-8"))


@app.put("/jobs/{job_id}/metadata")
async def put_metadata(job_id: str, request: Request) -> dict[str, bool]:
    auth(request)
    state = _state(_job_path(job_id))
    body = await request.json()
    if not isinstance(body, dict) or not body.get("title") or "description" not in body:
        raise HTTPException(422, "metadata must contain title and description")
    file = Path(state.get("artifacts", {}).get("metadata", ""))
    if not file.is_file():
        raise HTTPException(404, "metadata not ready")
    atomic_write_json(file, body)
    return {"ok": True}


@app.post("/jobs/{job_id}/upload")
def do_upload(job_id: str, request: Request, payload: UploadIn | None = None) -> dict[str, Any]:
    auth(request)
    job_dir = _job_path(job_id)
    state = _state(job_dir)
    if state.get("status") not in {"ready_for_review", "uploaded_private", "uploaded_unlisted"}:
        raise HTTPException(409, "job is not ready for review")
    payload = payload or UploadIn()
    if payload.privacy == "public" and not env_bool("V2M_ALLOW_PUBLIC_UPLOAD", False):
        raise HTTPException(403, "public upload is disabled; set V2M_ALLOW_PUBLIC_UPLOAD=true explicitly")
    set_dir = state.get("set_dir")
    if not set_dir:
        raise HTTPException(404, "render not ready")
    command = [sys.executable, str(HERE / "upload.py"), str(set_dir), "--privacy", payload.privacy]
    if payload.publish_at:
        command += ["--publish-at", payload.publish_at]
    result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)
    _append_log(job_dir, f"\n=== youtube upload ===\n{result.stdout}{result.stderr}")
    if result.returncode != 0:
        raise HTTPException(500, result.stderr[-1000:] or "YouTube upload failed")
    status = f"uploaded_{payload.privacy}"
    match = re.search(r"https://youtu\.be/([A-Za-z0-9_-]+)", result.stdout)
    _set_state(job_dir, status=status, youtube_video_id=match.group(1) if match else None, publish_at=payload.publish_at)
    return {"ok": True, "status": status, "video_id": match.group(1) if match else None}


_start_worker()
app.mount("/", StaticFiles(directory=str(ROOT / "ui"), html=True), name="ui")
