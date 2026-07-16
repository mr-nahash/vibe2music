"""Video renderer: still image + mix.wav -> YouTube-ready mp4 via ffmpeg.

No LLM (tier: scripts). Static image, h264/yuv420p/aac -- maximum compatibility.

Usage:
    python render.py <set_dir> --image cover.jpg [--out video.mp4]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def render(set_dir: Path, image: Path, out: Path | None = None) -> Path:
    audio = set_dir / "mix.wav"
    assert audio.exists(), f"run mix.py first -- {audio} missing"
    assert image.exists(), f"image not found: {image}"
    out = out or set_dir / "video.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "medium",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
        "-r", "2",                      # static image: low fps keeps files small
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-fflags", "+shortest", "-max_interleave_delta", "100M",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr[-2000:], file=sys.stderr)
        raise RuntimeError("ffmpeg failed")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Render mix + image into an mp4.")
    p.add_argument("set_dir", type=Path)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    out = render(args.set_dir, args.image, args.out)
    print(f"video: {out}")


if __name__ == "__main__":
    main()
