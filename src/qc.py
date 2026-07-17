"""Deterministic audio quality gate.

QC writes ``qc.json`` for the mixer and returns success when at least the
requested number of tracks pass. A single bad generation no longer destroys an
otherwise usable album; use ``--strict`` when a CLI caller wants every file to
pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np


def check_silence(y: np.ndarray, sr: int, max_silence_sec: float = 5.0) -> dict:
    intervals = librosa.effects.split(y, top_db=40)
    if len(intervals) == 0:
        return {"name": "silence", "passed": False, "details": "entirely silent"}
    lead = intervals[0][0] / sr
    trail = (len(y) - intervals[-1][1]) / sr
    gaps = [(intervals[i + 1][0] - intervals[i][1]) / sr for i in range(len(intervals) - 1)]
    worst = max([lead, trail] + gaps) if gaps else max(lead, trail)
    return {
        "name": "silence",
        # ``worst`` is usually a NumPy scalar; cast the comparison result so
        # the report can be serialized by the standard JSON encoder.
        "passed": bool(worst <= max_silence_sec),
        "details": f"worst gap {worst:.1f}s (lead {lead:.1f}s, trail {trail:.1f}s)",
    }


def check_clipping(y: np.ndarray, threshold: float = 0.99) -> dict:
    frac = float(np.mean(np.abs(y) >= threshold))
    return {"name": "clipping", "passed": frac < 1e-4, "details": f"{frac:.2e} samples clipped"}


def check_loudness(y: np.ndarray, sr: int, low: float = -20.0, high: float = -9.0) -> dict:
    try:
        import pyloudnorm

        lufs = float(pyloudnorm.Meter(sr).integrated_loudness(y))
    except ImportError:
        rms = float(np.sqrt(np.mean(y ** 2)))
        lufs = 20 * np.log10(rms + 1e-12)
    passed = np.isfinite(lufs) and low <= lufs <= high
    return {"name": "loudness", "passed": bool(passed), "details": f"{lufs:.1f} LUFS"}


def check_duration(y: np.ndarray, sr: int, min_sec: float = 60, max_sec: float = 300) -> dict:
    duration = len(y) / sr
    return {
        "name": "duration",
        "passed": bool(min_sec <= duration <= max_sec),
        "details": f"{duration:.0f}s",
    }


def run_qc(path: str | Path, max_silence_sec: float = 5.0) -> dict:
    path = Path(path)
    try:
        y, sr = librosa.load(path, sr=None, mono=True)
    except Exception as exc:  # noqa: BLE001 - a load error is a failed track
        return {"file": str(path), "passed": False,
                "checks": [{"name": "load", "passed": False, "details": str(exc)}]}
    checks = [
        check_silence(y, sr, max_silence_sec),
        check_clipping(y),
        check_loudness(y, sr),
        check_duration(y, sr),
    ]
    return {"file": str(path), "passed": all(item["passed"] for item in checks), "checks": checks}


def _files_for(target: Path) -> list[Path]:
    if not target.is_dir():
        return [target]
    manifest = target / "manifest.json"
    if manifest.exists():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        files = [Path(item) for item in payload.get("files", [])]
    else:
        files = sorted(target.glob("*.wav")) + sorted(target.glob("*.mp3"))
    return [path for path in files if path.exists() and path.name not in {"mix.wav", "master.wav"}]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic audio QC")
    parser.add_argument("target")
    parser.add_argument("--min-passed", type=int, default=1)
    parser.add_argument("--strict", action="store_true", help="require every input file to pass")
    parser.add_argument("--max-silence-sec", type=float, default=5.0)
    args = parser.parse_args()

    target = Path(args.target)
    files = _files_for(target)
    if not files:
        print(f"no audio files in {target}", file=sys.stderr)
        sys.exit(2)
    report = []
    for path in files:
        result = run_qc(path, args.max_silence_sec)
        report.append(result)
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {path.name}")
        for check in result["checks"]:
            print(f"      {'ok ' if check['passed'] else 'BAD'} {check['name']:<9} {check['details']}")

    out_dir = target if target.is_dir() else target.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "qc.json").write_text(json.dumps({"files": report}, indent=2), encoding="utf-8")
    passed = sum(1 for item in report if item["passed"])
    threshold_met = passed >= max(1, args.min_passed)
    if args.strict:
        threshold_met = threshold_met and passed == len(report)
    print(f"QC summary: {passed}/{len(report)} passed; report: {out_dir / 'qc.json'}")
    sys.exit(0 if threshold_met else 1)


if __name__ == "__main__":
    main()
