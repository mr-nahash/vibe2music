"""Compile a vibe into a coherent, target-length instrumental track plan.

The LLM is optional. When ``ANTHROPIC_API_KEY`` is absent or the request fails,
the compiler produces a deterministic local plan so the GPU pipeline remains
usable offline. The generated tracks are deliberately distinct: each gets a
different energy, texture, key, and seed while sharing the same sonic brief.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import random
import sys
from pathlib import Path
from typing import Any

try:
    from .common import default_track_count, load_config, target_track_duration
except ImportError:  # direct script execution
    from common import default_track_count, load_config, target_track_duration


SYSTEM = """You are a music director for an instrumental background-music channel.
Given a vibe, optional image, instruments, and a target duration, produce exactly
N distinct instrumental track briefs that form a coherent 45-minute album.

Rules:
- Instrumental only. Use [inst] as the lyrics value downstream; never request
  vocals, lyrics, singing, spoken word, or named living artists.
- Each track must vary tempo (+/- 15 BPM around a base), key, energy, and one
  featured texture. Create a gentle album arc: opening, development, peak,
  and resolution.
- Keep prompts concrete and audio-model friendly: genre, mood, instruments,
  BPM, key, arrangement, texture. No poetry or narrative.
- Return exactly N tracks, with duration_sec between the requested bounds.

Return ONLY valid JSON:
{
  "set_title": str,
  "mood_tags": [str],
  "tracks": [
    {"index": int, "title": str, "prompt": str, "bpm": int,
     "key": str, "duration_sec": int, "seed": int}
  ]
}"""


def _image_block(path: str) -> dict[str, Any]:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def _seed_for(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _fallback_tags(vibe: str | None) -> list[str]:
    text = (vibe or "ambient focus music").lower()
    known = [
        "ambient", "lofi", "cinematic", "sleep", "study", "focus", "jazz",
        "piano", "electronic", "synthwave", "dreamwave", "vaporwave", "chill",
        "acoustic", "nature", "rain", "night", "cafe", "calm", "meditation",
    ]
    tags = [word for word in known if word in text]
    return list(dict.fromkeys(tags + ["instrumental", "background music"]))[:8]


def _fallback_plan(vibe: str | None, instruments: list[str], n_tracks: int,
                   target_minutes: float, min_duration: int,
                   max_duration: int) -> dict[str, Any]:
    vibe_text = (vibe or "calm cinematic ambient focus music").strip()
    instruments = instruments or ["soft piano", "warm analog pads", "subtle percussion"]
    tags = _fallback_tags(vibe_text)
    target_duration = target_track_duration(
        target_minutes, n_tracks, minimum=min_duration, maximum=max_duration
    )
    energies = ["gentle opening", "steady development", "deep focus", "warm peak", "quiet resolution"]
    textures = [
        "tape hiss", "felt piano", "soft granular shimmer", "room ambience",
        "muted brushed drums", "subtle vinyl texture", "distant field recording",
        "analog flutter",
    ]
    keys = ["C major", "A minor", "F major", "D minor", "G major", "E minor", "Bb major", "C minor"]
    base_seed = _seed_for(vibe_text, ",".join(instruments), str(target_minutes), str(n_tracks))
    rng = random.Random(base_seed)
    bpm_base = 72 + rng.randrange(0, 22)
    tracks: list[dict[str, Any]] = []
    for i in range(n_tracks):
        progress = i / max(1, n_tracks - 1)
        energy = energies[min(len(energies) - 1, int(progress * len(energies)))]
        texture = textures[i % len(textures)]
        bpm = max(52, min(128, bpm_base + (-4 if i == 0 else 0) + (i % 5) * 2 - 3))
        key = keys[i % len(keys)]
        title = f"{i + 1:02d} · {energy.title()}"
        prompt = (
            f"instrumental {vibe_text}, {energy}, {', '.join(instruments)}, "
            f"{bpm} BPM, {key}, evolving arrangement, {texture}, "
            "smooth transitions, no vocals, no speech"
        )
        tracks.append({
            "index": i + 1,
            "title": title,
            "prompt": prompt,
            "bpm": bpm,
            "key": key,
            "duration_sec": target_duration,
            "seed": rng.randrange(1, 2_147_483_647),
        })
    return {
        "set_title": f"{vibe_text.title()} — Instrumental Sessions",
        "mood_tags": tags,
        "tracks": tracks,
        "target_duration_sec": round(float(target_minutes) * 60),
        "generator": "local-template",
    }


def _normalise_plan(plan: dict[str, Any], n_tracks: int, min_duration: int,
                    max_duration: int, target_minutes: float,
                    seed_namespace: str) -> dict[str, Any]:
    tracks = list(plan.get("tracks") or [])[:n_tracks]
    if len(tracks) != n_tracks:
        raise ValueError(f"model returned {len(tracks)} tracks; expected {n_tracks}")
    default_duration = target_track_duration(
        target_minutes, n_tracks, minimum=min_duration, maximum=max_duration
    )
    for i, track in enumerate(tracks, start=1):
        for field in ("title", "prompt", "bpm", "key"):
            if field not in track:
                raise ValueError(f"track {i} missing field: {field}")
        track["index"] = i
        track["duration_sec"] = max(min_duration, min(max_duration, int(track.get("duration_sec", default_duration))))
        track["bpm"] = int(track["bpm"])
        track["seed"] = int(track.get("seed") or _seed_for(seed_namespace, str(i)))
    plan["tracks"] = tracks
    plan["mood_tags"] = [str(tag) for tag in plan.get("mood_tags", [])][:12]
    plan["target_duration_sec"] = round(float(target_minutes) * 60)
    return plan


def compile_prompts(vibe: str | None, image: str | None, instruments: list[str],
                    n_tracks: int | None = None, target_minutes: float = 45.0,
                    offline: bool = False, require_llm: bool = False) -> dict[str, Any]:
    if not vibe and not image:
        raise ValueError("Provide a vibe description, an image, or both.")
    cfg = load_config()
    track_cfg = cfg.get("tracks", {})
    duration_cfg = track_cfg.get("duration_sec", {})
    min_duration = int(duration_cfg.get("min", 180))
    max_duration = int(duration_cfg.get("max", 240))
    crossfade = int(track_cfg.get("crossfade_sec", 4))
    n_tracks = n_tracks or track_cfg.get("per_set") or default_track_count(
        target_minutes, max_duration, crossfade
    )
    n_tracks = max(3, min(24, int(n_tracks)))
    seed_namespace = f"{vibe or 'image'}|{','.join(instruments)}|{target_minutes}"

    if offline or os.environ.get("V2M_DISABLE_LLM", "").lower() in {"1", "true", "yes"}:
        return _fallback_plan(vibe, instruments, n_tracks, target_minutes, min_duration, max_duration)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        if require_llm:
            raise RuntimeError("ANTHROPIC_API_KEY is required when --require-llm is set")
        return _fallback_plan(vibe, instruments, n_tracks, target_minutes, min_duration, max_duration)

    try:
        import anthropic

        content: list[dict[str, Any]] = []
        if image:
            content.append(_image_block(image))
        content.append({"type": "text", "text": (
            f"Vibe: {vibe or 'infer the vibe entirely from the image'}\n"
            f"Instruments to feature: {', '.join(instruments) or 'your choice, keep it minimal'}\n"
            f"Number of tracks: {n_tracks}\n"
            f"Target album duration: {target_minutes:.1f} minutes\n"
            f"Per-track duration bounds: {min_duration}-{max_duration} seconds"
        )})
        client = anthropic.Anthropic(api_key=api_key)
        model = cfg.get("llm", {}).get("cheap_model", "claude-haiku-4-5-20251001")
        msg = client.messages.create(
            model=model, max_tokens=5000, system=SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw[raw.find("{"):raw.rfind("}") + 1]
        plan = _normalise_plan(
            json.loads(raw), n_tracks, min_duration, max_duration,
            target_minutes, seed_namespace
        )
        plan["generator"] = "anthropic"
        return plan
    except Exception as exc:  # noqa: BLE001 - offline fallback is intentional
        if require_llm:
            raise
        plan = _fallback_plan(vibe, instruments, n_tracks, target_minutes, min_duration, max_duration)
        plan["generator"] = "local-template-fallback"
        plan["llm_error_type"] = type(exc).__name__
        return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a vibe into a target-length music plan.")
    parser.add_argument("vibe", nargs="?", default=None)
    parser.add_argument("--image", default=None)
    parser.add_argument("--instruments", default="")
    parser.add_argument("--tracks", type=int, default=None)
    parser.add_argument("--target-minutes", type=float, default=45.0)
    parser.add_argument("--out", default="prompts.json")
    parser.add_argument("--offline", action="store_true", help="never call an LLM")
    parser.add_argument("--require-llm", action="store_true")
    args = parser.parse_args()

    instruments = [item.strip() for item in args.instruments.split(",") if item.strip()]
    try:
        plan = compile_prompts(
            args.vibe, args.image, instruments, args.tracks, args.target_minutes,
            offline=args.offline, require_llm=args.require_llm,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out}: '{plan['set_title']}' with {len(plan['tracks'])} tracks")
    print(f"generator: {plan.get('generator', 'unknown')} | target: {args.target_minutes:g} min")


if __name__ == "__main__":
    main()
