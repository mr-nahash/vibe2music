"""Create a deterministic abstract cover when the user did not upload one."""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _palette(seed: bytes) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (35 + seed[i] % 80, 25 + seed[i + 1] % 75, 65 + seed[i + 2] % 120)
        for i in (0, 3, 6, 9)
    )


def generate_cover(title: str, vibe: str, output: str | Path,
                   width: int = 1920, height: int = 1080,
                   target_minutes: float = 45.0) -> Path:
    output = Path(output)
    seed = hashlib.sha256(f"{title}|{vibe}".encode("utf-8")).digest()
    colors = _palette(seed)
    image = Image.new("RGB", (width, height), colors[0])
    pixels = image.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        left = colors[0]
        right = colors[1]
        for x in range(width):
            mix = x / max(1, width - 1)
            pixels[x, y] = tuple(int((1 - ratio) * ((1 - mix) * left[c] + mix * right[c]) + ratio * colors[2][c]) for c in range(3))

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for i in range(10):
        x = int((seed[i % len(seed)] / 255) * width)
        y = int((seed[(i + 4) % len(seed)] / 255) * height)
        radius = 100 + seed[(i + 7) % len(seed)] * 2
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colors[(i + 1) % len(colors)] + (60,))
    image = Image.alpha_composite(image.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(80)))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(0, height, 10):
        alpha = int(20 + 15 * math.sin(y / 55))
        draw.line((0, y, width, y), fill=(255, 255, 255, alpha), width=1)
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)

    title_font = _font(72, bold=True)
    subtitle_font = _font(30)
    max_width = int(width * 0.72)
    words = title.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=title_font)[2] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    y = int(height * 0.36)
    for line in lines[:3]:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x + 3, y + 3), line, font=title_font, fill=(0, 0, 0, 110))
        draw.text((x, y), line, font=title_font, fill=(255, 250, 244, 245))
        y += 88
    subtitle = f"{max(1, round(target_minutes)):g} MINUTES · INSTRUMENTAL SESSIONS"
    bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, y + 22), subtitle, font=subtitle_font, fill=(255, 235, 215, 220))

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, quality=94)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--vibe", default="")
    parser.add_argument("--minutes", type=float, default=45.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(f"cover: {generate_cover(args.title, args.vibe, args.out, target_minutes=args.minutes)}")


if __name__ == "__main__":
    main()
