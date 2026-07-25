"""Atlas Cloud ``suno/chirp-fenix`` backend for instrumental mix sources.

Atlas exposes asynchronous text-to-audio generation but no continuation API for
the Chirp models.  A long production is therefore a coherent set of distinct
instrumentals that the existing mixer crossfades and trims to exact length.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from .common import slugify
except ImportError:
    from common import slugify

BASE_URL = "https://api.atlascloud.ai/api/v1/model"


class AtlasAPIError(RuntimeError):
    pass


def _request(url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=raw, method="POST" if payload is not None else "GET",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AtlasAPIError(f"Atlas Cloud HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:600]}") from exc
    except urllib.error.URLError as exc:
        raise AtlasAPIError(f"Atlas Cloud network error: {exc.reason}") from exc
    if body.get("code") not in (None, 200):
        raise AtlasAPIError(f"Atlas Cloud error {body.get('code')}: {body.get('msg', 'unknown error')}")
    return body


def _wait(prediction_id: str, token: str, poll_seconds: float, timeout_seconds: float) -> list[str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        data = _request(f"{BASE_URL}/prediction/{prediction_id}", token).get("data") or {}
        status = str(data.get("status", "processing")).lower()
        if status in {"completed", "succeeded"}:
            outputs = [str(url) for url in data.get("outputs", []) if url]
            if outputs:
                return outputs
            raise AtlasAPIError(f"prediction {prediction_id} completed without audio URLs")
        if status == "failed":
            raise AtlasAPIError(f"prediction {prediction_id} failed: {data.get('error', 'unknown error')}")
        time.sleep(poll_seconds)
    raise AtlasAPIError(f"prediction {prediction_id} timed out after {timeout_seconds:g}s")


def _download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vibe2music/1.0"}), timeout=180) as response:
        destination.write_bytes(response.read())
    if destination.stat().st_size < 1024:
        raise AtlasAPIError(f"downloaded audio is unexpectedly small: {destination}")


def generate_set(plan: dict[str, Any], out_root: Path, *, model: str = "suno/chirp-fenix",
                 poll_seconds: float = 6.0, timeout_seconds: float = 900.0) -> Path:
    """Generate one reproducible instrumental source per planned track."""
    token = os.environ.get("ATLASCLOUD_API_KEY", "").strip()
    if not token:
        raise AtlasAPIError("ATLASCLOUD_API_KEY is required for --engine atlas")
    if model != "suno/chirp-fenix":
        raise AtlasAPIError("only suno/chirp-fenix is supported; it is the selected Atlas Cloud default")
    tracks = list(plan.get("tracks") or [])
    if not tracks:
        raise AtlasAPIError("prompt plan contains no tracks")
    out_dir = out_root / slugify(plan["set_title"])
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    entries: list[dict[str, Any]] = list(existing.get("atlas_tracks") or [])

    for track in tracks[len(entries):]:
        index = int(track["index"])
        destination = out_dir / f"{index:02d}-atlas-chirp-fenix.mp3"
        if destination.exists():
            raise AtlasAPIError(f"found {destination}; its manifest entry is missing, so refusing to spend another paid generation")
        payload = {"model": model, "prompt": track["prompt"][:2000], "make_instrumental": True}
        submitted = _request(f"{BASE_URL}/generateAudio", token, payload)
        prediction_id = (submitted.get("data") or {}).get("id")
        if not prediction_id:
            raise AtlasAPIError("Atlas Cloud accepted the generation without returning a prediction id")
        print(f"  Atlas {index}/{len(tracks)}: waiting for chirp-fenix")
        alternatives = _wait(str(prediction_id), token, poll_seconds, timeout_seconds)
        _download(alternatives[0], destination)
        entries.append({"index": index, "file": str(destination.resolve()), "prediction_id": prediction_id,
                        "selected_alternative": 0, "alternatives": alternatives})
        partial = {"set_title": plan["set_title"], "mood_tags": plan.get("mood_tags", []),
                   "target_duration_sec": plan.get("target_duration_sec"), "generator": "atlascloud.ai",
                   "model": model, "tracks": tracks, "files": [item["file"] for item in entries],
                   "atlas_tracks": entries, "failures": []}
        manifest_path.write_text(json.dumps(partial, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_dir
