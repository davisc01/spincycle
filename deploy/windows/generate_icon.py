#!/usr/bin/env python3
"""Build icon.ico from the same isolated, centered dial artwork
deploy/macos/generate_icon_source.py produces for icon.icns -- crop near
the left knob of the full car-stereo faceplate (spin_cycle_icon_1024.png),
mask out everything past its chrome bezel, composite onto a procedural
wood-grain background, then let Pillow's multi-size ICO writer do the
scaling instead of macOS's sips/iconutil dance.

Crop/mask coordinates are the same ones derived for the macOS icon (see
that script's docstring for the pixel-sampling derivation) -- duplicated
here rather than imported, since the two build pipelines don't otherwise
share any code and this is the only piece in common.
"""
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

SRC_FULL = "../../app/images/spin_cycle_icon_1024.png"
OUT_PATH = "icon.ico"
OUT_SIZE = 1024

KNOB_CROP_BOX = (67, 382, 247, 562)  # 180x180, centered on the knob
KNOB_CENTER_LOCAL = (90, 90)  # crop is centered on the knob by construction
KNOB_RADIUS = 78
KNOB_FRACTION_OF_CANVAS = 0.82  # how much of the final square the dial fills

WOOD_DARK = (92, 58, 34)
WOOD_LIGHT = (168, 122, 74)
WOOD_SEED = 42

ICO_SIZES = [(16, 16), (32, 32), (48, 48), (256, 256)]


def make_wood_texture(size, seed=WOOD_SEED):
    random.seed(seed)

    base_col = Image.new("RGB", (1, size))
    pixels = base_col.load()
    for y in range(size):
        t = (math.sin(y / 37.0) * 0.5 + math.sin(y / 11.0) * 0.15 + 0.65) / 1.3
        t = max(0.0, min(1.0, t))
        pixels[0, y] = tuple(
            int(WOOD_DARK[c] + (WOOD_LIGHT[c] - WOOD_DARK[c]) * t) for c in range(3)
        )
    base = base_col.resize((size, size), Image.BILINEAR)

    grain = Image.new("L", (size, size), 200)
    draw = ImageDraw.Draw(grain)
    for _ in range(170):
        y0 = random.uniform(0, size)
        amp = random.uniform(2, 14)
        freq = random.uniform(1.5, 4.0)
        phase = random.uniform(0, math.tau)
        shade = random.randint(70, 190)
        width = random.choice([1, 1, 1, 2])
        points = [
            (x, y0 + amp * math.sin(freq * math.tau * x / size + phase))
            for x in range(0, size + 8, 8)
        ]
        draw.line(points, fill=shade, width=width)
    grain = grain.filter(ImageFilter.GaussianBlur(1))
    grain_rgb = Image.merge("RGB", (grain, grain, grain))

    wood = ImageChops.multiply(base, grain_rgb)
    wood = ImageEnhance.Brightness(wood).enhance(1.25)  # multiply darkens on average

    noise = Image.effect_noise((size, size), 24)
    noise = ImageEnhance.Contrast(noise).enhance(0.35)
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    wood = ImageChops.overlay(wood, noise_rgb)

    return wood


def isolate_knob(src_full):
    im = Image.open(src_full).convert("RGBA")
    crop = im.crop(KNOB_CROP_BOX)

    supersample = 4
    big_size = crop.size[0] * supersample
    cx, cy = (c * supersample for c in KNOB_CENTER_LOCAL)
    r = KNOB_RADIUS * supersample
    mask_big = Image.new("L", (big_size, big_size), 0)
    ImageDraw.Draw(mask_big).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    mask = mask_big.resize(crop.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.5))

    masked_knob = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    masked_knob.paste(crop, (0, 0), mask)
    return masked_knob


def main():
    masked_knob = isolate_knob(SRC_FULL)

    wood = make_wood_texture(OUT_SIZE).convert("RGBA")

    target_diameter = round(OUT_SIZE * KNOB_FRACTION_OF_CANVAS)
    scale = target_diameter / (2 * KNOB_RADIUS)
    resized_size = round(masked_knob.size[0] * scale)
    resized_knob = masked_knob.resize((resized_size, resized_size), Image.LANCZOS)

    offset = (OUT_SIZE - resized_size) // 2
    wood.paste(resized_knob, (offset, offset), resized_knob)

    wood.convert("RGB").save(OUT_PATH, format="ICO", sizes=ICO_SIZES)


if __name__ == "__main__":
    main()
