"""One-command pipeline: vibe -> published-ready set.

    python run_all.py "rainy tokyo cafe" --instruments piano,vinyl \
        --image cover.jpg [--tracks 8] [--upload] [--dry-run]

Steps: compile prompts -> generate (GPU) -> QC gate -> mix -> render -> metadata
       -> [optional] upload (private).
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
    p.add_argument("--out", default="output")
    p.add_argument("--upload", action="store_true", help="also upload (private) at the end")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    prompts = Path(args.out) / "prompts.json"
    prompts.parent.mkdir(parents=True, exist_ok=True)
    run("prompt_compiler.py", args.vibe, "--instruments", args.instruments,
        "--tracks", str(args.tracks), "--out", str(prompts))

    if args.dry_run:
        run("generate.py", str(prompts), "--out", args.out, "--dry-run")
        print("\ndry run complete -- no GPU or upload cost incurred")
        return

    run("generate.py", str(prompts), "--out", args.out)

    plan = json.loads(prompts.read_text(encoding="utf-8"))
    import re
    set_dir = Path(args.out) / re.sub(r"[^a-z0-9]+", "-", plan["set_title"].lower()).strip("-")[:60]

    run("qc.py", str(set_dir))
    run("mix.py", str(set_dir))
    run("render.py", str(set_dir), "--image", args.image)
    run("metadata.py", str(set_dir))

    print(f"\nREVIEW CHECKPOINT: listen to {set_dir / 'mix.wav'} and edit "
          f"{set_dir / 'metadata.json'} before publishing.")
    if args.upload:
        run("upload.py", str(set_dir), "--privacy", "private")
        print("uploaded as PRIVATE -- publish from YouTube Studio after review.")


if __name__ == "__main__":
    main()
