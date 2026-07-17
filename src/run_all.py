"""One-command pipeline: vibe -> published-ready set.

    python run_all.py "rainy tokyo cafe" --instruments piano,vinyl \
        --image cover.jpg --target-minutes 45 [--upload] [--dry-run]

Steps: compile prompts -> generate (GPU, auto-retries failed tracks) ->
       QC (prunes bad tracks, keeps going) -> mix (loops to target length) ->
       render -> metadata -> [optional] upload (private).

--target-minutes 45 sizes the whole run so the final mix lands at ~45 min.
Runs on a local NVIDIA GPU out of the box (see local/setup_local.sh);
use --low-vram on consumer cards under 12 GB.
--dry-run stops after printing the generation plan (no GPU, no API cost).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(script: str, *args: str) -> None:
    cmd = [sys.executable, str(HERE / script), *args]
    print(f"\n=== {script} {' '.join(args)} ===")
    if subprocess.run(cmd).returncode != 0:
        print(f"pipeline stopped at {script}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="vibe -> YouTube-ready video, one command")
    p.add_argument("vibe")
    p.add_argument("--instruments", default="")
    p.add_argument("--image", required=True, help="cover image for the video")
    p.add_argument("--tracks", type=int, default=8)
    p.add_argument("--target-minutes", type=float, default=None,
                   help="target length of the final mix, e.g. 45 -- sizes the "
                        "track set and loops the mix to reach it")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"],
                   help="generation device (auto prefers a local NVIDIA GPU)")
    p.add_argument("--allow-cpu", action="store_true")
    p.add_argument("--low-vram", action="store_true",
                   help="CPU offload for consumer GPUs (<12 GB VRAM)")
    p.add_argument("--out", default="output")
    p.add_argument("--upload", action="store_true", help="also upload (private) at the end")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    prompts = Path(args.out) / "prompts.json"
    prompts.parent.mkdir(parents=True, exist_ok=True)
    compile_args = [args.vibe, "--instruments", args.instruments,
                    "--tracks", str(args.tracks), "--out", str(prompts)]
    if args.target_minutes:
        compile_args += ["--target-minutes", str(args.target_minutes)]
    run("prompt_compiler.py", *compile_args)

    if args.dry_run:
        run("generate.py", str(prompts), "--out", args.out, "--dry-run")
        print("\ndry run complete -- no GPU or upload cost incurred")
        return

    gen_args = [str(prompts), "--out", args.out, "--device", args.device]
    if args.allow_cpu:
        gen_args.append("--allow-cpu")
    if args.low_vram:
        gen_args.append("--low-vram")
    run("generate.py", *gen_args)

    plan = json.loads(prompts.read_text(encoding="utf-8"))
    import re
    set_dir = Path(args.out) / re.sub(r"[^a-z0-9]+", "-", plan["set_title"].lower()).strip("-")[:60]

    run("qc.py", str(set_dir), "--prune")
    mix_args = [str(set_dir)]
    if args.target_minutes:
        mix_args += ["--target-minutes", str(args.target_minutes)]
    run("mix.py", *mix_args)
    run("render.py", str(set_dir), "--image", args.image)
    run("metadata.py", str(set_dir))

    print(f"\nREVIEW CHECKPOINT: listen to {set_dir / 'mix.wav'} and edit "
          f"{set_dir / 'metadata.json'} before publishing.")
    if args.upload:
        run("upload.py", str(set_dir), "--privacy", "private")
        print("uploaded as PRIVATE -- publish from YouTube Studio after review.")


if __name__ == "__main__":
    main()
