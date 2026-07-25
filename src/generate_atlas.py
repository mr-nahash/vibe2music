"""CLI wrapper for Atlas Cloud Chirp-fenix generation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from atlas import generate_set

parser = argparse.ArgumentParser(description="Generate instrumental sources with Atlas Cloud Chirp-fenix")
parser.add_argument("prompts")
parser.add_argument("--out", default="output")
parser.add_argument("--model", default="suno/chirp-fenix")
parser.add_argument("--poll-seconds", type=float, default=6)
parser.add_argument("--timeout-seconds", type=float, default=900)
args = parser.parse_args()
plan = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
print(f"Atlas Cloud: generating {len(plan['tracks'])} instrumental sources with {args.model}")
print(f"Each paid generation returns two alternatives; source 1 is selected and both are recorded in manifest.json.")
print(generate_set(plan, Path(args.out), model=args.model, poll_seconds=args.poll_seconds, timeout_seconds=args.timeout_seconds))
