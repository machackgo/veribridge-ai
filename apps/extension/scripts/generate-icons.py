#!/usr/bin/env python3
"""Generate the VeriBridge Recorder icon set.

Design: deep-indigo rounded square, white "VB" monogram, red recording dot.
The 128px icon keeps its artwork inside the central 96x96 region with
transparent padding, per Chrome Web Store icon guidance. Also emits the
440x280 small promo tile. Deterministic output (no timestamps embedded).
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
ICONS = ROOT / "icons"
STORE = ROOT / "store-assets"

BG = (49, 46, 129, 255)        # indigo-900
BG_LIGHT = (79, 70, 229, 255)  # indigo-600 accent border
FG = (255, 255, 255, 255)
DOT = (239, 68, 68, 255)       # red-500
DOT_RING = (255, 255, 255, 255)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    raise SystemExit("No usable bold font found")


def draw_mark(canvas_px: int, artwork_px: int) -> Image.Image:
    """Draw the mark with artwork centered in artwork_px inside canvas_px."""
    scale = 4  # supersample for clean small sizes
    c = canvas_px * scale
    a = artwork_px * scale
    img = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    off = (c - a) // 2
    radius = int(a * 0.22)
    d.rounded_rectangle([off, off, off + a - 1, off + a - 1], radius=radius, fill=BG)
    # subtle inner border for definition on dark backgrounds
    d.rounded_rectangle(
        [off, off, off + a - 1, off + a - 1],
        radius=radius,
        outline=BG_LIGHT,
        width=max(scale, a // 48),
    )

    font = load_font(int(a * 0.44))
    text = "VB"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = off + (a - tw) / 2 - bbox[0]
    ty = off + (a - th) / 2 - bbox[1] + a * 0.02
    d.text((tx, ty), text, font=font, fill=FG)

    # recording dot, top-right inside the tile
    dot_r = a * 0.115
    cx = off + a * 0.78
    cy = off + a * 0.24
    ring = dot_r * 0.28
    d.ellipse([cx - dot_r - ring, cy - dot_r - ring, cx + dot_r + ring, cy + dot_r + ring], fill=DOT_RING)
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=DOT)

    return img.resize((canvas_px, canvas_px), Image.LANCZOS)


def main() -> None:
    ICONS.mkdir(exist_ok=True)
    STORE.mkdir(exist_ok=True)

    # Package icons: artwork fills the tile at small sizes for legibility;
    # the 128 keeps the 96/128 store proportion.
    for size, artwork in [(16, 16), (32, 32), (48, 44), (128, 96)]:
        out = ICONS / f"icon{size}.png"
        draw_mark(size, artwork).save(out, optimize=True)
        print(f"wrote {out.relative_to(ROOT)} ({size}x{size}, artwork {artwork})")

    # Store icon: same as the 128 package icon (96px artwork + padding).
    store_icon = STORE / "store-icon-128.png"
    draw_mark(128, 96).save(store_icon, optimize=True)
    print(f"wrote {store_icon.relative_to(ROOT)} (128x128)")

    # Small promo tile 440x280: saturated indigo field, centered mark + name.
    promo = Image.new("RGBA", (440, 280), BG)
    mark = draw_mark(150, 142)
    promo.alpha_composite(mark, (28, 65))
    d = ImageDraw.Draw(promo)
    title_font = load_font(42)
    sub_font = load_font(19)
    d.text((196, 96), "VeriBridge", font=title_font, fill=FG)
    d.text((198, 150), "Website Proof Recorder", font=sub_font, fill=(199, 210, 254, 255))
    promo_path = STORE / "promo-small-440x280.png"
    promo.convert("RGB").save(promo_path, optimize=True)
    print(f"wrote {promo_path.relative_to(ROOT)} (440x280)")


if __name__ == "__main__":
    main()
