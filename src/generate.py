"""Generate the track plan with ACE-Step on a local or rented GPU.

The runtime is lazy-loaded so planning and dry-runs work without CUDA. The
current ACE-Step API is used first; a small compatibility fallback keeps older
installations understandable when their call signature differs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .common import env_bool, load_config, slugify
except ImportError:  # direct script execution
    from common import env_bool, load_config, slugify

MIN_VRAM_GB = 8


def detect_device(requested: str = "auto", allow_cpu: bool = False,
                  device_id: int = 0) -> str:
    """Select CUDA first, then MPS, then explicitly-authorised CPU."""
    try:
        import torch
    except ImportError as exc:
        if requested == "cpu" and allow_cpu:
            return "cpu"
        raise SystemExit(
            "PyTorch is not installed. Run setup_local.sh to install the GPU build."
        ) from exc

    if requested == "cuda":
        if not torch.cuda.is_available():
            raise SystemExit("CUDA was requested but torch.cuda.is_available() is false.")
        if device_id >= torch.cuda.device_count():
            raise SystemExit(f"CUDA device {device_id} is unavailable; found {torch.cuda.device_count()} device(s).")
        return "cuda"
    if requested == "mps":
        if not getattr(torch.backends, "mps", None) or not torch.backends.mps.is_available():
            raise SystemExit("MPS was requested but is unavailable.")
        return "mps"
    if requested == "cpu":
        if not allow_cpu:
            raise SystemExit("CPU generation is extremely slow; rerun with --allow-cpu to confirm.")
        return "cpu"

    if torch.cuda.is_available():
        if device_id >= torch.cuda.device_count():
            raise SystemExit(f"CUDA device {device_id} is unavailable; found {torch.cuda.device_count()} device(s).")
        name = torch.cuda.get_device_name(device_id)
        vram = torch.cuda.get_device_properties(device_id).total_memory / 1e9
        print(f"local NVIDIA GPU detected: {name} ({vram:.1f} GB VRAM)")
        if vram < MIN_VRAM_GB:
            print(f"warning: this GPU has less than {MIN_VRAM_GB} GB VRAM; CPU offload may be needed")
        return "cuda"

    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        print("Apple Silicon GPU detected (mps)")
        return "mps"
    if allow_cpu:
        print("no accelerator found; running on CPU (very slow)")
        return "cpu"
    raise SystemExit(
        "No supported accelerator found. Install a CUDA-enabled PyTorch build, "
        "or rerun with --allow-cpu."
    )


def _configure_cuda(device: str, device_id: int) -> None:
    """Select the physical GPU before ACE-Step imports its model modules."""
    if device == "cuda" and "CUDA_VISIBLE_DEVICES" not in os.environ:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(device_id)


def load_pipeline(device: str, device_id: int = 0, checkpoint_path: str = "",
                  bf16: bool = True, cpu_offload: bool = False,
                  overlapped_decode: bool = False,
                  torch_compile: bool = False):
    """Load ACE-Step once and keep it resident for the whole track set."""
    _configure_cuda(device, device_id)
    try:
        from acestep.pipeline_ace_step import ACEStepPipeline
    except ImportError as exc:
        raise RuntimeError(
            "ACE-Step is not installed. Run setup_local.sh (or runpod/setup.sh)."
        ) from exc

    kwargs: dict[str, Any] = {
        "checkpoint_dir": checkpoint_path or "",
        "dtype": "bfloat16" if device == "cuda" and bf16 else "float32",
        "torch_compile": bool(torch_compile),
        "cpu_offload": bool(cpu_offload),
        "overlapped_decode": bool(overlapped_decode),
    }
    try:
        return ACEStepPipeline(**kwargs)
    except TypeError:
        # Older ACE-Step builds did not expose the memory flags. Retain the
        # essential arguments and surface the original install in logs.
        reduced = {key: kwargs[key] for key in ("checkpoint_dir", "dtype", "torch_compile")}
        return ACEStepPipeline(**reduced)


def _generation_kwargs(track: dict[str, Any], settings: dict[str, Any], out_path: Path) -> dict[str, Any]:
    seed = int(track.get("seed") or settings.get("seed") or 0)
    return {
        "audio_duration": float(track["duration_sec"]),
        "prompt": track["prompt"],
        "lyrics": "[inst]",
        "infer_step": int(settings.get("infer_steps", 60)),
        "guidance_scale": float(settings.get("guidance_scale", 15.0)),
        "scheduler_type": str(settings.get("scheduler_type", "euler")),
        "cfg_type": str(settings.get("cfg_type", "apg")),
        "omega_scale": float(settings.get("omega_scale", 10.0)),
        "manual_seeds": str(seed),
        "guidance_interval": 0.5,
        "guidance_interval_decay": 0,
        "min_guidance_scale": 3,
        "use_erg_tag": True,
        "use_erg_lyric": True,
        "use_erg_diffusion": True,
        "oss_steps": "",
        "guidance_scale_text": 0.0,
        "guidance_scale_lyric": 0.0,
        "save_path": str(out_path),
    }


def generate_track(pipe: Any, track: dict[str, Any], out_dir: Path,
                   settings: dict[str, Any]) -> Path:
    out_path = out_dir / f"{int(track['index']):02d}-{slugify(str(track['title']))}.wav"
    if out_path.exists() and out_path.stat().st_size > 1024 and not settings.get("no_resume"):
        print(f"  skip [{int(track['index']):02d}] existing {out_path.name}")
        return out_path

    kwargs = _generation_kwargs(track, settings, out_path)
    try:
        # This is the current ACE-Step pipeline interface.
        pipe(**kwargs)
    except TypeError as first_error:
        # Compatibility with early releases used by the original scaffold.
        try:
            pipe(
                prompt=track["prompt"],
                lyrics="[inst]",
                audio_duration=float(track["duration_sec"]),
                infer_step=int(settings.get("infer_steps", 60)),
                guidance_scale=float(settings.get("guidance_scale", 15.0)),
                save_path=str(out_path),
            )
        except Exception:
            raise first_error
    if not out_path.exists() or out_path.stat().st_size <= 1024:
        raise RuntimeError(f"ACE-Step returned without creating {out_path}")
    return out_path


def _config_settings(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_config()
    music = cfg.get("music", {})
    settings: dict[str, Any] = {
        "infer_steps": args.steps if args.steps is not None else music.get("infer_steps", 60),
        "guidance_scale": args.guidance if args.guidance is not None else music.get("guidance_scale", 15.0),
        "scheduler_type": music.get("scheduler_type", "euler"),
        "cfg_type": music.get("cfg_type", "apg"),
        "omega_scale": music.get("omega_scale", 10.0),
        "checkpoint_path": args.checkpoint_path or os.environ.get("ACE_CHECKPOINT_PATH") or music.get("checkpoint_path", ""),
        "bf16": args.bf16 if args.bf16 is not None else env_bool("V2M_BF16", bool(music.get("bf16", True))),
        "cpu_offload": args.cpu_offload if args.cpu_offload is not None else env_bool("V2M_CPU_OFFLOAD", bool(music.get("cpu_offload", False))),
        "overlapped_decode": args.overlapped_decode if args.overlapped_decode is not None else env_bool("V2M_OVERLAPPED_DECODE", bool(music.get("overlapped_decode", False))),
        "torch_compile": args.torch_compile if args.torch_compile is not None else bool(music.get("torch_compile", False)),
        "seed": args.seed,
        "no_resume": args.no_resume,
    }
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ACE-Step tracks from prompts.json")
    parser.add_argument("prompts")
    parser.add_argument("--out", default="output")
    parser.add_argument("--device", default=os.environ.get("V2M_DEVICE", "auto"), choices=["auto", "cuda", "mps", "cpu"])
    parser.add_argument("--device-id", type=int, default=int(os.environ.get("V2M_DEVICE_ID", "0")))
    parser.add_argument("--checkpoint-path", default="")
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--guidance", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--bf16", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--cpu-offload", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--overlapped-decode", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--torch-compile", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    prompts_path = Path(args.prompts)
    plan = json.loads(prompts_path.read_text(encoding="utf-8"))
    out_dir = Path(args.out) / slugify(plan["set_title"])
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"set: {plan['set_title']} -- {len(plan['tracks'])} tracks -> {out_dir}")
    if args.dry_run:
        for track in plan["tracks"]:
            print(
                f"  [{int(track['index']):02d}] {track['title']} | {track.get('bpm', '?')} BPM "
                f"{track.get('key', '?')} | {track['duration_sec']}s | {track['prompt'][:90]}..."
            )
        return

    settings = _config_settings(args)
    device = detect_device(args.device, args.allow_cpu, args.device_id)
    pipe = load_pipeline(
        device, args.device_id, settings["checkpoint_path"], settings["bf16"],
        settings["cpu_offload"], settings["overlapped_decode"], settings["torch_compile"],
    )
    results: list[Path] = []
    failures: list[dict[str, Any]] = []
    for track in plan["tracks"]:
        started = time.time()
        try:
            path = generate_track(pipe, track, out_dir, settings)
            results.append(path)
            print(f"  ok  [{int(track['index']):02d}] {path.name} ({time.time() - started:.1f}s)")
        except Exception as exc:  # noqa: BLE001 - one bad seed should not erase a set
            failure = {"index": int(track["index"]), "error": str(exc)}
            failures.append(failure)
            print(f"  FAIL[{failure['index']:02d}] {failure['error']}", file=sys.stderr)

    manifest = {
        "set_title": plan["set_title"],
        "mood_tags": plan.get("mood_tags", []),
        "target_duration_sec": plan.get("target_duration_sec"),
        "generator": plan.get("generator"),
        "tracks": plan["tracks"],
        "files": [str(path.resolve()) for path in results],
        "failures": failures,
        "device": device,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"done: {len(results)} ok, {len(failures)} failed -> {out_dir / 'manifest.json'}")
    if not results:
        sys.exit(1)


if __name__ == "__main__":
    main()
