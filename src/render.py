"""Render the exact-length mix into a YouTube-compatible MP4."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def render(set_dir: Path, image: Path, out: Path | None = None,
           width: int = 1920, height: int = 1080, fps: int = 2,
           audio_bitrate: str = "192k") -> Path:
    audio = set_dir / "mix.wav"
    if not audio.exists():
        raise FileNotFoundError(f"run mix.py first -- {audio} missing")
    if not image.exists():
        raise FileNotFoundError(f"image not found: {image}")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required for video rendering")
    out = out or set_dir / "video.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    # Low frame rate plus a slowly changing crop keeps a 45-minute still-image
    # video small while making the visual less inert than a raw frozen frame.
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='min(zoom+0.00012,1.06)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={fps},format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(image), "-i", str(audio),
        "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage",
        "-r", str(fps), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", audio_bitrate,
        "-shortest", "-movflags", "+faststart", str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-4000:], file=sys.stderr)
        raise RuntimeError("ffmpeg failed")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Render mix.wav into video.mp4")
    parser.add_argument("set_dir", type=Path)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--fps", type=int, default=2)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--audio-bitrate", default="192k")
    args = parser.parse_args()
    output = render(args.set_dir, args.image, args.out, args.width, args.height, args.fps, args.audio_bitrate)
    print(f"video: {output}")


if __name__ == "__main__":
    main()
