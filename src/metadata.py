"""Metadata generator: set info + chapters -> title/description/tags (cheap LLM).

Drafts only -- a human edits before publish (inauthentic-content policy).

Usage:
    python metadata.py <set_dir>       # writes <set_dir>/metadata.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import anthropic

CHEAP_MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """You write YouTube metadata for instrumental background-music mixes.
Return ONLY valid JSON: {"title": str, "description": str, "tags": [str]}
Rules:
- Title <= 90 chars, includes the mood + use case (study/sleep/focus/relax), no clickbait.
- Description: 2 short paragraphs about the mood, then a blank line. Do NOT include
  chapters (they are appended separately). No hashtags spam -- max 3 at the end.
- 10-15 tags, lowercase.
- Never claim human performance. Content is AI-assisted music."""

DISCLOSURE = "\n\nThis music was created with AI assistance and curated by a human."


def generate_metadata(set_dir: Path) -> dict:
    manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
    chapters = (set_dir / "chapters.txt").read_text(encoding="utf-8").strip()

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=CHEAP_MODEL, max_tokens=1500, system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"Set title: {manifest['set_title']}\n"
                   f"Mood tags: {', '.join(manifest.get('mood_tags', []))}\n"
                   f"Track count: {len(manifest['files'])}\n"
                   f"Track names: {chapters}"}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
    meta = json.loads(raw)
    for field in ("title", "description", "tags"):
        assert field in meta, f"metadata missing {field}"

    meta["title"] = meta["title"][:100]
    meta["description"] = meta["description"] + "\n\nTracklist:\n" + chapters + DISCLOSURE
    meta["tags"] = [t.lower()[:60] for t in meta["tags"]][:15]
    out = set_dir / "metadata.json"
    out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("set_dir", type=Path)
    args = p.parse_args()
    meta = generate_metadata(args.set_dir)
    print(f"title: {meta['title']}\nwrote {args.set_dir / 'metadata.json'} -- edit before publishing!")


if __name__ == "__main__":
    main()
