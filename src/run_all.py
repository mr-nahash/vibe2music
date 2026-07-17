"""Run the complete production pipeline from vibe to reviewable MP4."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from common import slugify

HERE = Path(__file__).resolve().parent


def run(script: str, *args: str, env: dict[str, str] | None = None) -> None:
    command = [sys.executable, str(HERE / script), *args]
    print(f"\n=== {script} {' '.join(args)} ===")
    completed = subprocess.run(command, env=env)
    if completed.returncode != 0:
        raise SystemExit(f"pipeline stopped at {script} (exit {completed.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(description="vibe -> exact-length YouTube-ready video")
    parser.add_argument("vibe")
    parser.add_argument("--instruments", default="")
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--tracks", type=int, default=None)
    parser.add_argument("--target-minutes", type=float, default=45.0)
    parser.add_argument("--out", default="output")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    parser.add_argument("--device-id", type=int, default=0)
    parser.add_argument("--checkpoint-path", default="")
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--upload", action="store_true", help="upload as private after the pipeline")
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-llm", action="store_true")
    args = parser.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    prompts = out_root / "prompts.json"
    compile_args = [
        args.vibe, "--instruments", args.instruments,
        "--target-minutes", str(args.target_minutes), "--out", str(prompts),
    ]
    if args.tracks is not None:
        compile_args += ["--tracks", str(args.tracks)]
    if args.image:
        compile_args += ["--image", str(args.image)]
    if args.require_llm:
        compile_args.append("--require-llm")
    if args.dry_run:
        compile_args.append("--offline")
    run("prompt_compiler.py", *compile_args)

    if args.dry_run:
        run("generate.py", str(prompts), "--out", str(out_root), "--dry-run")
        print("\ndry run complete -- no GPU or LLM request was made")
        return

    generate_args = [
        str(prompts), "--out", str(out_root), "--device", args.device,
        "--device-id", str(args.device_id),
    ]
    if args.checkpoint_path:
        generate_args += ["--checkpoint-path", args.checkpoint_path]
    if args.allow_cpu:
        generate_args.append("--allow-cpu")
    run("generate.py", *generate_args)

    plan = json.loads(prompts.read_text(encoding="utf-8"))
    set_dir = out_root / slugify(plan["set_title"])
    run("qc.py", str(set_dir), "--min-passed", "1")
    run("mix.py", str(set_dir), "--target-minutes", str(args.target_minutes))
    run("metadata.py", str(set_dir), "--vibe", args.vibe)

    image = args.image
    if image is None:
        image = set_dir / "cover.png"
        run("cover.py", "--title", plan["set_title"], "--vibe", args.vibe, "--out", str(image))
    run("render.py", str(set_dir), "--image", str(image))

    print(
        f"\nREADY FOR REVIEW\n"
        f"  audio: {set_dir / 'mix.wav'}\n"
        f"  video: {set_dir / 'video.mp4'}\n"
        f"  metadata: {set_dir / 'metadata.json'}\n"
        "Review the complete video and metadata before any public release."
    )
    if args.upload:
        run("upload.py", str(set_dir), "--privacy", args.privacy)
        print(f"uploaded to YouTube as {args.privacy}")


if __name__ == "__main__":
    main()
