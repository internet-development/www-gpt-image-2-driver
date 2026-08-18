#!/usr/bin/env python3
"""Indexed palette quantizer (Win95 / MS-Paint / retro-console look) — sibling to imagegen.py.

Snaps any image to a small, period-accurate FIXED palette and writes a true indexed-colour PNG
(mode 'P') into the shared `generated/` folder, prefixed `processed-palette-`:

    <anything>.png  ->  generated/processed-palette-<name>.png

Why indexed quantization (vs a baked display effect like CRT/scanlines or a window frame): the
output stays a clean, reusable ASSET. A mode-'P' PNG is locked to a named palette, so it is tiny,
palette-swappable, and drops straight into game engines, tilesets, and sprite tools — while also
being the authentic engine of the Win95/MS-Paint shading look. Presentation effects bake a frame
into the pixels and can't be reused; this can.

Usage
-----
    python3 palette.py IMAGE [IMAGE ...]              # files, folders, or globs
    python3 palette.py generated --palette win20      # a folder name under the repo root
    python3 palette.py foo.png --palette vga16 --dither ordered

Flags
-----
    --palette NAME    fixed palette: ansi (default, 16 ANSI/text-mode colours), ansi8, win20,
                      vga16/win16, cga, gameboy, grayscale4, bw
    --dither {floyd,ordered,none}
                      floyd (default) = Floyd-Steinberg error diffusion (the classic GIF look);
                      ordered = Bayer pattern dither (MS-Paint pattern-fill shading);
                      none = hard flat banding (pure bucket-fill look).
    --matrix {2,4,8}  Bayer matrix size for --dither ordered (default 4).
    --ordered-amount N  ordered dither strength in 0-255 RGB units (default 80).
    --pixel-size N    downsample by N before quantizing -> chunky low-res sprite (default 1 = off).
    --scale N         nearest-upscale the output by N (default 1; raises resolution, keeps indices).
    --out-dir DIR     output folder (default generated/).
    --force           overwrite existing processed-palette-*.png (default: skip if present).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent
GENERATED = ROOT / "generated"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
PREFIX = "processed-palette-"

# --------------------------------------------------------------------------- #
# Period-accurate fixed palettes
# --------------------------------------------------------------------------- #
_VGA16 = [
    (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
    (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
    (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
]
# The Windows default system palette = the 16 VGA colours + 4 "static" extras.
_WIN20 = _VGA16 + [(192, 220, 192), (166, 202, 240), (255, 251, 240), (160, 160, 164)]

# Canonical ANSI / VGA-text-mode 16-colour palette. Unlike the Windows VGA palette (which uses
# 128/192 intensities), ANSI uses 0xAA/0x55 (170/85) and a brown for "yellow" — so it shifts
# EVERY colour visibly, giving the unmistakable terminal / ANSI-art look. ansi8 = the 8 base
# colours only (no bright variants) for an even harsher, more obvious reduction.
_ANSI = [
    (0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0),          # black, red, green, yellow(brown)
    (0, 0, 170), (170, 0, 170), (0, 170, 170), (170, 170, 170),  # blue, magenta, cyan, white(gray)
    (85, 85, 85), (255, 85, 85), (85, 255, 85), (255, 255, 85),  # bright: gray, red, green, yellow
    (85, 85, 255), (255, 85, 255), (85, 255, 255), (255, 255, 255),  # bright: blue, magenta, cyan, white
]

PALETTES: dict[str, list[tuple[int, int, int]]] = {
    "ansi": _ANSI,
    "ansi8": _ANSI[:8],
    "win20": _WIN20,
    "vga16": _VGA16,
    "win16": _VGA16,
    "cga": [(0, 0, 0), (85, 255, 255), (255, 85, 255), (255, 255, 255)],
    "gameboy": [(15, 56, 15), (48, 98, 48), (139, 172, 15), (155, 188, 15)],
    "grayscale4": [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)],
    "bw": [(0, 0, 0), (255, 255, 255)],
}


def palette_image(colors: Sequence[tuple[int, int, int]]) -> Image.Image:
    """A mode-'P' image whose palette is exactly `colors` (padded to 256 entries for PIL)."""
    flat: list[int] = []
    for r, g, b in colors:
        flat += [r, g, b]
    flat += [0, 0, 0] * (256 - len(colors))
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat)
    return pal


# --------------------------------------------------------------------------- #
# Ordered (Bayer) pre-dither for the MS-Paint pattern look
# --------------------------------------------------------------------------- #
def bayer_matrix(size: int) -> list[list[int]]:
    m = [[0]]
    while len(m) < size:
        n = len(m)
        bigger = [[0] * (n * 2) for _ in range(n * 2)]
        for y in range(n):
            for x in range(n):
                v = m[y][x]
                bigger[y][x] = 4 * v + 0
                bigger[y][x + n] = 4 * v + 2
                bigger[y + n][x] = 4 * v + 3
                bigger[y + n][x + n] = 4 * v + 1
        m = bigger
    return m


def _tile_to(tile: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    tw, th = tile.size
    strip = Image.new("L", (w, th))
    for x in range(0, w, tw):
        strip.paste(tile, (x, 0))
    full = Image.new("L", (w, h))
    for y in range(0, h, th):
        full.paste(strip, (0, y))
    return full


def ordered_predither(img: Image.Image, amount: int, matrix: int) -> Image.Image:
    """Perturb each RGB channel by a centered Bayer pattern (+/- amount/2) so that snapping to the
    fixed palette with NO error-diffusion produces the structured cross-hatch dither MS Paint used
    for its pattern fills, instead of flat banding."""
    cells = matrix * matrix
    data = [round((idx + 0.5) / cells * amount) for row in bayer_matrix(matrix) for idx in row]
    tile = Image.new("L", (matrix, matrix))
    tile.putdata(data)
    omap = _tile_to(tile, img.size)
    half = amount // 2
    out_bands = []
    for band in img.split():
        biased = ImageChops.add(band, omap)            # + (0..amount)
        out_bands.append(biased.point(lambda v: max(0, v - half)))  # shift to (-half..+half)
    return Image.merge("RGB", out_bands)


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
def quantize(img: Image.Image, *, palette: str, dither: str, matrix: int,
             ordered_amount: int, pixel_size: int, scale: int) -> Image.Image:
    colors = PALETTES[palette]
    pal = palette_image(colors)

    # Indexed assets don't carry alpha cleanly; flatten any transparency onto white.
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba).convert("RGB")
    else:
        img = img.convert("RGB")
    orig_size = img.size

    work = img
    if pixel_size > 1:
        w = max(1, orig_size[0] // pixel_size)
        h = max(1, orig_size[1] // pixel_size)
        work = img.resize((w, h), Image.Resampling.LANCZOS)

    if dither == "ordered":
        work = ordered_predither(work, ordered_amount, matrix)
        out = work.quantize(palette=pal, dither=Image.Dither.NONE)
    elif dither == "none":
        out = work.quantize(palette=pal, dither=Image.Dither.NONE)
    else:  # floyd
        out = work.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG)

    # Resizes stay in mode 'P' with NEAREST, so the output remains a clean indexed asset.
    if pixel_size > 1:
        out = out.resize(orig_size, Image.Resampling.NEAREST)
    if scale > 1:
        out = out.resize((orig_size[0] * scale, orig_size[1] * scale), Image.Resampling.NEAREST)
    return out


# --------------------------------------------------------------------------- #
# Filesystem
# --------------------------------------------------------------------------- #
def gather(paths: Sequence[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        rp = p.resolve()
        if (rp not in seen and p.is_file() and p.suffix.lower() in IMAGE_EXTS
                and not p.name.startswith(PREFIX)):
            seen.add(rp)
            found.append(p)

    for raw in paths:
        p = Path(raw)
        candidates = [p] if p.is_absolute() else [p, ROOT / raw]
        target = next((c for c in candidates if c.exists()), p)
        if target.is_dir():
            for child in sorted(target.iterdir()):
                add(child)
        else:
            add(target)
    return found


def out_path(src: Path, out_dir: Path) -> Path:
    return out_dir / f"{PREFIX}{src.stem}.png"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Indexed palette quantizer (Win95/MS-Paint/retro) -> reusable indexed PNG.")
    p.add_argument("inputs", nargs="+", help="image files, folders, or globs to process.")
    p.add_argument("--palette", default="ansi", choices=sorted(PALETTES),
                   help="fixed palette: ansi (default, 16 ANSI/text-mode colours), ansi8, win20, "
                        "vga16/win16, cga, gameboy, grayscale4, bw.")
    p.add_argument("--dither", default="floyd", choices=["floyd", "ordered", "none"], help="dither mode (default floyd).")
    p.add_argument("--matrix", type=int, default=4, choices=[2, 4, 8], help="Bayer matrix for --dither ordered (default 4).")
    p.add_argument("--ordered-amount", type=int, default=80, help="ordered dither strength 0-255 (default 80).")
    p.add_argument("--pixel-size", type=int, default=1, help="downsample factor before quantizing (default 1 = off).")
    p.add_argument("--scale", type=int, default=1, help="nearest-upscale the output by this factor (default 1).")
    p.add_argument("--out-dir", default=str(GENERATED), help="output folder (default generated/).")
    p.add_argument("--force", action="store_true", help="overwrite existing processed-palette-*.png.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (0 <= args.ordered_amount <= 255):
        print("error: --ordered-amount must be 0..255", file=sys.stderr)
        return 2
    if args.pixel_size < 1 or args.scale < 1:
        print("error: --pixel-size and --scale must be >= 1", file=sys.stderr)
        return 2

    sources = gather(args.inputs)
    if not sources:
        print("error: no image files matched (already-processed and non-images are skipped).", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Palette quantize: {len(sources)} image(s) | palette={args.palette} ({len(PALETTES[args.palette])} colours) "
          f"dither={args.dither} pixel-size={args.pixel_size} scale={args.scale} -> {out_dir}/")
    done = 0
    for src in sources:
        dst = out_path(src, out_dir)
        if dst.exists() and not args.force:
            print(f"  skip (exists, use --force): {dst.name}")
            continue
        try:
            with Image.open(src) as im:
                im.load()
                result = quantize(im, palette=args.palette, dither=args.dither, matrix=args.matrix,
                                  ordered_amount=args.ordered_amount, pixel_size=args.pixel_size, scale=args.scale)
            result.save(dst, "PNG", optimize=True)
            print(f"  {src.name} -> {dst.name}")
            done += 1
        except Exception as exc:
            print(f"  ! failed on {src.name}: {exc}", file=sys.stderr)

    print(f"done: wrote {done} indexed PNG(s) to {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
