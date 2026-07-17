"""Deterministic audio QC -- no LLM calls (tier: scripts, cost: zero).

Checks: silence, clipping, loudness (target -14 LUFS), duration.

Usage:
    python qc.py <file.wav | directory>   # exits 1 if any file fails
"""

from __future__ import annotations

import sys
from pathlib import Path

import librosa
import numpy as np


def check_silence(y: np.ndarray, sr: int, max_silence_sec: float = 5.0) -> dict:
    """Flag long leading/trailing/internal silence."""
    intervals = librosa.effects.split(y, top_db=40)
    if len(intervals) == 0:
        return {"name": "silence", "passed": False, "details": "entirely silent"}
    lead = intervals[0][0] / sr
    trail = (len(y) - intervals[-1][1]) / sr
    gaps = [(intervals[i + 1][0] - intervals[i][1]) / sr for i in range(len(intervals) - 1)]
    worst = max([lead, trail] + gaps) if gaps else max(lead, trail)
    return {
        "name": "silence",
        "passed": worst <= max_silence_sec,
        "details": f"worst gap {worst:.1f}s (lead {lead:.1f}s, trail {trail:.1f}s)",
    }


def check_clipping(y: np.ndarray, threshold: float = 0.99) -> dict:
    """Fraction of samples at/near full scale."""
    frac = float(np.mean(np.abs(y) >= threshold))
    return {"name": "clipping", "passed": frac < 1e-4, "details": f"{frac:.2e} samples clipped"}


def check_loudness(y: np.ndarray, sr: int) -> dict:
    """Integrated loudness vs the -14 LUFS streaming target (pass window -20..-9)."""
    try:
        import pyloudnorm
        lufs = pyloudnorm.Meter(sr).integrated_loudness(y)
    except ImportError:  # fallback: RMS-based rough estimate
        rms = float(np.sqrt(np.mean(y ** 2)))
        lufs = 20 * np.log10(rms + 1e-12)
    return {"name": "loudness", "passed": -20.0 <= lufs <= -9.0, "details": f"{lufs:.1f} LUFS"}


def check_duration(y: np.ndarray, sr: int, min_sec: float = 60, max_sec: float = 300) -> dict:
    dur = len(y) / sr
    return {"name": "duration", "passed": min_sec <= dur <= max_sec, "details": f"{dur:.0f}s"}


def run_qc(path: str | Path) -> dict:
    """All checks for one file. Load errors fail the file rather than crash."""
    path = Path(path)
    try:
        y, sr = librosa.load(path, sr=None, mono=True)
    except Exception as e:  # noqa: BLE001
        return {"file": str(path), "passed": False,
                "checks": [{"name": "load", "passed": False, "details": str(e)}]}
    checks = [
        check_silence(y, sr),
        check_clipping(y),
        check_loudness(y, sr),
        check_duration(y, sr),
    ]
    return {"file": str(path), "passed": all(c["passed"] for c in checks), "checks": checks}


def prune_manifest(set_dir: Path, results: list[dict], min_keep: int = 2) -> None:
    """Drop QC-failing files from manifest.json so downstream steps skip them.

    Exits 1 only if fewer than min_keep tracks survive -- a couple of bad
    tracks shouldn't kill an otherwise good set.
    """
    import json
    mpath = set_dir / "manifest.json"
    if not mpath.exists():
        print("no manifest.json -- prune skipped")
        return
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    passed_names = {Path(r["file"]).name for r in results if r["passed"]}
    keep_idx = [i for i, f in enumerate(manifest["files"])
                if Path(f).name in passed_names]
    dropped = len(manifest["files"]) - len(keep_idx)
    manifest["files"] = [manifest["files"][i] for i in keep_idx]
    if manifest.get("tracks"):
        manifest["tracks"] = [manifest["tracks"][i] for i in keep_idx]
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"prune: kept {len(keep_idx)}, dropped {dropped}")
    if len(keep_idx) < min_keep:
        print(f"fewer than {min_keep} tracks survived QC -- aborting", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Deterministic audio QC.")
    p.add_argument("target", type=Path, help="wav/mp3 file or a set directory")
    p.add_argument("--prune", action="store_true",
                   help="drop failing files from manifest.json instead of exiting 1 "
                        "(pipeline keeps going with the good tracks)")
    p.add_argument("--min-keep", type=int, default=2,
                   help="with --prune: minimum surviving tracks (default 2)")
    args = p.parse_args()

    target = args.target
    files = sorted(target.glob("*.wav")) + sorted(target.glob("*.mp3")) \
        if target.is_dir() else [target]
    files = [f for f in files if f.name != "mix.wav"]
    if not files:
        print(f"no audio files in {target}")
        sys.exit(2)

    any_fail, results = False, []
    for f in files:
        r = run_qc(f)
        results.append(r)
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark}  {Path(r['file']).name}")
        for c in r["checks"]:
            print(f"      {'ok ' if c['passed'] else 'BAD'} {c['name']:<9} {c['details']}")
        any_fail |= not r["passed"]

    if args.prune and target.is_dir():
        prune_manifest(target, results, args.min_keep)
        sys.exit(0)  # pruning handled the failures
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
