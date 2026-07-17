"""Build an exact-length, crossfaded mix from generated tracks."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

TARGET_LUFS = -14.0
CROSSFADE_SEC = 4.0
SR = 44100


def _load_norm(path: Path, target_lufs: float = TARGET_LUFS) -> np.ndarray:
    import librosa
    import pyloudnorm

    y, _ = librosa.load(path, sr=SR, mono=True)
    lufs = float(pyloudnorm.Meter(SR).integrated_loudness(y))
    if np.isfinite(lufs):
        y = y * (10 ** ((target_lufs - lufs) / 20))
    return np.clip(y, -1.0, 1.0).astype(np.float32)


def _crossfade(a: np.ndarray, b: np.ndarray, fade_samples: int) -> np.ndarray:
    n = min(fade_samples, len(a), len(b))
    if n <= 0:
        return np.concatenate([a, b])
    t = np.linspace(0, np.pi / 2, n, dtype=np.float32)
    blended = a.copy()
    blended[-n:] = blended[-n:] * np.cos(t) + b[:n] * np.sin(t)
    return np.concatenate([blended, b[n:]])


def _fmt_ts(sec: float) -> str:
    h, rem = divmod(max(0, int(sec)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _manifest_files(set_dir: Path) -> tuple[list[Path], dict[str, str], dict[str, bool]]:
    manifest_path = set_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = [Path(item) for item in manifest.get("files", [])]
        titles = {
            Path(file_name).name: track.get("title", Path(file_name).stem)
            for file_name, track in zip(manifest.get("files", []), manifest.get("tracks", []))
        }
    else:
        files, titles = sorted(set_dir.glob("*.wav")), {}
    qc_status: dict[str, bool] = {}
    qc_path = set_dir / "qc.json"
    if qc_path.exists():
        report = json.loads(qc_path.read_text(encoding="utf-8"))
        qc_status = {str(Path(item["file"]).resolve()): bool(item["passed"])
                     for item in report.get("files", [])}
    files = [
        path for path in files
        if path.exists() and path.name not in {"mix.wav", "master.wav"}
        and qc_status.get(str(path.resolve()), True)
    ]
    return files, titles, qc_status


def _write_preview(wav: Path) -> Path | None:
    """Create a browser-friendly preview without changing the master WAV."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    preview = wav.with_name("preview.mp3")
    result = subprocess.run([
        ffmpeg, "-y", "-i", str(wav), "-vn", "-codec:a", "libmp3lame",
        "-b:a", "160k", str(preview),
    ], capture_output=True, text=True)
    return preview if result.returncode == 0 and preview.exists() else None


def build_mix(set_dir: Path, loops: int = 1, target_duration_sec: float | None = None,
              crossfade_sec: float = CROSSFADE_SEC, fade_out_sec: float = 3.0,
              target_lufs: float = TARGET_LUFS) -> tuple[Path, Path]:
    """Return ``(master_wav, chapters_txt)`` and trim/pad to the target exactly."""
    files, titles, _ = _manifest_files(set_dir)
    if not files:
        raise AssertionError(f"no QC-passed tracks found in {set_dir}")
    if target_duration_sec is not None and target_duration_sec <= 0:
        raise ValueError("target_duration_sec must be positive")

    fade = int(max(0.0, crossfade_sec) * SR)
    mix: np.ndarray | None = None
    chapters: list[str] = []
    used_tracks = 0
    loop_limit = max(1, int(loops))
    if target_duration_sec is not None:
        # One complete set is preferred; repeat only as a resilience fallback
        # when a short custom plan cannot cover the requested target.
        estimated_total = sum(sf.info(path).duration for path in files) - max(0, len(files) - 1) * crossfade_sec
        loop_limit = max(loop_limit, int(math.ceil(float(target_duration_sec) / max(1.0, estimated_total))))

    for loop in range(loop_limit):
        for path in files:
            y = _load_norm(path, target_lufs)
            if mix is not None and target_duration_sec is not None and len(mix) >= int(target_duration_sec * SR):
                break
            start = 0.0 if mix is None else max(0.0, (len(mix) - fade) / SR)
            base_title = titles.get(path.name) or path.stem.split("-", 1)[-1].replace("-", " ").title()
            title = base_title if loop == 0 else f"{base_title} (variation {loop + 1})"
            chapters.append(f"{_fmt_ts(start)} {title}")
            mix = y if mix is None else _crossfade(mix, y, fade)
            used_tracks += 1
        if target_duration_sec is not None and mix is not None and len(mix) >= int(target_duration_sec * SR):
            break

    assert mix is not None
    if target_duration_sec is not None:
        desired_samples = int(round(float(target_duration_sec) * SR))
        if len(mix) < desired_samples:
            # This should only occur for a malformed/very short track set. Pad
            # with silence rather than silently returning a shorter video.
            mix = np.pad(mix, (0, desired_samples - len(mix)))
        else:
            mix = mix[:desired_samples]
        fade_samples = min(int(fade_out_sec * SR), len(mix))
        if fade_samples > 0:
            mix[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        target_chapters = float(target_duration_sec)
        chapters = [line for line in chapters if _chapter_seconds(line) < target_chapters]

    out_wav = set_dir / "mix.wav"
    sf.write(out_wav, mix, SR, subtype="PCM_16")
    out_chapters = set_dir / "chapters.txt"
    out_chapters.write_text("\n".join(chapters) + "\n", encoding="utf-8")
    _write_preview(out_wav)
    (set_dir / "mix_manifest.json").write_text(json.dumps({
        "duration_sec": len(mix) / SR,
        "target_duration_sec": target_duration_sec,
        "track_count": used_tracks,
        "source_track_count": len(files),
        "crossfade_sec": crossfade_sec,
        "target_lufs": target_lufs,
    }, indent=2), encoding="utf-8")
    return out_wav, out_chapters


def _chapter_seconds(line: str) -> int:
    timestamp = line.split(" ", 1)[0]
    parts = [int(item) for item in timestamp.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a target-length YouTube mix")
    parser.add_argument("set_dir", type=Path)
    parser.add_argument("--loops", type=int, default=1)
    parser.add_argument("--target-minutes", type=float, default=None)
    parser.add_argument("--target-seconds", type=float, default=None)
    parser.add_argument("--crossfade-sec", type=float, default=CROSSFADE_SEC)
    args = parser.parse_args()
    target = args.target_seconds if args.target_seconds is not None else (
        args.target_minutes * 60 if args.target_minutes is not None else None
    )
    wav, chapters = build_mix(
        args.set_dir, loops=args.loops, target_duration_sec=target,
        crossfade_sec=args.crossfade_sec,
    )
    print(f"mix: {wav} ({sf.info(wav).duration / 60:.2f} min)\nchapters: {chapters}")


if __name__ == "__main__":
    main()
