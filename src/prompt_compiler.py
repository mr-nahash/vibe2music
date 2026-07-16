"""Prompt compiler: turn a vibe (text or image) + instruments into music-generation prompts.

Runs on a cheap model (Claude Haiku) -- high-volume, low-difficulty step.
Output: prompts.json consumed by generate.py.

Usage:
    python prompt_compiler.py "rainy tokyo cafe at midnight" --instruments piano,vinyl --tracks 8
    python prompt_compiler.py --image mood.jpg --instruments "warm pads,tape hiss" --tracks 10
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
from pathlib import Path

import anthropic

CHEAP_MODEL = "claude-haiku-4-5-20251001"  # tier: cheap -- templated creativity

SYSTEM = """You are a music director for an instrumental background-music channel.
Given a vibe and a set of instruments, produce N distinct track briefs that share
one coherent mood but vary enough that a listener never feels a loop.

Rules:
- Instrumental only. Never mention vocals, lyrics, or singing.
- Each track: vary tempo (+/- 15 BPM around a base), key (stay in related keys),
  energy (gentle arc across the set), and one featured texture.
- Keep prompts concrete and audio-model friendly: genre, mood, instruments,
  BPM, key, texture words. No poetry, no narrative.

Return ONLY valid JSON:
{
  "set_title": str,
  "mood_tags": [str],
  "tracks": [
    {"index": int, "title": str, "prompt": str, "bpm": int, "key": str, "duration_sec": int}
  ]
}"""


def _image_block(path: str) -> dict:
    """Encode a local image as an Anthropic vision content block."""
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def compile_prompts(vibe: str | None, image: str | None,
                    instruments: list[str], n_tracks: int = 8) -> dict:
    """Ask the cheap model for a structured track-set plan. Returns parsed dict."""
    if not vibe and not image:
        raise ValueError("Provide a vibe description, an image, or both.")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    content: list[dict] = []
    if image:
        content.append(_image_block(image))
    content.append({"type": "text", "text": (
        f"Vibe: {vibe or 'infer the vibe entirely from the image'}\n"
        f"Instruments to feature: {', '.join(instruments) or 'your choice, keep it minimal'}\n"
        f"Number of tracks: {n_tracks}"
    )})

    msg = client.messages.create(
        model=CHEAP_MODEL, max_tokens=4000, system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):  # tolerate accidental code fences
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
    plan = json.loads(raw)

    # Validate here -- fail loudly now, not at GPU time.
    assert plan.get("tracks"), "model returned no tracks"
    for t in plan["tracks"]:
        for field in ("index", "title", "prompt", "bpm", "key", "duration_sec"):
            assert field in t, f"track missing field: {field}"
        t["duration_sec"] = max(120, min(240, int(t["duration_sec"])))
    return plan


def main() -> None:
    p = argparse.ArgumentParser(description="Compile a vibe into music-model prompts.")
    p.add_argument("vibe", nargs="?", default=None, help="text description of the vibe")
    p.add_argument("--image", default=None, help="path to a mood image")
    p.add_argument("--instruments", default="", help="comma-separated instrument list")
    p.add_argument("--tracks", type=int, default=8)
    p.add_argument("--out", default="prompts.json")
    args = p.parse_args()

    instruments = [i.strip() for i in args.instruments.split(",") if i.strip()]
    try:
        plan = compile_prompts(args.vibe, args.image, instruments, args.tracks)
    except Exception as e:  # noqa: BLE001 -- CLI boundary
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    Path(args.out).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"wrote {args.out}: '{plan['set_title']}' with {len(plan['tracks'])} tracks")


if __name__ == "__main__":
    main()
