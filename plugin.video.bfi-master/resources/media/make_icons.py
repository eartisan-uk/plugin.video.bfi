#!/usr/bin/env python3
"""
Generate BFI Player Kodi addon menu icons.

Run once from this directory (resources/media):
    pip install Pillow
    python make_icons.py

Produces 7 new 256x256 PNG files that match the existing flat icon style.
"""
import math
from PIL import Image, ImageDraw

SIZE = 256


def new_icon(color):
    """Rounded-square background in the given RGB colour."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=32, fill=color)
    return img, draw


def save(img, name):
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0))
    out.save(name + ".png")
    print("  wrote", name + ".png")


# ── subscription.png ─ deep-purple background, white 5-pointed star ──────────
def make_subscription():
    img, draw = new_icon((106, 27, 154))
    cx, cy, ro, ri = 128, 128, 88, 36
    pts = []
    for i in range(10):
        r = ro if i % 2 == 0 else ri
        a = math.radians(-90 + i * 36)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    draw.polygon(pts, fill="white")
    save(img, "subscription")


# ── free.png ─ teal background, white play-button triangle ───────────────────
def make_free():
    img, draw = new_icon((0, 105, 92))
    cx, cy = 136, 128       # slightly right-of-centre for optical balance
    r = 82
    draw.polygon(
        [(cx - r * 0.6, cy - r), (cx - r * 0.6, cy + r), (cx + r * 0.75, cy)],
        fill="white"
    )
    save(img, "free")


# ── exclusives.png ─ amber background, white gem/diamond ─────────────────────
def make_exclusives():
    img, draw = new_icon((245, 127, 23))
    cx, cy = 128, 132
    # Outer gem shape
    outer = [
        (cx, cy - 88),
        (cx + 78, cy - 18),
        (cx + 68, cy + 82),
        (cx - 68, cy + 82),
        (cx - 78, cy - 18),
    ]
    draw.polygon(outer, fill="white")
    # Recessed inner facet (background colour)
    inner = [
        (cx, cy - 50),
        (cx + 42, cy - 4),
        (cx + 36, cy + 44),
        (cx - 36, cy + 44),
        (cx - 42, cy - 4),
    ]
    draw.polygon(inner, fill=(245, 127, 23))
    save(img, "exclusives")


# ── recently-added.png ─ indigo background, white clock face ─────────────────
def make_recently_added():
    img, draw = new_icon((40, 53, 147))
    cx, cy, r = 128, 128, 86
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="white")
    draw.ellipse([cx - r + 13, cy - r + 13, cx + r - 13, cy + r - 13], fill=(40, 53, 147))
    # 12 o'clock hour hand
    draw.line([(cx, cy), (cx, cy - 54)], fill="white", width=11)
    # 3 o'clock minute hand
    draw.line([(cx, cy), (cx + 44, cy)], fill="white", width=9)
    # Centre dot
    draw.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill="white")
    save(img, "recently-added")


# ── coming-soon.png ─ deep-orange background, white calendar ─────────────────
def make_coming_soon():
    bg = (230, 81, 0)
    img, draw = new_icon(bg)
    x0, y0, x1, y1 = 44, 62, 212, 208
    # Calendar body
    draw.rounded_rectangle([x0, y0, x1, y1], radius=12, fill="white")
    # Header band (background colour)
    draw.rounded_rectangle([x0, y0, x1, y0 + 54], radius=12, fill=bg)
    draw.rectangle([x0, y0 + 34, x1, y0 + 54], fill=bg)
    # Ring pegs
    for px in (78, 178):
        draw.ellipse([px - 11, y0 - 17, px + 11, y0 + 17], fill="white")
        draw.ellipse([px - 7,  y0 - 13, px + 7,  y0 + 13], fill=bg)
    # Day-dot grid (3 rows x 4 cols)
    for row in range(3):
        for col in range(4):
            dx, dy = 72 + col * 37, 132 + row * 26
            draw.ellipse([dx - 8, dy - 8, dx + 8, dy + 8], fill=bg)
    save(img, "coming-soon")


# ── inside-film.png ─ blue background, white clapperboard ────────────────────
def make_inside_film():
    bg = (21, 101, 192)
    img, draw = new_icon(bg)
    # Board body
    draw.rounded_rectangle([42, 96, 214, 208], radius=10, fill="white")
    # Clapper top bar (white)
    draw.rounded_rectangle([42, 52, 214, 100], radius=8, fill="white")
    # Diagonal black stripes on the clapper
    stripe_w = 26
    for i in range(8):
        x = 42 + i * stripe_w * 2
        draw.polygon(
            [(x, 52), (x + stripe_w, 52), (x + stripe_w - 12, 100), (x - 12, 100)],
            fill=bg
        )
    # Hinge joint (cover the stripe edges at the join)
    draw.rectangle([42, 88, 214, 100], fill=bg)
    draw.rectangle([42, 96, 214, 106], fill="white")
    # Play triangle in body
    bx, by = 130, 158
    draw.polygon([(bx - 30, by - 38), (bx - 30, by + 38), (bx + 44, by)], fill=bg)
    save(img, "inside-film")


# ── shorts.png ─ deep-purple background, white film strip ────────────────────
def make_shorts():
    bg = (69, 39, 160)
    img, draw = new_icon(bg)
    # Central white film strip band
    draw.rectangle([52, 82, 204, 174], fill="white")
    # Top and bottom edge strips
    for y0, y1 in [(62, 82), (174, 194)]:
        draw.rectangle([52, y0, 204, y1], fill="white")
    # Sprocket holes
    for y in [100, 128, 156]:
        draw.rounded_rectangle([36, y - 11, 60, y + 11], radius=5, fill=bg)
        draw.rounded_rectangle([196, y - 11, 220, y + 11], radius=5, fill=bg)
    # Frame dividers
    draw.rectangle([96, 82, 106, 174], fill=bg)
    draw.rectangle([150, 82, 160, 174], fill=bg)
    # Play triangle in the middle frame
    draw.polygon([(111, 108), (111, 148), (148, 128)], fill=bg)
    save(img, "shorts")


if __name__ == "__main__":
    print("Generating BFI Player menu icons...")
    make_subscription()
    make_free()
    make_exclusives()
    make_recently_added()
    make_coming_soon()
    make_inside_film()
    make_shorts()
    print("Done — 7 icons written to this directory.")
