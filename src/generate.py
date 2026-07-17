"""Generation runner: prompts.json -> WAV files via ACE-Step.

Device selection is automatic: prefers a local NVIDIA GPU when present,
falls back to Apple Silicon (mps), and only then CPU (very slow -- requires
--allow-cpu so you don't burn hours by accident). Override with --device.

NOTE: ACE-Step's Python API may drift between releases -- if the import or call
signature fails, check `python -c "import acestep; help(acestep)"` and adjust
the marked sections only.

Usage:
    python generate.py prompts.json --out output/ [--device auto|cuda|mps|cpu] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

MIN_VRAM_GB = 8  # below this, ACE-Step inference will struggle


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def detect_device(requested: str = "auto", allow_cpu: bool = False) -> str:
    """Pick the best available device, preferring a local GPU."""
    import torch

    if requested != "auto":
        if requested == "cpu" and not allow_cpu:
            sys.exit("CPU generation is extremely slow -- rerun with --allow-cpu to confirm.")
        return requested

    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"local GPU detected: {name} ({vram:.0f} GB VRAM)")
        if vram < MIN_VRAM_GB:
            print(f"warning: <{MIN_VRAM_GB} GB VRAM -- generation may OOM; "
                  "consider a cloud GPU if it fails")
        return "cuda"

    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        print("Apple Silicon GPU detected (mps)")
        return "mps"

    if allow_cpu:
        print("no GPU found -- running on CPU (very slow)")
        return "cpu"
    sys.exit("no GPU detected. Options: run on a cloud GPU (see runpod/setup.sh), "
             "or force CPU with --allow-cpu.")


def load_pipeline(device: str):
    """Lazy-load ACE-Step so --dry-run works on machines without a GPU."""
    # ---- ACE-Step API surface: adjust here if the release changed ----
    from acestep.pipeline_ace_step import ACEStepPipeline
    return ACEStepPipeline(
        dtype="bfloat16" if device == "cuda" else "float32",
        torch_compile=False,
        device_id=0 if device == "cuda" else None,
    )
    # ------------------------------------------------------------------


def generate_track(pipe, track: dict, out_dir: Path) -> Path:
    """Generate one instrumental track; returns the output path."""
    out_path = out_dir / f"{track['index']:02d}-{slugify(track['title'])}.wav"
    # ---- ACE-Step API surface: adjust here if the release changed ----
    pipe(
        prompt=track["prompt"],
        lyrics="[instrumental]",          # force no vocals
        audio_duration=track["duration_sec"],
        infer_step=60,
        guidance_scale=15.0,
        save_path=str(out_path),
    )
    # ------------------------------------------------------------------
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description="Generate tracks from prompts.json")
    p.add_argument("prompts", help="path to prompts.json from prompt_compiler.py")
    p.add_argument("--out", default="output")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    p.add_argument("--allow-cpu", action="store_true", help="permit (very slow) CPU generation")
    p.add_argument("--dry-run", action="store_true", help="print plan, generate nothing")
    args = p.parse_args()

    plan = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    out_dir = Path(args.out) / slugify(plan["set_title"])
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"set: {plan['set_title']} -- {len(plan['tracks'])} tracks -> {out_dir}")
    if args.dry_run:
        for t in plan["tracks"]:
            print(f"  [{t['index']:02d}] {t['title']} | {t['bpm']} BPM {t['key']} "
                  f"| {t['duration_sec']}s | {t['prompt'][:70]}...")
        return

    device = detect_device(args.device, args.allow_cpu)
    pipe = load_pipeline(device)
    results, failures = [], []
    for t in plan["tracks"]:
        t0 = time.time()
        try:
            path = generate_track(pipe, t, out_dir)
            results.append(path)
            print(f"  ok  [{t['index']:02d}] {path.name} ({time.time() - t0:.0f}s)")
        except Exception as e:  # noqa: BLE001 -- keep the batch going
            failures.append((t["index"], str(e)))
            print(f"  FAIL[{t['index']:02d}] {e}", file=sys.stderr)

    manifest = {
        "set_title": plan["set_title"],
        "mood_tags": plan.get("mood_tags", []),
        "files": [str(r) for r in results],
        "failures": failures,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"done: {len(results)} ok, {len(failures)} failed -> {out_dir / 'manifest.json'}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
