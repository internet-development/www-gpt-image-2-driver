#!/usr/bin/env python3
"""Batch Bayer ordered-dithering processor (AAA-game-style) — sibling to imagegen.py.

Takes any image(s) — a file, a folder, or many paths/globs — applies a Bayer ordered
("ordered dithering") diffusion in the chunky, high-contrast look games use for that crisp
retro/stylized banding, and writes each result as a PNG into the shared `generated/` folder,
prefixed `processed-bayer-`:

    <anything>.jpg  ->  generated/processed-bayer-<name>.png

Pure-PIL (no numpy): the threshold matrix is tiled to image size once, then every colour
channel is dithered with two vectorised C-level PIL ops (ImageChops.add + a point LUT), so it
is fast even on large images.

Usage
-----
    python3 bayer.py IMAGE [IMAGE ...]      # files, folders, or globs
    python3 bayer.py base_poses             # a folder name under the repo root
    python3 bayer.py generated/foo.png --levels 4 --matrix 8 --pixel-size 2

Flags
-----
    --levels N        colour levels PER channel (2-256, default 4 -> 64-colour dither look)
    --matrix {2,4,8}  Bayer matrix size; bigger = finer dither pattern (default 4)
    --strength F      dither amount 0.0-1.0 (default 1.0 = full ordered dither)
    --pixel-size N    downsample by N before dithering, then nearest-upscale (default 1 = off;
                      >1 gives chunky "low-res console" pixels with the dither baked in)
    --out-dir DIR     output folder (default generated/)
    --force           overwrite existing processed-bayer-*.png (default: skip if present)
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
PREFIX = "processed-bayer-"


# --------------------------------------------------------------------------- #
# Bayer matrix
# --------------------------------------------------------------------------- #
def bayer_matrix(size: int) -> list[list[int]]:
    """Recursive Bayer (ordered-dither) index matrix of side `size` (a power of two). Values are
    the integers 0 .. size*size-1 in the classic Bayer ordering."""
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


def threshold_tile(size: int, step: float, strength: float) -> Image.Image:
    """An `size`x`size` 'L' image whose pixels are the per-position dither OFFSET to add to a
    channel before quantizing. Offset is centered so that, after adding `step/2` of headroom, the
    floor-quantize LUT performs a correctly-rounded ordered dither. Values land in [0, step], so
    PIL's saturating add only ever clips pixels that already belong to the top level — harmless."""
    matrix = bayer_matrix(size)
    cells = size * size
    data: list[int] = []
    for row in matrix:
        for idx in row:
            bayer_norm = (idx + 0.5) / cells           # in [0, 1)
            centered = (bayer_norm - 0.5) * strength    # in [-0.5, 0.5) * strength
            offset = (centered + 0.5) * step            # shift into [0, step)
            data.append(max(0, min(255, round(offset))))
    tile = Image.new("L", (size, size))
    tile.putdata(data)
    return tile


def tile_to(tile: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Tile a small pattern across a (W, H) canvas using a handful of paste ops (fast: ~W/tw
    horizontal + H/th vertical pastes, all at C level)."""
    w, h = size
    tw, th = tile.size
    strip = Image.new("L", (w, th))
    for x in range(0, w, tw):
        strip.paste(tile, (x, 0))
    full = Image.new("L", (w, h))
    for y in range(0, h, th):
        full.paste(strip, (0, y))
    return full


def quantize_lut(step: float, levels: int) -> list[int]:
    """256-entry lookup: floor each (already dither-biased) channel value to its Bayer level, then
    map the level index back to an evenly-spread 0..255 value."""
    lut: list[int] = []
    for v in range(256):
        idx = int(v / step)
        if idx > levels - 1:
            idx = levels - 1
        lut.append(min(255, round(idx * step)))
    return lut


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
def dither(img: Image.Image, *, levels: int, matrix: int, strength: float,
           pixel_size: int, scale: int) -> Image.Image:
    """Apply Bayer ordered dithering to an image, preserving any alpha channel.

    pixel_size > 1 dithers on a coarser grid (chunkier cells, lower detail). scale > 1
    nearest-upscales the FINAL result, so the output resolution goes up by `scale` and each
    dither cell becomes `pixel_size * scale` output pixels wide — crisp and clearly visible."""
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    orig_size = img.size

    work = img
    if pixel_size > 1:
        w = max(1, orig_size[0] // pixel_size)
        h = max(1, orig_size[1] // pixel_size)
        work = img.resize((w, h), Image.Resampling.LANCZOS)

    step = 255.0 / (levels - 1)
    omap = tile_to(threshold_tile(matrix, step, strength), work.size)
    lut = quantize_lut(step, levels)

    bands = work.split()
    out_bands = []
    for i, band in enumerate(bands):
        if has_alpha and i == 3:        # leave alpha untouched
            out_bands.append(band)
            continue
        biased = ImageChops.add(band, omap)   # saturating add of the dither offset
        out_bands.append(biased.point(lut))   # floor-quantize to the Bayer level
    out = Image.merge(work.mode, out_bands)

    if pixel_size > 1:
        out = out.resize(orig_size, Image.Resampling.NEAREST)
    if scale > 1:
        out = out.resize((orig_size[0] * scale, orig_size[1] * scale), Image.Resampling.NEAREST)
    return out


# --------------------------------------------------------------------------- #
# Filesystem
# --------------------------------------------------------------------------- #
def gather(paths: Sequence[str]) -> list[Path]:
    """Expand each arg (file, folder, or already-expanded glob) into a sorted, de-duplicated list
    of image files, skipping anything we already produced (processed-bayer-*)."""
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
    p = argparse.ArgumentParser(description="AAA-game-style Bayer ordered-dithering batch processor (-> PNG).")
    p.add_argument("inputs", nargs="+", help="image files, folders, or globs to process.")
    p.add_argument("--levels", type=int, default=4, help="colour levels per channel (2-256, default 4).")
    p.add_argument("--matrix", type=int, default=4, choices=[2, 4, 8], help="Bayer matrix size (default 4).")
    p.add_argument("--strength", type=float, default=1.0, help="dither amount 0.0-1.0 (default 1.0).")
    p.add_argument("--pixel-size", type=int, default=1, help="downsample factor before dithering (default 1 = off).")
    p.add_argument("--scale", type=int, default=1,
                   help="nearest-upscale the output by this factor (default 1). Raises output "
                        "resolution AND enlarges the dither cells so the pattern is clearly visible.")
    p.add_argument("--out-dir", default=str(GENERATED), help="output folder (default generated/).")
    p.add_argument("--force", action="store_true", help="overwrite existing processed-bayer-*.png.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (2 <= args.levels <= 256):
        print("error: --levels must be 2..256", file=sys.stderr)
        return 2
    if not (0.0 <= args.strength <= 1.0):
        print("error: --strength must be 0.0..1.0", file=sys.stderr)
        return 2
    if args.pixel_size < 1:
        print("error: --pixel-size must be >= 1", file=sys.stderr)
        return 2
    if args.scale < 1:
        print("error: --scale must be >= 1", file=sys.stderr)
        return 2

    sources = gather(args.inputs)
    if not sources:
        print("error: no image files matched (already-processed and non-images are skipped).", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Bayer dither: {len(sources)} image(s) | levels={args.levels} matrix={args.matrix}x{args.matrix} "
          f"strength={args.strength} pixel-size={args.pixel_size} scale={args.scale} -> {out_dir}/")
    done = 0
    for src in sources:
        dst = out_path(src, out_dir)
        if dst.exists() and not args.force:
            print(f"  skip (exists, use --force): {dst.name}")
            continue
        try:
            with Image.open(src) as im:
                im.load()
                result = dither(im, levels=args.levels, matrix=args.matrix,
                                strength=args.strength, pixel_size=args.pixel_size, scale=args.scale)
            result.save(dst, "PNG", optimize=True)
            print(f"  {src.name} -> {dst.name}")
            done += 1
        except Exception as exc:  # keep the batch going if one file is broken
            print(f"  ! failed on {src.name}: {exc}", file=sys.stderr)

    print(f"done: wrote {done} file(s) to {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
