"""Small shared helpers used by the CLI pipeline and API worker."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, limit: int = 60) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "untitled").lower()).strip("-")
    return (value or "untitled")[:limit]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Read config.yaml, returning useful defaults when PyYAML is unavailable."""
    path = Path(path or ROOT / "config.yaml")
    if not path.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        # The production requirements include PyYAML. This fallback keeps dry
        # run/diagnostic commands readable in a minimal test environment.
        return {}


def atomic_write_json(path: str | Path, value: Any) -> None:
    """Write JSON without leaving a half-written state file after a restart."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def default_track_count(target_minutes: float, max_track_sec: int = 240,
                        crossfade_sec: int = 4) -> int:
    """Return enough distinct generated tracks to cover a target duration."""
    target_sec = max(60.0, float(target_minutes) * 60.0)
    effective_track_sec = max(1, max_track_sec - crossfade_sec)
    return max(3, min(24, int((target_sec + effective_track_sec - 1) // effective_track_sec)))


def target_track_duration(target_minutes: float, n_tracks: int,
                          crossfade_sec: int = 4, minimum: int = 120,
                          maximum: int = 240) -> int:
    """Approximate a per-track duration that makes a crossfaded set hit target."""
    target_sec = float(target_minutes) * 60.0
    duration = round((target_sec + max(0, n_tracks - 1) * crossfade_sec) / n_tracks)
    return max(minimum, min(maximum, duration))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
