"""Draft YouTube metadata, with a deterministic local fallback."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from .common import load_config
except ImportError:  # direct script execution
    from common import load_config

DISCLOSURE = "This music was created with AI assistance and curated by a human."
SYSTEM = """You write accurate YouTube metadata for an instrumental background-music album.
Return ONLY valid JSON: {"title": str, "description": str, "tags": [str]}.
Title <= 90 characters, includes mood and use case without clickbait. Description
has two useful paragraphs, then a concise human-curation and AI-assistance note.
Use 10-15 lowercase tags. Never claim a human performed the music and never name
a living artist as a style reference."""


def _clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:90].rstrip(" -|")


def _fallback_metadata(manifest: dict[str, Any], chapters: str, vibe: str | None) -> dict[str, Any]:
    set_title = str(manifest.get("set_title", "Instrumental Sessions"))
    tags = [str(tag).lower() for tag in manifest.get("mood_tags", [])]
    tags += ["instrumental music", "focus music", "study music", "ambient music", "background music"]
    title = _clean_title(f"{set_title} | 45-Minute Instrumental Focus Mix")
    description = (
        f"A continuous instrumental mix built around {vibe or set_title.lower()}. "
        "The album moves through several related arrangements so it can sit behind "
        "study, reading, work, or a quiet evening without abrupt changes.\n\n"
        "The tracks were generated with AI assistance, selected with deterministic "
        "audio quality checks, crossfaded, and curated for this channel."
    )
    return {
        "title": title,
        "description": description,
        "tags": list(dict.fromkeys(tags))[:15],
    }


def generate_metadata(set_dir: Path, vibe: str | None = None,
                      require_llm: bool = False) -> dict[str, Any]:
    manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
    chapters = (set_dir / "chapters.txt").read_text(encoding="utf-8").strip()
    cfg = load_config()
    meta: dict[str, Any]
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and not os.environ.get("V2M_DISABLE_LLM", "").lower() in {"1", "true", "yes"}:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=cfg.get("llm", {}).get("cheap_model", "claude-haiku-4-5-20251001"),
                max_tokens=1800, system=SYSTEM,
                messages=[{"role": "user", "content": (
                    f"Vibe: {vibe or manifest.get('set_title')}\n"
                    f"Set title: {manifest.get('set_title')}\n"
                    f"Mood tags: {', '.join(manifest.get('mood_tags', []))}\n"
                    f"Track count: {len(manifest.get('files', []))}\n"
                    f"Tracklist/chapter data:\n{chapters}"
                )}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw[raw.find("{"):raw.rfind("}") + 1]
            meta = json.loads(raw)
            for field in ("title", "description", "tags"):
                if field not in meta:
                    raise ValueError(f"metadata missing {field}")
        except Exception:
            if require_llm:
                raise
            meta = _fallback_metadata(manifest, chapters, vibe)
    else:
        if require_llm:
            raise RuntimeError("ANTHROPIC_API_KEY is required when --require-llm is set")
        meta = _fallback_metadata(manifest, chapters, vibe)

    meta["title"] = _clean_title(str(meta.get("title", manifest.get("set_title", "Instrumental Mix"))))
    description = str(meta.get("description", "")).strip()
    if chapters:
        description += f"\n\nTracklist:\n{chapters}"
    if DISCLOSURE.lower() not in description.lower():
        description += f"\n\n{DISCLOSURE}"
    meta["description"] = description
    meta["tags"] = [str(tag).lower()[:60] for tag in meta.get("tags", [])][:15]
    meta["contains_synthetic_media"] = True
    meta["human_review_required"] = True
    out = set_dir / "metadata.json"
    out.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("set_dir", type=Path)
    parser.add_argument("--vibe", default=None)
    parser.add_argument("--require-llm", action="store_true")
    args = parser.parse_args()
    meta = generate_metadata(args.set_dir, args.vibe, args.require_llm)
    print(f"title: {meta['title']}\nwrote {args.set_dir / 'metadata.json'} -- review before publishing")


if __name__ == "__main__":
    main()
