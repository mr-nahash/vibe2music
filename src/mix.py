"""Mix builder: QC-passed tracks -> one long mix WAV + YouTube chapter list.

No LLM (tier: scripts). Normalizes each track to target LUFS, joins with
equal-power crossfades, writes chapters.txt for the video description.

Usage:
    python mix.py <set_dir>            # uses manifest.json track order if present
    python mix.py <set_dir> --loops 2  # repeat the set to lengthen the mix
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

TARGET_LUFS = -14.0
CROSSFADE_SEC = 4.0
SR = 44100


def _load_norm(path: Path) -> np.ndarray:
    """Load mono at SR and gain-normalize to TARGET_LUFS."""
    import librosa
    import pyloudnorm
    y, _ = librosa.load(path, sr=SR, mono=True)
    lufs = pyloudnorm.Meter(SR).integrated_loudness(y)
    y = y * (10 ** ((TARGET_LUFS - lufs) / 20))
    return np.clip(y, -1.0, 1.0)


def _crossfade(a: np.ndarray, b: np.ndarray, fade_samples: int) -> np.ndarray:
    """Equal-power crossfade a into b."""
    n = min(fade_samples, len(a), len(b))
    t = np.linspace(0, np.pi / 2, n)
    a = a.copy()
    a[-n:] = a[-n:] * np.cos(t) + b[:n] * np.sin(t)
    return np.concatenate([a, b[n:]])


def _fmt_ts(sec: float) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_mix(set_dir: Path, loops: int = 1,
              target_minutes: float | None = None) -> tuple[Path, Path]:
    """Returns (mix_wav_path, chapters_txt_path).

    target_minutes: auto-compute loops so the mix reaches at least this length
    (a short set is repeated -- standard practice for long-form ambient mixes).
    """
    manifest_path = set_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = [Path(f) for f in manifest["files"]]
        titles = {Path(f).name: t["title"]
                  for f, t in zip(manifest["files"], manifest.get("tracks", []))} \
            if manifest.get("tracks") else {}
    else:
        files, titles = sorted(set_dir.glob("*.wav")), {}
    files = [f for f in files if f.exists() and f.name != "mix.wav"]
    assert files, f"no tracks found in {set_dir}"

    if target_minutes:
        set_sec = sum(sf.info(f).duration for f in files)
        joined = set_sec - (len(files) - 1) * CROSSFADE_SEC  # first pass length
        per_loop = set_sec - len(files) * CROSSFADE_SEC       # each repeat adds this
        loops = 1
        total = joined
        while total < target_minutes * 60 and per_loop > 0:
            loops += 1
            total += per_loop
        print(f"target {target_minutes:.0f} min: set is {set_sec/60:.1f} min "
              f"-> {loops} loop(s) ~ {total/60:.1f} min")

    fade = int(CROSSFADE_SEC * SR)
    mix = None
    chapters: list[str] = []
    for loop in range(loops):
        for f in files:
            y = _load_norm(f)
            title = titles.get(f.name) or f.stem.split("-", 1)[-1].replace("-", " ").title()
            start = 0.0 if mix is None else (len(mix) - fade) / SR
            chapters.append(f"{_fmt_ts(start)} {title}")
            mix = y if mix is None else _crossfade(mix, y, fade)

    out_wav = set_dir / "mix.wav"
    sf.write(out_wav, mix, SR)
    out_ch = set_dir / "chapters.txt"
    out_ch.write_text("\n".join(chapters) + "\n", encoding="utf-8")
    return out_wav, out_ch


def main() -> None:
    p = argparse.ArgumentParser(description="Build a long mix from a track set.")
    p.add_argument("set_dir", type=Path)
    p.add_argument("--loops", type=int, default=1)
    p.add_argument("--target-minutes", type=float, default=None,
                   help="loop the set until the mix is at least this long")
    args = p.parse_args()
    wav, ch = build_mix(args.set_dir, args.loops, args.target_minutes)
    dur = sf.info(wav).duration
    print(f"mix: {wav} ({dur/60:.1f} min)\nchapters: {ch}")


if __name__ == "__main__":
    main()
