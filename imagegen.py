#!/usr/bin/env python3
"""Dynamic style tools for gpt-image-2 — ONE learned hand, three jobs.

This script learns a hand from a folder of reference art (the shared `learn_style`
pipeline: 7-lens manual -> compose -> concretize -> staging), then puts it to work
in one of three modes, each documented in its own card:

    match  (RUN_MATCH.md)   <style>/sample-*            -> generated/<style>-generated-<n>.png
            prove the superset style with N INVENTED subjects (`step1` is an alias).
    make   (RUN_MAKE.md)    <style>/sample-* + --prompt -> generated/<style>-make-generated-<n>.png
            draw a NEW, TEXT-GIVEN subject ("an archer") in that hand. No subject image.
    clone  (RUN_CLONE.md)   <style> + <target>/*        -> generated/<target>-clone-generated-<n>.png
            redraw EVERY existing image in a folder in that hand, 1-to-1.

Design goals
------------
* gpt-image-2. The default `codex` backend drives the live, already-authenticated
  Codex session and its built-in `image_gen` tool (no OPENAI_API_KEY needed); that
  built-in tool uses gpt-image-2. The optional `cli` backend calls the bundled
  imagegen CLI with `--model gpt-image-2` (needs OPENAI_API_KEY).
* Fully dynamic. Nothing is hardcoded to a sample count or filename. Every style
  summary and the deep style bible are *derived* from the pixels of whatever
  `sample-*` files currently exist, so changing the samples changes the prompt.
* Maximum style fidelity. The style study runs deep vision passes that actually look
  at the art and write a depictable style directive (the soul), then generate with
  gpt-image-2 driven by that directive plus the real full-resolution sample art. The
  describing prose is held to a museum-grade register matched to the observed medium
  (the shared `DICTION` directive), because an image model obeys register as much as
  nouns and the most compressed, exact word is also the most depictable.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat


ROOT = Path(__file__).resolve().parent
BASE_ILLUSTRATION = ROOT / "base_illustration"
RUNS_DIR = ROOT / "_temporary"


def output_dir_for(folder: Path) -> Path:
    """All generated deliverables live in ONE shared `generated/` dir; every file is prefixed
    with its source folder name (e.g. base_illustration -> generated/base_illustration-generated-3.png).
    One folder instead of a `<name>_generated/` per source keeps outputs simple to manage."""
    return ROOT / "generated"

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_GENERATED = CODEX_HOME / "generated_images"
DEFAULT_IMAGEGEN_CLI = CODEX_HOME / "skills/.system/imagegen/scripts/image_gen.py"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SUPERSET_NAME = "generated-superset-style.png"

DEFAULT_MODEL = "gpt-image-2"
DEFAULT_QUALITY = "high"
# A gpt-image-2-valid portrait (1024*1536 = 1,572,864 px, 3:2, both /16).
DEFAULT_SIZE = "1024x1536"
# Final deliverable size: 5:7 portrait at 300 DPI (1500x2100 = 5"x7"). Every codex-backend
# output is cover-cropped to exactly this so all generations share one resolution/aspect.
DEFAULT_TARGET_SIZE = "1500x2100"
OUTPUT_DPI = (300, 300)

GENERATED_RE = re.compile(r"GENERATED=(\S+)")
# Codex echoes the prompt in stdout, so each sentinel appears twice; take the LAST match.
BRIEF_RE = re.compile(r"<<<BRIEF\s*(.*?)\s*BRIEF>>>", re.DOTALL)
PROMPT_RE = re.compile(r"<<<PROMPT\s*(.*?)\s*PROMPT>>>", re.DOTALL)


# --------------------------------------------------------------------------- #
# Filesystem discovery
# --------------------------------------------------------------------------- #
def natural_key(path: Path) -> list[object]:
    parts: list[object] = []
    current = ""
    for ch in path.stem:
        if ch.isdigit():
            current += ch
        else:
            if current:
                parts.append(int(current))
                current = ""
            parts.append(ch)
    if current:
        parts.append(int(current))
    return parts


def _matching(folder: Path, prefix: str) -> list[Path]:
    if not folder.is_dir():
        return []
    found = [
        p
        for p in folder.iterdir()
        if p.is_file()
        and p.name.startswith(prefix)
        and p.suffix.lower() in IMAGE_EXTS
        and p.name != SUPERSET_NAME
    ]
    return sorted(found, key=natural_key)


def sample_images(folder: Path) -> list[Path]:
    return _matching(folder, "sample-")


# --------------------------------------------------------------------------- #
# Image helpers (reference pack + metrics)
# --------------------------------------------------------------------------- #
def open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as img:
        img.load()
        return img.convert("RGB")


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def fit_image(img: Image.Image, size: tuple[int, int], fill: tuple[int, int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, fill)
    copy = img.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    canvas.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
    return canvas


def make_contact_sheet(paths: Sequence[Path], out: Path, *, title: str, columns: int = 4) -> Path:
    cell = (520, 520)
    columns = max(1, min(columns, len(paths)))
    rows = math.ceil(len(paths) / columns)
    label_h, title_h, margin = 60, 76, 24
    bg = (240, 232, 212)
    width = columns * cell[0] + (columns + 1) * margin
    height = title_h + rows * (cell[1] + label_h) + (rows + 1) * margin
    sheet = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 22), title, fill=(30, 25, 18), font=load_font(28))
    label_font = load_font(18)
    for i, path in enumerate(paths):
        row, col = divmod(i, columns)
        x = margin + col * (cell[0] + margin)
        y = title_h + margin + row * (cell[1] + label_h + margin)
        sheet.paste(fit_image(open_rgb(path), cell, bg), (x, y))
        draw.rectangle([x, y, x + cell[0] - 1, y + cell[1] - 1], outline=(70, 58, 42), width=2)
        draw.text((x, y + cell[1] + 10), path.name, fill=(30, 25, 18), font=label_font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    return out


def edge_panel(path: Path, size: tuple[int, int]) -> Image.Image:
    img = fit_image(open_rgb(path), size, (242, 237, 222)).convert("L")
    edges = ImageOps.autocontrast(img).filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.invert(ImageOps.autocontrast(edges))
    return Image.merge("RGB", (edges, edges, edges))


def value_panel(path: Path, size: tuple[int, int]) -> Image.Image:
    img = ImageOps.autocontrast(fit_image(open_rgb(path), size, (242, 237, 222)).convert("L"))
    img = ImageOps.posterize(img, 3)
    return Image.merge("RGB", (img, img, img))


def make_analysis_sheet(paths: Sequence[Path], out: Path, *, mode: str) -> Path:
    cell = (420, 420)
    columns = max(1, min(4, len(paths)))
    rows = math.ceil(len(paths) / columns)
    label_h, title_h, margin = 48, 64, 20
    width = columns * cell[0] + (columns + 1) * margin
    height = title_h + rows * (cell[1] + label_h) + (rows + 1) * margin
    sheet = Image.new("RGB", (width, height), (240, 232, 212))
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 20), f"{mode} retention sheet", fill=(30, 25, 18), font=load_font(24))
    label_font = load_font(16)
    for i, path in enumerate(paths):
        row, col = divmod(i, columns)
        x = margin + col * (cell[0] + margin)
        y = title_h + margin + row * (cell[1] + label_h + margin)
        panel = edge_panel(path, cell) if mode == "edge" else value_panel(path, cell)
        sheet.paste(panel, (x, y))
        draw.rectangle([x, y, x + cell[0] - 1, y + cell[1] - 1], outline=(70, 58, 42), width=2)
        draw.text((x, y + cell[1] + 8), path.name, fill=(30, 25, 18), font=label_font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    return out


def quantized_palette(path: Path, colors: int = 8) -> list[tuple[int, int, int]]:
    img = open_rgb(path)
    img.thumbnail((220, 220), Image.Resampling.LANCZOS)
    quantized = img.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    swatches: list[tuple[int, int, int]] = []
    for _, idx in sorted(quantized.getcolors() or [], reverse=True)[:colors]:
        base = idx * 3
        if base + 2 < len(palette):
            swatches.append((palette[base], palette[base + 1], palette[base + 2]))
    return swatches


def make_palette_sheet(paths: Sequence[Path], out: Path) -> Path:
    row_h, label_w, swatch_w, title_h, margin = 64, 170, 72, 64, 22
    width = label_w + 8 * swatch_w + 2 * margin
    height = title_h + len(paths) * row_h + margin
    sheet = Image.new("RGB", (width, height), (240, 232, 212))
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 20), "dominant color memory", fill=(30, 25, 18), font=load_font(24))
    label_font = load_font(16)
    for i, path in enumerate(paths):
        y = title_h + i * row_h
        draw.text((margin, y + 18), path.name, fill=(30, 25, 18), font=label_font)
        for j, color in enumerate(quantized_palette(path, 8)):
            x = margin + label_w + j * swatch_w
            draw.rectangle([x, y + 10, x + swatch_w - 8, y + row_h - 10], fill=color, outline=(60, 50, 38))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    return out


def image_metrics(path: Path) -> dict[str, object]:
    img = open_rgb(path)
    w, h = img.size
    small = img.copy()
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = small.convert("L")
    stat = ImageStat.Stat(gray)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    histogram = gray.histogram()
    total = max(1, gray.width * gray.height)
    sat = ImageEnhance.Color(small).enhance(1.0).convert("HSV").split()[1]
    return {
        "file": path.name,
        "width": w,
        "height": h,
        "aspect": round(w / h, 3),
        "brightness_mean": round(float(stat.mean[0]), 2),
        "brightness_stddev": round(float(stat.stddev[0]), 2),
        "edge_density": round(float(ImageStat.Stat(edges).mean[0]) / 255.0, 4),
        "dark_mass_ratio": round(sum(histogram[:48]) / total, 4),
        "paper_light_ratio": round(sum(histogram[225:]) / total, 4),
        "saturation_mean": round(float(ImageStat.Stat(sat).mean[0]) / 255.0, 4),
        "palette": quantized_palette(path, 6),
    }


def derive_observation(m: dict[str, object]) -> str:
    """Turn raw metrics into a short, dynamic style sentence (no hardcoding)."""
    edge = float(m["edge_density"])
    dark = float(m["dark_mass_ratio"])
    light = float(m["paper_light_ratio"])
    sat = float(m["saturation_mean"])
    bright = float(m["brightness_mean"])

    if edge >= 0.16:
        line = "dense, busy linework and hatching"
    elif edge >= 0.09:
        line = "moderate hand-drawn linework"
    else:
        line = "soft, painterly edges with little hard outline"

    if dark >= 0.22:
        value = "heavy black masses and deep shadow"
    elif light >= 0.30:
        value = "light/high-key with large bright or empty areas"
    else:
        value = "balanced mid-value rendering"

    if sat >= 0.40:
        color = "saturated, bold color"
    elif sat <= 0.16:
        color = "muted, near-monochrome color"
    else:
        color = "restrained, mid-saturation color"

    key = "high-key/bright" if bright >= 170 else "low-key/dark" if bright <= 95 else "mid-key"
    return f"{line}; {value}; {color}; {key} overall"


def _hexes(colors: Sequence[tuple[int, int, int]]) -> str:
    return ", ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in colors)


def aggregate_summary(metrics: Sequence[dict[str, object]]) -> str:
    if not metrics:
        return "No samples were found to characterize."
    edge = statistics.median(float(m["edge_density"]) for m in metrics)
    dark = statistics.median(float(m["dark_mass_ratio"]) for m in metrics)
    light = statistics.median(float(m["paper_light_ratio"]) for m in metrics)
    sat = statistics.median(float(m["saturation_mean"]) for m in metrics)
    counts: dict[tuple[int, int, int], int] = {}
    for m in metrics:
        for c in m["palette"]:  # type: ignore[index]
            counts[c] = counts.get(c, 0) + 1
    top = [c for c, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]]
    linework = "hard-edged/line-forward" if edge >= 0.13 else "soft-edged/low-line" if edge <= 0.08 else "mixed line-and-fill"
    return (
        f"Across {len(metrics)} samples the shared style reads as {linework}. "
        f"Median edge density {edge:.3f}, dark-mass ratio {dark:.3f}, light/empty ratio {light:.3f}, "
        f"saturation {sat:.3f}. Dominant shared palette: {_hexes(top)}. "
        "Reproduce the medium, density, and finish exactly as the MAJORITY of samples show — "
        "traditional or digital, polished or deliberately crude, smooth or textured — never a "
        "default, never an 'upgraded' (prettified) look, and never a 'roughened' (grunged / "
        "texture-added) look; do not let one outlier or mere scan grain set the finish."
    )


# --------------------------------------------------------------------------- #
# Quantitative style fingerprint (measured facts to ground the prompt)
# --------------------------------------------------------------------------- #
_NAMED_COLORS = {
    "paper cream": (240, 232, 210), "white": (250, 250, 248), "ink black": (22, 20, 18),
    "graphite grey": (120, 120, 120), "oxblood": (140, 45, 40), "red": (200, 55, 45),
    "orange": (215, 120, 45), "ochre/gold": (190, 150, 70), "yellow": (225, 200, 90),
    "moss green": (95, 120, 70), "teal": (60, 130, 130), "cobalt blue": (70, 95, 165),
    "navy": (40, 50, 90), "violet": (110, 85, 145), "brown": (120, 80, 55),
    "skin/peach": (225, 175, 150),
}


def _color_name(rgb: tuple[int, int, int]) -> str:
    return min(_NAMED_COLORS, key=lambda n: sum((rgb[i] - _NAMED_COLORS[n][i]) ** 2 for i in range(3)))


def _aggregate_palette(samples: Sequence[Path], k: int = 10) -> list[tuple[tuple[int, int, int], int]]:
    """k-means-ish dominant palette across ALL samples (montage + median-cut), with the
    percentage of area each color occupies."""
    cell = 96
    cols = min(6, len(samples))
    rows = math.ceil(len(samples) / cols)
    montage = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    for i, p in enumerate(samples):
        im = open_rgb(p)
        im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        montage.paste(im, ((i % cols) * cell, (i // cols) * cell))
    q = montage.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette() or []
    counts = q.getcolors() or []
    total = sum(c for c, _ in counts) or 1
    out: list[tuple[tuple[int, int, int], int]] = []
    for count, idx in sorted(counts, reverse=True)[:k]:
        base = idx * 3
        if base + 2 < len(palette):
            out.append(((palette[base], palette[base + 1], palette[base + 2]), round(100 * count / total)))
    return out


def finish_metrics(path: Path) -> dict[str, float]:
    """Measured FINISH facts computed at NATIVE resolution. A downscaled view (the model's
    image ingestion, or our own 512px thumbnails) smooths a crude/lo-fi hand into what looks
    like clean anti-aliased illustration — the classic 'upgrade' misread. These numbers can't
    be fooled: true ink stroke width and wobble, edge softness, the scale detail lives at,
    and how much of the page is flat bucket-fill."""
    img = open_rgb(path)
    w, h = img.size
    gray = img.convert("L")

    # Ink stroke width + wobble: erode the dark-ink mask and watch how fast it dies. A stroke
    # of width n survives ~(n-1)/2 erosions, so the survival curve gives width quantiles.
    ink = gray.point(lambda v: 255 if v < 80 else 0)
    total = ImageStat.Stat(ink).sum[0] / 255.0
    q25 = q50 = q75 = 0.0
    if total / max(1, w * h) > 0.005:  # need a real ink presence to measure
        survival: list[float] = []
        m = ink
        for _ in range(12):
            m = m.filter(ImageFilter.MinFilter(3))
            survival.append((ImageStat.Stat(m).sum[0] / 255.0) / total)

        def width_at(frac: float) -> float:
            for i, s in enumerate(survival, 1):
                if s < frac:
                    return 2 * i - 1
            return 2 * len(survival) + 1

        q25, q50, q75 = width_at(0.75), width_at(0.50), width_at(0.25)

    # Edge softness: of the pixels that ARE edges, how many are mid-strength transitions
    # (anti-aliasing / upscale smoothing) vs hard jumps (crisp or aliased edges).
    edges = gray.filter(ImageFilter.FIND_EDGES)
    hist = edges.histogram()
    mid, hard = sum(hist[40:150]), sum(hist[150:])
    edge_soft = mid / max(1, mid + hard)

    # Detail scale: edge energy at native vs at 512px. Fine micro-detail keeps its energy at
    # native; big blunt marks (or an upscaled lo-fi original) lose most of it.
    small = gray.copy()
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    density_native = float(ImageStat.Stat(edges).mean[0])
    density_small = float(ImageStat.Stat(small.filter(ImageFilter.FIND_EDGES)).mean[0])
    detail_ratio = density_native / max(1e-6, density_small)

    # Flat-fill coverage: fraction of ~48px cells whose tone barely varies (bucket-fill flats).
    cols, rows = max(1, w // 48), max(1, h // 48)
    cell_mean = gray.resize((cols, rows), Image.Resampling.BOX)
    deviation = ImageChops.difference(gray, cell_mean.resize((w, h), Image.Resampling.NEAREST))
    mad = deviation.resize((cols, rows), Image.Resampling.BOX)
    px = mad.load()
    flat = sum(1 for y in range(rows) for x in range(cols) if px[x, y] < 6)
    flat_ratio = flat / max(1, cols * rows)

    return {"page_w": float(w), "stroke_q25": q25, "stroke_q50": q50, "stroke_q75": q75,
            "edge_soft_ratio": round(edge_soft, 3), "detail_ratio": round(detail_ratio, 3),
            "flat_fill_ratio": round(flat_ratio, 3)}


def style_fingerprint(samples: Sequence[Path], metrics: Sequence[dict[str, object]]) -> str:
    """A measured, deterministic signature of the sample set — concrete numbers that anchor
    the prompt so gpt-image-2 has far less room to drift toward its own defaults."""
    pal = _aggregate_palette(samples, 10)
    pal_str = ", ".join(f"#{r:02x}{g:02x}{b:02x} ({_color_name((r, g, b))}) ~{pct}%" for (r, g, b), pct in pal)
    med = lambda key: statistics.median(float(m[key]) for m in metrics)
    edge, dark, paper, sat, bright = (med("edge_density"), med("dark_mass_ratio"),
                                      med("paper_light_ratio"), med("saturation_mean"), med("brightness_mean"))
    aspects = sorted({round(float(m["aspect"]), 2) for m in metrics})
    line_desc = "busy/dense linework" if edge >= 0.16 else "moderate linework" if edge >= 0.09 else "sparse/open"
    sat_desc = "saturated" if sat >= 0.40 else "muted/near-monochrome" if sat <= 0.16 else "restrained"

    # FINISH facts at native resolution — the anti-"upgrade" evidence. (A downscaled view
    # smooths a crude/lo-fi hand into apparent clean illustration; these numbers don't.)
    fm = [finish_metrics(p) for p in samples]
    fmed = lambda key: statistics.median(f[key] for f in fm)
    stroke_px = fmed("stroke_q50")
    page_w = fmed("page_w")
    stroke_pm = stroke_px / max(1.0, page_w) * 1000  # per-mille of page width
    wobble = (fmed("stroke_q75") - fmed("stroke_q25")) / max(1.0, stroke_px)
    soft, det, flat = fmed("edge_soft_ratio"), fmed("detail_ratio"), fmed("flat_fill_ratio")
    stroke_desc = ("THICK, blunt strokes" if stroke_pm >= 4.5
                   else "medium-weight strokes" if stroke_pm >= 2.5 else "fine strokes")
    wobble_desc = ("stroke-width variation unmeasurable at this line weight" if stroke_px < 3
                   else "width varies strongly along a single stroke — an uneven, hand-guided "
                   "(mouse-like) line, NOT a calligraphic or vector line" if wobble >= 0.6
                   else "moderately uneven stroke width" if wobble >= 0.3
                   else "even, controlled stroke width")
    soft_desc = ("edges are reproduction-softened (upscaling / resampling blur) — do NOT read "
                 "this softness as a refined anti-aliased digital hand" if soft >= 0.55
                 else "hard, crisp edge transitions (aliased or near-aliased)")
    det_desc = ("detail lives at a COARSE scale: the page is built from FEW, LARGE, simple "
                "marks (a LOW-DETAIL hand — a downscaled view makes it look far more refined "
                "and detailed than it really is)" if det < 0.6
                else "detail present at medium scale" if det < 0.85
                else "genuine fine micro-detail survives at native pixels")
    flat_desc = ("flat bucket-fill color fields dominate" if flat >= 0.45
                 else "fills are partly modulated" if flat >= 0.2 else "fills are heavily modulated/painterly")

    return (
        f"- Measured palette (median-cut across all {len(samples)} samples, by area): {pal_str}\n"
        f"- Linework density (edge ratio): median {edge:.3f} ({line_desc})\n"
        f"- Notan/value: deep-shadow area ~{dark * 100:.0f}%, bright/light area ~{paper * 100:.0f}%, "
        f"mean brightness {bright:.0f}/255\n"
        f"- Saturation: median {sat:.3f} ({sat_desc})\n"
        f"- Aspect ratios present (w/h): {aspects}\n"
        f"- Ink stroke width (NATIVE pixels): median ~{stroke_px:.0f}px on a {page_w:.0f}px-wide page "
        f"(~{stroke_pm:.1f}/1000 of page width) → {stroke_desc}; {wobble_desc}\n"
        f"- Edge finish (NATIVE pixels): soft-edge fraction {soft:.2f} → {soft_desc}\n"
        f"- Detail scale: native-vs-downscaled edge-energy ratio {det:.2f} → {det_desc}\n"
        f"- Flat-fill coverage: {flat:.0%} of the page is near-constant color → {flat_desc}"
    )


# --------------------------------------------------------------------------- #
# Reference pack (human-facing study aids)
# --------------------------------------------------------------------------- #
def make_technique_sheet(paths: Sequence[Path], out: Path, *, tiles: int = 9, tile: int = 320) -> Path:
    """NATIVE-PIXEL technique crops (1:1, no resampling) — the finish evidence that a
    downscaled full view destroys: true edge quality (aliased / anti-aliased / upscale-
    softened), stroke bluntness and wobble, real mark size, and fill flatness. Attached to
    every style-study vision pass so the model judges finish from actual pixels, not from
    its shrunken view of the whole page. Kept compact (~3 tiles wide at 1:1) so the sheet
    itself survives the model's ingestion without heavy downscaling."""
    per_sample: list[list[tuple[Path, int, int]]] = []
    for p in paths:
        img = open_rgb(p)
        if img.width < tile or img.height < tile:
            continue
        edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
        cols, rows = max(1, img.width // tile), max(1, img.height // tile)
        cell = edges.resize((cols, rows), Image.Resampling.BOX)
        px = cell.load()
        ranked = sorted(((px[x, y], x, y) for y in range(rows) for x in range(cols)), reverse=True)
        busiest, typical = ranked[0], ranked[len(ranked) // 3]
        pair = []
        for _, cx, cy in (busiest, typical):
            x = min(cx * tile, img.width - tile)
            y = min(cy * tile, img.height - tile)
            pair.append((p, x, y))
        per_sample.append(pair)
    picks: list[tuple[Path, int, int]] = []
    for rank in range(2):  # busiest crop of each sample first, then the typical ones
        for pair in per_sample:
            if len(picks) < tiles and rank < len(pair):
                picks.append(pair[rank])
    columns, margin, label_h, title_h = 3, 14, 26, 56
    rows_n = max(1, math.ceil(len(picks) / columns))
    width = columns * tile + (columns + 1) * margin
    height = title_h + rows_n * (tile + label_h + margin) + margin
    sheet = Image.new("RGB", (width, height), (240, 232, 212))
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 16), "technique crops - NATIVE pixels, 1:1, unresampled", fill=(30, 25, 18), font=load_font(22))
    label_font = load_font(14)
    for i, (p, x, y) in enumerate(picks):
        row, col = divmod(i, columns)
        sx = margin + col * (tile + margin)
        sy = title_h + row * (tile + label_h + margin)
        sheet.paste(open_rgb(p).crop((x, y, x + tile, y + tile)), (sx, sy))
        draw.rectangle([sx, sy, sx + tile - 1, sy + tile - 1], outline=(70, 58, 42), width=2)
        draw.text((sx, sy + tile + 5), f"{p.name} @({x},{y})", fill=(30, 25, 18), font=label_font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    return out


def build_reference_pack(run_dir: Path, label: str, samples: Sequence[Path]) -> dict[str, Path]:
    pack = run_dir / "reference_pack"
    pack.mkdir(parents=True, exist_ok=True)
    return {
        "contact": make_contact_sheet(samples, pack / f"{label}-contact.png", title=f"All {label} samples"),
        "edge": make_analysis_sheet(samples, pack / f"{label}-edge.png", mode="edge"),
        "value": make_analysis_sheet(samples, pack / f"{label}-value.png", mode="value"),
        "palette": make_palette_sheet(samples, pack / f"{label}-palette.png"),
        "technique": make_technique_sheet(samples, pack / f"{label}-technique.png"),
    }


def write_inventory(out: Path, label: str, metrics: Sequence[dict[str, object]]) -> Path:
    lines = [f"# {label} style inventory", "", aggregate_summary(metrics), "", "## Per-sample (derived)", ""]
    for m in metrics:
        lines += [
            f"### {m['file']}",
            f"- {m['width']}x{m['height']} (aspect {m['aspect']})",
            f"- edge {m['edge_density']} | dark {m['dark_mass_ratio']} | light {m['paper_light_ratio']} | sat {m['saturation_mean']}",
            f"- palette: {_hexes(m['palette'])}",  # type: ignore[arg-type]
            f"- observation: {derive_observation(m)}",
            "",
        ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
AVOID = (
    "Avoid: superficial filter or color-grade as a substitute for the real drawing method, "
    "texture-only transfer, watermarks, signatures, UI text, labels, border text, card frames, "
    "extra characters, unrelated background clutter, and any recognizable pop-culture / "
    "franchise / game characters or properties."
)


# The fidelity of a one-shot is bounded by the precision of the English that describes it: an
# image model obeys register as much as nouns. The most compressed word is also the most
# depictable, because precision and evocation converge at the level of a single mark. So every
# prose-producing vision pass (study lenses, compose, concretize, staging) is bound by this
# directive — demand museum-grade art-writing, hand it the exact lexicon of drawing/painting, and
# bind it with the one rule that keeps it honest: every elevated word must name a mark a camera
# can see, and the register must MATCH the medium actually observed (no forge-and-grunge words for
# a smooth glazed hand, no lacquer words for a coarse one).
DICTION = """\
DICTION — write at the highest register of art writing: the English of a museum catalogue and a
master draughtsman. For each mark, choose the single most EXACT and COMPRESSED word — the precise
term, never a vague phrase — because the most compressed word is also the most depictable:
precision and evocation meet at the single mark. Reach for the true lexicon of drawing and
painting WHERE IT IS LITERALLY TRUE of these samples — e.g. contour, telegraphed line-weight,
ingoing/outgoing stroke, taper, the cusp of a form; graded wash, transparent glaze, layered
glaze, scumble, the marker's streak-edge; the soft terminator where light fails into shade,
modeled turn, core shadow, reflected light; reserved highlight, specular spark, catch-light;
lost-and-found edge, sealed silhouette; luminous transparency, tempered chord, jewel-tone,
burnished sheen, breathing edge — AND their loaded, impasto, gestural, or abraded counterparts
where the medium is thick, raw, or lo-fi.
TWO HARD RULES: (1) every elevated term must still name something a camera can SEE in THESE
samples — never reach for a beautiful word that is not literally true of the marks; precision over
ornament, always; no purple filler, no art-speak abstraction. (2) MATCH THE REGISTER TO THE
MEDIUM you actually observe: lapidary, glazed, luminous vocabulary for a smooth, clean, glazed
hand; loaded, impasto, gestural vocabulary for thick paint; abraded, aliased, lo-fi vocabulary for
crude raster — NEVER apply forge-and-grunge words (batter, scuff, scumble, dry-brush, ragged,
distress) to a smooth glazed surface, nor lacquer words to a coarse one."""


# Generic subject ARCHETYPE slots (abstract, no named property) so a batch spreads across the
# KINDS of forms this body of work contains instead of all defaulting to the model's own prior.
# Each instance must be ORIGINAL and drawn from the extracted FORM VOCABULARY in style-core.txt.
# These are the "safe recombination" slots — novel INSTANCES of families the samples demonstrate.
ARCHETYPE_MODES = [
    "a single original hero / adventurer figure, full-length, in a confident dynamic pose",
    "an original creature or monster",
    "a small original group or party of figures together in one scene",
    "an original piece of gear / a prop / object study",
]

# FRONTIER / ADJACENCY probe — category-novelty, not instance-novelty. Instead of recombining a
# family the samples already show, infer the WORLD the samples imply and draw the piece this same
# body of work would plausibly contain NEXT: a subject family the references imply but never
# actually show. Higher-variance by design (it leans on technique alone to stay on-brand), so it
# is fired as exactly ONE rotating slot per batch and extrapolates only from the samples' own
# logic — the adjacency catalogue from study lens #6 grounds it. Detected by identity in
# oneshot_prompt().
FRONTIER_MODE = (
    "infer the world this body of work belongs to — its genre, tools, places, inhabitants, and "
    "routines — then draw the piece this same body of work would plausibly contain NEXT: an "
    "original subject from a family the references clearly IMPLY but never actually show (an "
    "adjacent place, an off-screen moment, or a neighbouring class of object / being / "
    "structure — not another version of something already drawn). Extrapolate ONLY from the "
    "samples' own internal logic; introduce no motif, setting, creature class, or rendering the "
    "samples don't already justify"
)


def batch_modes(attempts: int) -> list[Optional[str]]:
    """Mode for each attempt in a batch: rotate through the safe ARCHETYPE_MODES, then dedicate
    the FINAL slot to the FRONTIER_MODE adjacency probe (one per batch). A single-shot batch
    stays safe (no frontier). Returns objects by reference so oneshot_prompt() can identity-test
    the frontier slot."""
    if not ARCHETYPE_MODES:
        return [None] * max(1, attempts)
    if attempts <= 1:
        return [ARCHETYPE_MODES[0]]
    modes: list[Optional[str]] = [ARCHETYPE_MODES[i % len(ARCHETYPE_MODES)] for i in range(attempts - 1)]
    modes.append(FRONTIER_MODE)
    return modes


def mode_label(mode: Optional[str]) -> str:
    """Short tag for console output (the frontier directive is too long to print whole)."""
    if mode is FRONTIER_MODE:
        return "frontier: implied/adjacent subject"
    return mode.split(",")[0] if mode else "free subject"


# Distinct artifact types the folder actually contains. Each gets its own proof + loop.
# --------------------------------------------------------------------------- #
# Vision analysis (the "soul" — a model actually LOOKS at the reference art)
# --------------------------------------------------------------------------- #
def _run_codex_proc(cmd: Sequence[str], *, input_text: str, cwd, timeout: int):
    """A subprocess.run replacement that runs codex in its OWN process group and, on timeout,
    kills the WHOLE group (SIGKILL) — not just the immediate child. codex exec spawns
    grandchildren that inherit the stdout pipe; killing only the direct child leaves them
    holding the pipe open, so a plain subprocess.run(timeout=…) wedges in the post-kill reap
    and never actually returns. Killing the group tears down every descendant and closes the
    pipe. Raises subprocess.TimeoutExpired on timeout (after the group is dead)."""
    with subprocess.Popen(list(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, cwd=cwd,
                          start_new_session=True) as p:
        try:
            out, err = p.communicate(input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                p.kill()
            try:
                p.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                pass
            raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def run_codex_text(*, prompt_text: str, refs: Sequence[Path], effort: str) -> Optional[str]:
    """Run a read-only Codex vision/text turn and return the model's stdout text."""
    cmd = [
        "codex",
        "exec",
        "-s",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-c",
        f'model_reasoning_effort="{effort}"',
    ]
    for r in refs:
        cmd += ["-i", str(r)]
    cmd += ["-"]
    print("+ " + " ".join(shq(c) for c in cmd) + "   (vision analysis, prompt on stdin)")
    # A vision pass should return in a couple of minutes; cap it so a wedged read-only codex
    # call can't stall the whole study forever (the callers treat None as a failed pass).
    vis_timeout = int(os.environ.get("IMAGEGEN_VISION_TIMEOUT", "600"))
    try:
        proc = _run_codex_proc(cmd, input_text=prompt_text, cwd=ROOT, timeout=vis_timeout)
    except subprocess.TimeoutExpired:
        print(f"  ! codex vision analysis hung >{vis_timeout}s; killed", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(proc.stderr[-1500:], file=sys.stderr)
        print(f"  ! codex vision analysis failed ({proc.returncode})", file=sys.stderr)
        return None
    return proc.stdout


# --------------------------------------------------------------------------- #
# Per-style SOUL brief (edit-mode: deep study of ONE family — marks + soul + anti-prior)
# --------------------------------------------------------------------------- #
# Each lens is a dedicated deep vision pass that gives one dimension its full attention,
# rather than splitting attention across everything in a single generalist pass.
STUDY_LENSES = [
    ("SHAPE & TECHNIQUE CENSUS — EVERY SAMPLE",
     "Go through the attached samples ONE AT A TIME, in order, and for EACH one write a short "
     "labelled note (Sample 1, Sample 2, …) capturing its distinctive line/curve quality, form "
     "construction, and shape language — and especially what THAT sample does that the others "
     "don't. Cover ALL samples; skip none. Give the rough, loose, simple, or odd ones equal "
     "weight to the polished ones — their technique must survive into the synthesis too."),
    ("FIGURE PROPORTION & CONSTRUCTION (humanoids)",
     "Pin down EXACTLY how human/humanoid figures are proportioned and built, in precise, "
     "MEASURABLE terms (estimate by eye, but state ratios / fractions / head-counts): total "
     "height in head-lengths; head width-to-height ratio; the FACE — where the eye-line sits "
     "as a fraction of head height, eye size and spacing, brow/nose/mouth/chin placement and "
     "size, jaw and cranium shape; neck length and thickness; shoulder width in head-units; "
     "torso-to-leg ratio; arm and hand length, hand and foot size in head-units; how the body "
     "masses are simplified and the line of action; the overall stylization (elongated, compact, "
     "heroic, childlike, etc.) and any deliberate exaggerations. Note how proportions vary "
     "across samples and state the COMMON system. Be specific and numeric enough that a new "
     "figure could be constructed to the same measurements."),
    ("DRAFTSMANSHIP — HOW IT'S DRAWN",
     "Reverse-engineer the exact construction, mark by mark: how each line starts, tapers, "
     "ends, and overshoots; line-weight logic and where weight is added/lost; how FACES are "
     "built (eye/nose/mouth shapes, proportions, how expression is achieved); how hands, "
     "hair, cloth folds, armor, creatures, and props are constructed; the shape language; "
     "how forms are simplified or exaggerated; perspective and staging habits. STATE THE MARK "
     "BUDGET: count, roughly, how many distinct strokes build a face, a hand, a hair mass, a "
     "garment in these samples — a low-detail hand (few, large, blunt marks) must be recorded "
     "as exactly that, never rounded up to a more detailed or refined construction."),
    ("STAGING, FRAMING & COMPOSITION — HOW THE SUBJECT SITS IN THE FRAME",
     "Reverse-engineer how this hand COMPOSES and FRAMES a piece — staging is part of the style, "
     "not just the content. Across the samples, pin down the COMMON habits AND the spread: the "
     "CROP / shot size (extreme close bust, half-figure, full-figure with headroom, or wide with "
     "the subject small in a large field); the subject's SCALE in the frame (what fraction of the "
     "height / width it fills) and where its mass is ANCHORED (centered, off to one side, low, "
     "high, on a thirds line); the CAMERA height and angle (eye-level, low / heroic looking up, "
     "high looking down, straight-on flat vs three-quarter); HORIZON / ground-line placement and "
     "how much sky / ground / empty field sits above and below; NEGATIVE SPACE — how much "
     "emptiness, where it pools, and its shape; DEPTH staging (flat single plane vs foreground / "
     "midground / background layering, overlap, atmospheric recession, props or framing elements "
     "that ring the subject); the subject's ORIENTATION and gaze direction relative to the frame; "
     "symmetry vs asymmetry and any recurring compositional TEMPLATE the hand returns to. State it "
     "concretely enough that a NEW subject could be STAGED the same way — describe the framing "
     "SYSTEM, never a specific pictured scene, and use no external artist / genre / era labels."),
    ("MEDIUM, SURFACE & COLOR",
     "FIRST decide, from visible evidence ONLY, what the work is actually made WITH — do not "
     "assume traditional art. It may be physical media (ink, brush-pen, marker, watercolor, "
     "gouache, colored pencil, graphite, crayon) OR digital — and if digital, say which kind: "
     "smooth vector, soft digital painting, hard-brush raster sketch, pixel art, or a crude "
     "raster paint-program look (e.g. jittery mouse-drawn lines, flat bucket-fills, "
     "aliased / stair-stepped / pixel-notched edges, pure-primary color, MS-Paint-grade "
     "roughness). Cite the concrete tells you actually SEE for your verdict: paper tooth / bleed "
     "/ granulation / tide-lines (traditional) vs. anti-aliased smoothness (clean digital) vs. "
     "stair-stepped pixels / no anti-aliasing / flat hard-edged fills / blunt hard-brush strokes "
     "(crude or pixel digital). THEN describe: how marks / strokes / fills behave; how color is "
     "applied (flat fills vs graded washes vs scribble vs pixel blocks); the palette and its "
     "character (muted vs pure / RGB-primary, etc.); saturation; value / notan; whether light "
     "and shadow are modeled or ignored; edge quality; and the overall surface / finish — naming "
     "whatever is genuinely there, traditional OR digital, polished OR crude. "
     "WEIGHT BY DOMINANCE: say how many of the samples show each finish, and state the MAJORITY "
     "finish as the VERDICT — do NOT let a single textured / rough / busy outlier (or reproduction "
     "noise) override a smooth, clean majority, or vice versa; flag minority looks as clearly-"
     "secondary variants, not the rule. "
     "SEPARATE REAL SURFACE FROM REPRODUCTION NOISE: genuine paper tooth, dry-brush drag, scumble, "
     "and hand hatching that are PART OF THE DRAWING are NOT the same as faint scan / JPEG / print "
     "grain lying on top of an otherwise smooth, clean-edged, evenly-filled painting. If the fills "
     "are smooth, the gradients soft, the highlights glossy, and the contours crisp and clean, the "
     "medium is SMOOTH / CLEAN (cel, marker, gouache, soft digital paint) even when light grain is "
     "present — do NOT promote scan grain into a 'scanned traditional texture' verdict. "
     "STAY SYMMETRICAL: exactly as you must not sand a genuinely crude / lo-fi look into a refined "
     "one, you must NOT roughen a genuinely smooth / clean / softly-rendered look into a textured "
     "one — do not invent paper grain, crosshatching, dry-brush, ink-scratch, or 'traditional "
     "media' surface that the samples do not actually show. Report the finish as it is, at its true "
     "DOMINANT level."),
    ("CHARM & SOUL",
     "What makes these illustrations delightful and ALIVE: personality, attitude, humor, "
     "warmth; the gesture and energy of the drawing; the deliberate imperfection, wobble, "
     "line overshoot, lumpiness, and asymmetry; the human-hand quirks a careless copy sands "
     "off. Say specifically WHERE the charm lives and exactly how it is produced."),
    ("SUBJECT, ICONOGRAPHY & FORM-LANGUAGE — ARCHETYPES, NOT INSTANCES",
     "Catalogue, IN THE ABSTRACT, WHAT this hand draws and how it imagines form — the content "
     "DNA of the body of work, never a named property. Cover: the recurring SUBJECT FAMILIES "
     "and roughly how often each appears (e.g. lone hero figures, adventuring parties / group "
     "line-ups, monsters and creatures, gear / props / objects, maps or annotated diagram "
     "pages, mounts or beasts); the FIGURE ARCHETYPES and how they are stylized ACROSS THE "
     "RANGE (e.g. compact big-head chibi vs tall elegant romantic figures — give "
     "the spread, not one mode); the POSE, GESTURE and ENERGY the figures carry (dynamic "
     "action, heroic swagger, playful charm, stillness — say which dominate); recurring MOTIF "
     "families (helmets / horns, capes and cloth, fur trim, shields, blades and weapons, "
     "jewellery, fantastical anatomy, hand-drawn glyphs and labels); and the overall "
     "world / genre flavour depicted. State it so a NEW, ORIGINAL subject could be invented "
     "that plainly belongs to this same body of work. "
     "THEN add an ADJACENCY / FRONTIER pass: from the world, genre, motifs, inhabitants, and "
     "routines these pages actually imply, name 4-8 subject FAMILIES that this body of work "
     "clearly IMPLIES but does NOT itself show in the samples — the kinds of pieces this same "
     "body of work would plausibly contain NEXT (e.g. an adjacent place, a quieter or off-screen "
     "moment, a neighbouring class of object / being / structure — not another version of what "
     "is already drawn). For each, name in a few words which present motifs imply it, so the "
     "leap is grounded in the samples' own logic, not outside invention. Strictly abstract: do "
     "NOT name or describe any specific character, creature, scene, brand, franchise, game, or "
     "property — only the archetype / motif / frontier categories themselves."),
]


def lens_instruction(name: str, focus: str, evidence: str = "") -> str:
    return f"""\
You are a master illustrator analyzing the EXACT style of the attached reference
illustrations — treat them as ONE artist / one house style. Focus ONLY on this dimension:

{name}: {focus}

{evidence}Study every image obsessively and be EXHAUSTIVE and concrete; cite recurring habits you
actually SEE across the images, with specifics (not generic art-speak). This is one section
of a larger style manual, so go deep on this dimension only.

Describe ONLY what is literally visible in these samples. Do NOT classify the look with any
external label (no artist, studio, franchise, game, decade, era, movement, or genre names
like "90s", "RPG", "anime", "comic"). Name the marks and behaviors themselves, not a
category they resemble.

{DICTION}

Output ONLY your section between the markers, nothing else:
<<<BRIEF
{name}:
...your exhaustive, concrete analysis...
BRIEF>>>
"""


def build_manual(
    args: argparse.Namespace, label: str, samples: Sequence[Path], run_dir: Path,
    *, evidence: str = "", extra_refs: Sequence[Path] = (),
) -> str:
    """Multi-lens ensemble study: a dedicated deep vision pass per dimension (each with full
    attention), assembled into one rich style manual. `evidence` (measured native-resolution
    finish facts + technique-sheet note + any user hint) is injected into every lens so the
    study cannot 'upgrade' a crude/lo-fi hand its downscaled view can't see; `extra_refs`
    carries the native-pixel technique sheet."""
    sections: list[str] = []
    if not args.dry_run and getattr(args, "vision", True) and args.backend == "codex":
        for name, focus in STUDY_LENSES:
            print(f"[{label}] studying lens: {name} ...")
            stdout = run_codex_text(prompt_text=lens_instruction(name, focus, evidence),
                                    refs=list(samples) + list(extra_refs), effort=args.analysis_effort)
            sec = ""
            if stdout:
                found = BRIEF_RE.findall(stdout)
                if found:
                    sec = found[-1].strip()
            if sec:
                sections.append(f"## {sec}" if not sec.startswith("#") else sec)
            else:
                print(f"  ! no analysis parsed for lens {name}", file=sys.stderr)
    manual = "\n\n".join(sections)
    (run_dir / "style-brief.md").write_text(manual + "\n", encoding="utf-8")
    print(f"  style manual -> style-brief.md ({len(manual)} chars)")
    return manual


# --------------------------------------------------------------------------- #
# Distillation (long bible -> tight, image-model-obeyable style core)
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Output sizing
# --------------------------------------------------------------------------- #
def parse_size(size: Optional[str]) -> Optional[tuple[int, int]]:
    if not size or size == "auto":
        return None
    m = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", size)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _estimate_bg(img: Image.Image, frac: float = 0.06) -> tuple[int, int, int]:
    """Estimate the flat ground color from the four corner patches (median). Works for the white
    ground these styles use, and stays correct for dark-ground variants so padding is seamless."""
    w, h = img.size
    cw, ch = max(1, int(w * frac)), max(1, int(h * frac))
    strip = Image.new("RGB", (cw * 2, ch * 2))
    strip.paste(img.crop((0, 0, cw, ch)), (0, 0))
    strip.paste(img.crop((w - cw, 0, w, ch)), (cw, 0))
    strip.paste(img.crop((0, h - ch, cw, h)), (0, ch))
    strip.paste(img.crop((w - cw, h - ch, w, h)), (cw, ch))
    med = ImageStat.Stat(strip).median
    return (int(med[0]), int(med[1]), int(med[2]))


def _content_bbox(img: Image.Image, bg: tuple[int, int, int], tol: int = 18) -> Optional[tuple[int, int, int, int]]:
    """Bounding box of everything that differs from the ground color by more than `tol` — i.e. the
    subject, ignoring the empty ground and faint scan grain."""
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg)).convert("L")
    return diff.point(lambda p: 255 if p > tol else 0).getbbox()


def smart_fit_to(src: Path, dst: Path, target: tuple[int, int], *,
                 margin_frac: float = 0.045, tol: int = 18) -> None:
    """Content-aware fit: trim the empty ground to the subject's true bounding box, then scale the
    WHOLE subject to fit inside `target` with a safety margin and recompose on a ground-colored
    canvas. Because it starts from the full subject and only ever scales DOWN to fit, the head,
    feet, and weapon tips can never be clipped — unlike a scale-to-cover center-crop."""
    img = open_rgb(src)
    tw, th = target
    bg = _estimate_bg(img)
    bbox = _content_bbox(img, bg, tol)
    if bbox and (bbox[2] - bbox[0]) > 2 and (bbox[3] - bbox[1]) > 2:
        pad = round(0.012 * max(img.size))  # keep anti-aliased edges / faint wash
        l = max(0, bbox[0] - pad)
        t = max(0, bbox[1] - pad)
        r = min(img.width, bbox[2] + pad)
        b = min(img.height, bbox[3] + pad)
        content = img.crop((l, t, r, b))
    else:
        content = img  # nothing detected (blank/edge-to-edge) -> fit the whole frame
    inner_w, inner_h = tw * (1 - 2 * margin_frac), th * (1 - 2 * margin_frac)
    scale = min(inner_w / content.width, inner_h / content.height)
    nw, nh = max(1, round(content.width * scale)), max(1, round(content.height * scale))
    resized = content.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), bg)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "PNG", dpi=OUTPUT_DPI)


def cover_to(src: Path, dst: Path, target: Optional[tuple[int, int]], fit: str = "cover") -> None:
    """Copy src -> dst (PNG). If target given, resize to it by `fit`:
      cover   — scale-to-cover then center-crop (fills frame, CAN clip the subject);
      contain — scale whole image to fit, pad the remainder with the ground color (never clips);
      smart   — trim empty ground to the subject, then fit it with a margin (never clips, no bars).
    smart is the default for the pipeline: it fills the frame with the subject the way the samples
    do, and is mathematically incapable of cropping the figure."""
    if target is None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        open_rgb(src).save(dst, "PNG", dpi=OUTPUT_DPI)
        return
    if fit == "smart":
        smart_fit_to(src, dst, target)
        return
    img = open_rgb(src)
    tw, th = target
    if fit == "contain":
        bg = _estimate_bg(img)
        scale = min(tw / img.width, th / img.height)
        nw, nh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
        resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (tw, th), bg)
        canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
        dst.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(dst, "PNG", dpi=OUTPUT_DPI)
        return
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.Resampling.LANCZOS)
    left = (resized.width - tw) // 2
    top = (resized.height - th) // 2
    cropped = resized.crop((left, top, left + tw, top + th))
    dst.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dst, "PNG", dpi=OUTPUT_DPI)


# --------------------------------------------------------------------------- #
# Generation backends
# --------------------------------------------------------------------------- #
def shq(value: str) -> str:
    if value and all(ch.isalnum() or ch in "@%_+=:,./-" for ch in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def codex_instruction(prompt_text: str, refs: Sequence[Path], model: str, mode: str = "generate") -> str:
    if mode == "clone" and len(refs) >= 2:
        # CLONE: the refs split into STYLE source(s) + ONE content/pose reference (the LAST ref).
        # The worker must keep the subject/pose/composition from the content reference but render
        # it entirely in the style reference's hand.
        *style_refs, content_ref = refs
        style_lines = "\n".join(f"  - {p}" for p in style_refs)
        return f"""\
You are an image-generation worker. Use ONLY your built-in image_gen tool. Use model {model}.

Two KINDS of local files are attached as absolute paths. Their roles are DIFFERENT — do not
confuse them:

STYLE REFERENCE(S) — copy ONLY the drawing style from these (medium, line/curve quality,
mark-making, value, color, surface, finish, and figure-proportion system). Do NOT copy their
subject matter:
{style_lines}

CONTENT / POSE REFERENCE — copy ONLY the subject, pose, gesture, action, silhouette,
composition, and layout from THIS one (do NOT copy its drawing style):
  - {content_ref}

Feed ALL of them to the image_gen tool as references for ONE generation. Redraw the
CONTENT/POSE reference's subject and composition in the STYLE reference's hand, per this
specification:

{prompt_text}

Strict rules:
- Produce exactly one image with the built-in image_gen tool ({model}).
- Do NOT move, rename, copy, resize, or post-process the file. Leave it where the tool saves it.
- Do NOT write any other files.
- After the image is saved, your FINAL message must be exactly one line and nothing else:
  GENERATED=<absolute path to the PNG the image_gen tool just created>
"""
    ref_lines = "\n".join(f"  - {p}" for p in refs)
    return f"""\
You are an image-generation worker. Use ONLY your built-in image_gen tool. Use model {model}.

The following local files are attached and listed as absolute paths. They are the COMPLETE
reference set for one artist's style; study them all and feed them to the image_gen tool as
references for this single generation:
{ref_lines}

Produce exactly ONE image from this specification:

{prompt_text}

Strict rules:
- Produce exactly one image with the built-in image_gen tool ({model}).
- Do NOT move, rename, copy, resize, or post-process the file. Leave it where the tool saves it.
- Do NOT write any other files.
- After the image is saved, your FINAL message must be exactly one line and nothing else:
  GENERATED=<absolute path to the PNG the image_gen tool just created>
"""


class FatalBackendError(RuntimeError):
    """A non-retryable backend failure (out of credits, not authenticated). The batch loops catch
    this and stop cleanly instead of firing dozens of doomed calls; the user fixes billing/login
    and re-runs the SAME command to resume (finished deliverables are skipped). This is why no
    external retry/resume wrapper script is ever needed — the behavior lives in this tool."""


# Substrings that mark a codex failure as permanent (stop the batch) vs. worth one more try.
# Kept as clear phrases, not bare status numbers, so a token count or path can't false-match.
_FATAL_PATTERNS = (
    "out of credits", "add credits", "insufficient_quota", "insufficient credit",
    "not logged in", "please run codex login", "run `codex login`", "codex login",
    "unauthorized", "invalid api key", "authentication failed",
)
_TRANSIENT_PATTERNS = (
    "reconnecting", "websocket closed", "stream disconnected",
    "closed by server before response", "connection reset", "connection refused",
    "timed out", "timeout", "temporarily unavailable", "rate limit", "too many requests",
)


def _classify_codex_failure(text: str) -> str:
    """'fatal' (raise, stop the batch), 'transient' (retry with backoff), or 'other' (give up on
    this one image but keep the batch going)."""
    low = text.lower()
    if any(p in low for p in _FATAL_PATTERNS):
        return "fatal"
    if any(p in low for p in _TRANSIENT_PATTERNS):
        return "transient"
    return "other"


def _fatal_reason(text: str) -> str:
    low = text.lower()
    if "credit" in low or "quota" in low:
        return "codex workspace is out of credits — add credits, then re-run to resume."
    return "codex is not authenticated — run `codex login` (or set OPENAI_API_KEY), then re-run to resume."


def run_codex(
    *,
    prompt_text: str,
    refs: Sequence[Path],
    target_path: Path,
    target: Optional[tuple[int, int]],
    model: str,
    effort: str,
    dry_run: bool,
    mode: str = "generate",
    fit: str = "smart",
) -> bool:
    instruction = codex_instruction(prompt_text, refs, model, mode)
    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "-s",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        "-c",
        "sandbox_workspace_write.network_access=true",
        "-c",
        f'model_reasoning_effort="{effort}"',
    ]
    for r in refs:
        cmd += ["-i", str(r)]
    cmd += ["-"]

    print("+ " + " ".join(shq(c) for c in cmd) + "   (prompt on stdin)")
    if dry_run:
        print(f"  [dry-run] would generate -> {target_path}")
        return True

    # Snapshot the image-gen output set BEFORE the call so we can reliably identify the image
    # this call creates (the agent's GENERATED= line and "newest overall" are both unreliable:
    # the echoed prompt pollutes the regex, and stale images can win on mtime).
    before = _codex_images()
    start = time.time()
    # Confine the workspace-write agent to a throwaway temp dir as its cwd. The image_gen tool
    # saves into CODEX_GENERATED (~/.codex), independent of cwd, so capture still works — but any
    # stray files the agent tries to write (it has been seen writing sample-*.png back into the
    # repo despite being told not to) now land in the temp dir and are discarded, never polluting
    # the sample folders or sibling outputs.
    #
    # Resilience lives HERE, in-process, so no external wrapper/loop is ever needed: a transient
    # network drop (websocket close / reconnect) is retried with backoff; a fatal billing/auth
    # failure raises FatalBackendError so the batch stops cleanly and can be resumed by re-running.
    max_tries = 3
    # A single image call should finish in a few minutes; if codex exec ever hangs (a wedged
    # websocket that never closes), cap it so the batch self-heals instead of stalling forever.
    call_timeout = int(os.environ.get("IMAGEGEN_CALL_TIMEOUT", "600"))
    proc = None
    for attempt in range(1, max_tries + 1):
        try:
            with tempfile.TemporaryDirectory(prefix="imagegen_ws_") as ws:
                proc = _run_codex_proc(cmd, input_text=instruction, cwd=ws, timeout=call_timeout)
        except subprocess.TimeoutExpired:
            # Killed by the timeout — treat exactly like a transient backend error.
            if attempt < max_tries:
                wait = 5 * attempt
                print(f"  … codex exec hung >{call_timeout}s for {target_path.name} "
                      f"(attempt {attempt}/{max_tries}); killed, retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  ! codex exec hung >{call_timeout}s for {target_path.name}; giving up",
                  file=sys.stderr)
            return False
        if proc.returncode == 0:
            break
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        kind = _classify_codex_failure(combined)
        if kind == "fatal":
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:], file=sys.stderr)
            raise FatalBackendError(_fatal_reason(combined))
        if kind == "transient" and attempt < max_tries:
            wait = 5 * attempt
            print(f"  … transient backend error for {target_path.name} "
                  f"(attempt {attempt}/{max_tries}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:], file=sys.stderr)
        print(f"  ! codex exec failed ({proc.returncode}) for {target_path.name}", file=sys.stderr)
        return False

    # Prefer the image that NEWLY appeared during this call.
    new_imgs = _codex_images() - before
    src: Optional[Path] = max(new_imgs, key=lambda p: p.stat().st_mtime) if new_imgs else None
    # Fallbacks: a real GENERATED= path the agent emitted (ignore the echoed template), else
    # the newest image created since `start`.
    if src is None:
        for cand in reversed(GENERATED_RE.findall(proc.stdout)):
            p = Path(cand.strip().strip('"').strip("'"))
            if p.exists() and p.suffix.lower() in IMAGE_EXTS:
                src = p
                break
    if src is None:
        src = _latest_codex_image(since=start)
    if src is None or not src.exists():
        print(proc.stdout[-1500:])
        print(f"  ! could not locate generated image for {target_path.name}", file=sys.stderr)
        return False

    cover_to(src, target_path, target, fit)
    print(f"  saved -> {target_path}  (from {src.name}, fit={fit})")
    return True


def _codex_images() -> set[Path]:
    if not CODEX_GENERATED.is_dir():
        return set()
    return {p for p in CODEX_GENERATED.rglob("*")
            if p.is_file() and p.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}}


def _latest_codex_image(*, since: float) -> Optional[Path]:
    newest: Optional[Path] = None
    newest_mtime = since - 1
    for p in _codex_images():
        mtime = p.stat().st_mtime
        if mtime > newest_mtime:
            newest, newest_mtime = p, mtime
    return newest


def run_cli(
    *,
    prompt_text: str,
    refs: Sequence[Path],
    target_path: Path,
    size: str,
    model: str,
    quality: str,
    cli: Path,
    dry_run: bool,
    force: bool,
) -> bool:
    run_dir = target_path.parent / "_prompts"
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = run_dir / f"{target_path.stem}.prompt.txt"
    if not dry_run:
        prompt_file.write_text(prompt_text, encoding="utf-8")
    cmd = [
        sys.executable,
        str(cli),
        "edit",
        "--model",
        model,
        "--quality",
        quality,
        "--size",
        size,
        "--output-format",
        "png",
        "--prompt-file",
        str(prompt_file),
        "--no-augment",
        "--out",
        str(target_path),
    ]
    for r in refs:
        cmd += ["--image", str(r)]
    if force:
        cmd.append("--force")
    if dry_run:
        cmd.append("--dry-run")
    print("+ " + " ".join(shq(c) for c in cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode == 0


def generate(
    args: argparse.Namespace,
    *,
    prompt_text: str,
    refs: Sequence[Path],
    target_path: Path,
) -> bool:
    if target_path.exists() and not args.force and not args.dry_run:
        print(f"  skip (exists, use --force): {target_path}")
        return True
    if args.backend == "cli":
        cli = Path(args.cli).expanduser().resolve()
        if not cli.exists():
            raise SystemExit(f"Imagegen CLI not found: {cli}")
        return run_cli(
            prompt_text=prompt_text,
            refs=refs,
            target_path=target_path,
            size=args.size,
            model=args.model,
            quality=args.quality,
            cli=cli,
            dry_run=args.dry_run,
            force=args.force,
        )
    return run_codex(
        prompt_text=prompt_text,
        refs=refs,
        target_path=target_path,
        target=parse_size(args.target_size),
        model=args.model,
        effort=args.codex_effort,
        dry_run=args.dry_run,
        mode=getattr(args, "mode", "generate"),
        fit=getattr(args, "fit", "smart"),
    )


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def resolve_folder(target: str) -> Optional[Path]:
    """Resolve a folder arg robustly: an absolute path, a NAME under the repo root (e.g.
    'base_poses'), or a cwd-relative path — whichever exists. Returns None if none is a
    directory."""
    p = Path(target)
    if p.is_absolute():
        return p if p.is_dir() else None
    under_root = ROOT / target
    if under_root.is_dir():
        return under_root
    return p if p.is_dir() else None


def _new_run_dir(label: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / f"{label}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _next_output_index(out_dir: Path, label: str) -> int:
    """Next free index past the highest existing {label}-generated-N.png, so each source's runs
    accumulate independently in the shared generated/ folder and nothing is overwritten."""
    mx = 0
    if out_dir.is_dir():
        for p in out_dir.glob(f"{label}-generated-*.png"):
            m = re.fullmatch(rf"{re.escape(label)}-generated-(\d+)", p.stem)
            if m:
                mx = max(mx, int(m.group(1)))
    return mx + 1


def _one_shot(args: argparse.Namespace, *, prompt: str, refs: Sequence[Path],
              run_dir: Path, key: str, output: Path) -> bool:
    """Generate EXACTLY ONE image and place it at `output`. No candidates, no critic, no
    selection — the single result is for the user to evaluate. A copy + the exact prompt
    are kept in the run dir."""
    # True resume: if the final deliverable already exists, don't regenerate it (the generate()
    # skip at line ~1153 can't see this — it's handed the fresh run-dir path, not the deliverable).
    # This makes re-running the SAME command after a fatal stop a real resume, not a full redo.
    if output.exists() and not args.force and not args.dry_run:
        print(f"  skip (exists, use --force): {output.name}")
        return True
    (run_dir / f"prompt-{key}.txt").write_text(prompt, encoding="utf-8")
    if args.dry_run:
        print(f"  (dry-run) would one-shot -> {output.name}")
        return generate(args, prompt_text=prompt, refs=list(refs), target_path=output)
    cand = run_dir / f"{key}.png"  # fresh path (never skipped); applies --target-size here
    if not generate(args, prompt_text=prompt, refs=list(refs), target_path=cand):
        return False
    cover_to(cand, output, None)  # plain copy to the deliverable
    print(f"  one-shot -> {output}")
    return True


def compose_instruction(label: str, brief: str, evidence: str = "") -> str:
    """Pass 2: turn the exhaustive manual into the single most potent gpt-image-2 prompt."""
    return f"""\
You are a world-class prompt engineer for the gpt-image-2 image model AND a master
illustrator fluent in EVERY medium (traditional and digital). Attached are the reference
images for ONE artist's style ("{label}"). Below is a style manual derived from close study
of them.

{evidence}Write the SINGLE most effective image-generation prompt that will make gpt-image-2 produce
NEW forms in this artist's hand — an EXTRACTION of the style so the model can invent fresh,
ORIGINAL subjects that plausibly CONTINUE the body of work. Capture TWO things: (1) the exact
line / curve technique and draftsmanship — the WAY OF DRAWING; and (2) this hand's abstract
FORM-LANGUAGE — the subject archetypes, figure stylization, gesture / energy, and motif
families it draws — so new subjects belong to the same body of work, not just share its brush.
Never copy a specific thing that was drawn, and never reference a real-world property.

COVER THE FULL RANGE (SUPERSET). The samples span several line/curve/form/shape techniques
(see the SHAPE & TECHNIQUE CENSUS). Your prompt must fuse the WHOLE range — pulling technique
from EVERY sample, not just the dominant or prettiest ones — so the result could plausibly sit
beside ANY sample in the set. Do not collapse to one sample's look; name the variety of
mark/shape behaviors the shared hand uses.

MEDIUM, DENSITY & FINISH ARE SAMPLE-DERIVED — DO NOT ASSUME, DO NOT DEFAULT. Read the actual
medium, density, and level of refinement off the attached samples and the manual, and demand
exactly THAT. Impose NO default look — not traditional media, not watercolor, not "airy /
economical", not "polished". Match the samples at their own level: if they are sparse, demand
sparseness; if dense, demand density; if polished, demand polish; if the samples are crude or
lo-fi (e.g. jittery mouse-drawn raster lines, flat bucket-fills, aliased / stair-stepped pixel
edges, pure-primary color, MS-Paint-grade roughness), demand exactly that crudeness and
EXPLICITLY FORBID smoothing, cleaning, or "upgrading" it into refined / polished / smooth-
digital illustration — one common failure is a model quietly making a rough, crude, or digital
source look prettier and more professional than it is. THE REVERSE FAILURE IS EQUALLY COMMON
AND EQUALLY FATAL: if the samples are actually SMOOTH and CLEANLY rendered (soft cel / marker /
gouache / airbrushed fills, crisp even outlines, gradient shading, glossy highlights, clean
color zones), demand exactly THAT smoothness and EXPLICITLY FORBID adding paper grain, visible
tooth, dry-brush scumble, crosshatching, ink-scratch surface, scan / print noise, or any
"traditional-media texture" the samples do not show — do not "roughen", "age", "grunge", or
"hand-craft" a clean source into a textured one. Faint scan / JPEG grain on a smooth painting
is NOT evidence of a rough medium; do not build the look around it. WEIGHT MEDIUM & FINISH BY
SAMPLE MAJORITY: lead with the finish MOST of the samples actually share, and treat a lone
rougher-or-smoother sample as a clearly-secondary variant, never as the rule. The finish must
read as the SAME hand at the SAME refinement level as the samples — neither cleaner nor rougher,
neither airier nor busier. Capture each sample's mark-making and proportion DNA across the
whole superset; do not collapse to one sample's look.

Make the prompt:
- LONG, EXHAUSTIVE, TECHNIQUE-ONLY: aim for ~2800 words (no fewer than 2200) — spend words
  freely; more length is good WHEN it buys more specificity. Spend the whole length on HOW this
  hand makes marks — line, curve, stroke mechanics, form construction, medium handling, value,
  palette behavior, surface/edge quality, and the actual density/finish. FRONT-LOAD the few
  make-or-break traits first, then go deep and specific on everything else. Use the extra length
  to pin down what makes THIS hand singular and unmistakable — the specific combinations and
  tensions no generic description would capture (e.g. how proportion, face, costume, detail
  density, and rendering sit together) — naming exact observed marks, never padding with generic
  filler or restating the same trait. (Length is about technical thoroughness; it does NOT change
  the image's density — the depicted result must match the samples' OWN density and finish, per
  the rule above, whatever that is.)
- STYLE = TECHNIQUE + FORM-LANGUAGE. Distil BOTH: how the marks are made AND the abstract
  form-language (subject archetypes, figure stylization / proportion modes, pose / gesture /
  energy, recurring motif families) the hand works in — so new forms genuinely CONTINUE the
  body of work, not just its brush texture. Include a compact FORM VOCABULARY the model should
  invent from (the kinds of figures / creatures / props / scenes and the energy they carry).
- NO SPECIFIC SUBJECT, NO POP CULTURE. Keep the form-language ABSTRACT — archetype and motif
  CATEGORIES only. Do NOT name, describe, or imply any specific character, creature, object,
  scene, or property, and include NO pop-culture / franchise / game / brand / artist / studio /
  era / genre references whatsoever — not even obliquely. Do not lock to one fixed subject or
  composition; describe the vocabulary and let each generation invent its own original instance.
- Lead with the LINE and CURVE technique: how contours are drawn, stroke entry/exit/taper/
  overshoot, line-weight modulation, how curves and corners are constructed, hatching/
  feathering — so the model draws NEW forms with this exact hand.
- INCLUDE A PRECISE FIGURE-PROPORTION SPEC for humanoids and BE NUMERIC here (this is the one
  place exact numbers matter, because it defines the figures): total height in head-lengths;
  head shape ratio; eye-line placement as a fraction of head height; eye size/spacing;
  nose/mouth/chin/jaw placement and size; neck; shoulder width in heads; torso-to-leg ratio;
  hand/foot size in heads; and the stylization (elongated/compact/heroic/childlike + any
  exaggerations). State it exactly; do NOT soften it. The model keeps getting humanoid
  proportions wrong, so make this unmissable. LEAD with the DOMINANT, signature proportion this
  hand is actually known for — the build most of its figures share — and give that as the primary
  target; mention rarer or taller variants only as clearly-secondary notes, so an averaged middle
  is not mistaken for the signature. Pin down what makes this proportion and construction
  DISTINCTIVE and specific to THIS hand (the particular way head, body, limbs, face, and gear sit
  together); do NOT settle for a generic category label ('chibi', 'cute', 'super-deformed',
  'anime', 'cartoonish') in place of the precise observed proportions — name the exact thing, not
  the nearest cliché.
- Concrete about MEDIUM & MARKS, matched to what the samples ACTUALLY are: the real tools and
  surface; stroke / brush / fill behavior; line quality and weight; and the true surface feel —
  paper grain and scanned-from-paper feel IF traditional, or aliasing / flat hard-edged fills /
  hard-brush or pixel edges / no-anti-alias roughness IF digital. Name what is really there.
- Describe the palette and value feel in plain words (the families of color and how dark/light
  it runs) — do NOT pin exact hex codes or palette percentages here; leave color room. (This
  looseness is for COLOR only — keep figure proportions exact.)
- Translate the drawing's character into concrete marks (gesture, deliberate imperfection,
  wobble, overshoot, asymmetry).
- Include a thorough list of marks/behaviors to AVOID — specifically the ones that would betray
  THIS hand given its actual medium and finish (for a polished hand, the rough/sloppy tells; for
  a crude or lo-fi hand, the smooth/clean/"upgraded"/over-rendered tells) — and reaffirm the
  rule that the result must match the samples' own density and finish. Do not name external
  artists/styles/eras.
- Direct, imperative, no meta-talk or preamble. Do NOT specify a subject or composition.

{DICTION}

Style manual:
{brief}

Output ONLY the prompt between the markers, nothing else:
<<<PROMPT
...the optimized style/rendering prompt...
PROMPT>>>
"""


def compose_oneshot_core(
    args: argparse.Namespace, label: str, samples: Sequence[Path], brief: str, run_dir: Path,
    *, evidence: str = "", extra_refs: Sequence[Path] = (),
) -> str:
    """Pass 2: a prompt-engineering vision pass that compresses the manual into the single
    most potent, gpt-image-2-optimized style directive (front-loaded traits + hard
    anti-prior). Falls back to the raw manual if unavailable."""
    if args.dry_run or not getattr(args, "vision", True) or args.backend != "codex" or not brief:
        return brief
    print(f"[{label}] composing the optimized one-shot prompt from the manual...")
    stdout = run_codex_text(prompt_text=compose_instruction(label, brief, evidence),
                            refs=list(samples) + list(extra_refs), effort=args.analysis_effort)
    core = ""
    if stdout:
        found = PROMPT_RE.findall(stdout)
        if found:
            core = found[-1].strip()
    if not core:
        print("  ! no composed prompt parsed; falling back to the full manual.", file=sys.stderr)
        core = brief
    (run_dir / "style-core-draft.txt").write_text(core + "\n", encoding="utf-8")
    print(f"  draft core -> style-core-draft.txt ({len(core)} chars)")
    return core


def concretize_instruction(label: str, core: str, evidence: str = "") -> str:
    """Pass 3: advanced prompt-craft — rewrite the directive into maximally DEPICTABLE
    English (show-don't-tell, precise media vocabulary, front-loaded) grounded ONLY in the
    attached samples (no external style/era/genre anchoring)."""
    return f"""\
You are the world's most exacting image-prompt engineer. Attached are the reference images
for this style. Below is a strong DRAFT prompt for gpt-image-2.

{evidence}Rewrite the draft into its MAXIMALLY DEPICTABLE form — every clause must describe something
a camera could literally see in the finished image.

Rules:
- SHOW, DON'T TELL. Translate every abstract or emotional word into the concrete marks that
  CAUSE it. Words like "charm", "soul", "lively", "expressive", "energy", "whimsical" are
  NOT depictable — replace each with its exact visual cause you can verify in the attached
  art (e.g. "contour lines wobble and overshoot past corners"; "features set slightly
  off-center"; "cheeks built from two or three flat marker strokes"; "the blade keeps one hard
  reserved catch-light bounded by a cool cyan glaze"). Cut anything undrawable.
- DEPICTABLE MEANS EXACT, NOT COARSE. Show-don't-tell is a demand for PRECISION, not for
  bluntness — do NOT "concretize" a subtle mark by flattening it into a cruder one. If the
  samples model form with a long graded sheen, a soft terminator, or a luminous transparent
  glaze, say exactly THAT ("metal turns through a slow gradient from cobalt core to pale cyan
  bevel, broken by one hard specular spark") — never posterize it into "abrupt value jumps",
  "chunky islands", or "hatching" it does not contain. The most exact description of a gradient
  IS a gradient. Match the sample's true subtlety; do not trade nuance for false concreteness.
- Describe the LINE and CURVE technique precisely: how contours are drawn, where strokes
  enter/exit/taper/overshoot, line-weight modulation, corner and curve construction,
  hatching/feathering habits — so the model draws NEW forms with this exact hand.
- KEEP THE FIGURE-PROPORTION SPEC EXACT: restate the humanoid proportions numerically (height
  in head-lengths, eye-line placement fraction, eye size/spacing, feature placement, neck,
  shoulder width in heads, torso-to-leg ratio, hand/foot size in heads, stylization). This is
  what makes the humanoids match — be precise here, do NOT soften or drop it. Lead with the
  DOMINANT signature build (not an averaged middle), and describe the distinctive construction in
  precise observed terms — never substitute a generic category label ('chibi', 'cute',
  'super-deformed', 'anime') for the exact proportions.
- Use precise, accurate MEDIUM vocabulary for whatever the samples truly are — traditional
  (gouache, granulation, dry-brush scumble, marker streaking and pooling, bleed, tide-line,
  hatching) OR digital (anti-aliased vs aliased / stair-stepped / pixel-notched edges, flat
  bucket-fill, hard-brush raster strokes, jagged mouse-drawn contours, pure-primary fills, no
  anti-aliasing) — only to name what the samples literally show. Do not default to traditional
  terms when the samples are digital, or vice versa.
- Describe the palette and value feel in plain words; do NOT pin exact hex codes or palette
  percentages (the no-numbers rule applies to COLOR only — proportions stay numeric).
- KEEP THE FULL LENGTH: preserve the draft's exhaustive ~2800-word technical depth (no fewer
  than 2200 words). Refine and sharpen each clause for depictability, and you may ADD specificity
  where it sharpens the distinctive signature, but do NOT compress, summarize, or drop technique.
  Don't name external artists/styles/eras.
- PRESERVE THE BREADTH: keep the range of line/curve/form/shape techniques the draft drew from
  all the samples; don't narrow it to a single sample's look while tightening.
- PRESERVE THE SAMPLES' ACTUAL DENSITY & FINISH: keep whatever level of sparseness/density and
  polish/crudeness the draft drew from the samples. Do NOT push toward airy/economical, and do
  NOT push toward busy/over-rendered — match the samples. If the draft calls for a crude / lo-fi
  / digital look (aliased edges, flat fills, jittery raster lines), keep it sharp and explicitly
  forbid smoothing or "upgrading" it into clean polished illustration. EQUALLY, if the draft /
  samples are SMOOTH and cleanly rendered (soft cel / marker / gouache fills, crisp even outlines,
  gradient shading, glossy highlights), keep it smooth and explicitly FORBID adding paper grain,
  visible tooth, dry-brush, crosshatching, ink-scratch texture, or scan / print noise the samples
  do not show — never roughen or "grunge" a clean source. Match the samples' DOMINANT finish, not
  a rougher-or-smoother outlier.
- FRONT-LOAD the few make-or-break visual traits first.
- Imperative, concrete. No hedging, no meta-talk, no non-visual adjectives.
- KEEP TECHNIQUE + FORM-LANGUAGE, NO SPECIFIC SUBJECT: preserve BOTH the mark-making technique
  AND the abstract FORM VOCABULARY (subject archetypes, figure stylization, gesture / energy,
  motif families) from the draft, rendered depictably. Do NOT collapse to one fixed subject or
  composition, and include NO specific named character / creature / scene / property and NO
  pop-culture / franchise / game / brand / artist / era / genre references. The vocabulary
  stays abstract so each generation invents its own original instance in this hand.

{DICTION}

Draft prompt:
{core}

Output ONLY the rewritten prompt between the markers, nothing else:
<<<PROMPT
...the maximally depictable prompt...
PROMPT>>>
"""


def concretize_core(
    args: argparse.Namespace, label: str, samples: Sequence[Path], core: str, run_dir: Path,
    *, evidence: str = "", extra_refs: Sequence[Path] = (),
) -> str:
    """Pass 3: turn the draft directive into its most depictable form (the key linguistic
    lever — an image model draws concrete marks, not abstractions)."""
    if args.dry_run or not getattr(args, "vision", True) or args.backend != "codex" or not core:
        (run_dir / "style-core.txt").write_text((core or "") + "\n", encoding="utf-8")
        return core
    print(f"[{label}] concretizing the prompt (show-don't-tell, samples-only)...")
    stdout = run_codex_text(prompt_text=concretize_instruction(label, core, evidence),
                            refs=list(samples) + list(extra_refs), effort=args.analysis_effort)
    final = ""
    if stdout:
        found = PROMPT_RE.findall(stdout)
        if found:
            final = found[-1].strip()
    if not final:
        print("  ! no concretized prompt parsed; keeping the draft core.", file=sys.stderr)
        final = core
    (run_dir / "style-core.txt").write_text(final + "\n", encoding="utf-8")
    print(f"  final core -> style-core.txt ({len(final)} chars)")
    return final


def staging_instruction(label: str, brief: str, evidence: str = "") -> str:
    """Pass 2b: distill the style's STAGING / FRAMING / POSE-PRESENTATION habits into a short,
    depictable directive. The compose/concretize core is technique-only (it deliberately drops
    composition so each generation is free); this recovers staging as its OWN load-bearing
    directive — reused by step1 (stage every invented subject this way) and clone (re-frame a pose
    this way)."""
    return f"""\
You are a master illustrator and image-prompt engineer. Attached are the reference images for
ONE artist's style ("{label}"), plus a style manual derived from close study of them.

{evidence}

Distill ONLY this hand's STAGING, FRAMING, and POSE-PRESENTATION habits into a tight, maximally
DEPICTABLE directive for how this artist FRAMES and POSES a SINGLE subject in a tall 5:7
portrait — so a DIFFERENT, new subject could be composed and posed the same way. This is a
load-bearing part of the style, as important as the figure-proportion spec: how the subject sits
in the frame and how the figure is posed is itself a technique.

Cover, in concrete camera-visible terms:
- CROP / shot size (close bust, half-figure, full-figure with headroom, or figure small in a
  large field) and how much of the frame the subject fills.
- ANCHORING: where the subject's mass sits (centered, off to a side, low, high, on a thirds
  line) and the camera height / angle (eye-level, low / heroic looking up, high looking down,
  straight-on vs three-quarter).
- POSE PRESENTATION: how the figure is posed and carried — weight shift / contrapposto, the line
  of action (S-curve, diagonal, vertical), twist of shoulders vs hips, gaze direction, the
  attitude and tension the pose projects, and how the pose is angled to flatter and dramatize the
  figure rather than sit flat and frontal. Name the recurring pose habits, not one fixed pose.
- HORIZON / ground-line placement; where NEGATIVE SPACE pools and its shape; DEPTH staging (flat
  single plane vs foreground / midground / background layering, overlap, atmospheric recession,
  framing props that ring the subject).
- Any recurring compositional TEMPLATE the hand returns to.

Describe the framing and posing SYSTEM only — no specific named character, creature, scene, or
property, and no external artist / franchise / genre / era labels. Keep it 150-260 words,
imperative, concrete: every clause something a camera could literally see.

{DICTION}

Style manual:
{brief}

Output ONLY the directive between the markers, nothing else:
<<<PROMPT
...the staging / framing / pose directive...
PROMPT>>>
"""


def compose_staging(
    args: argparse.Namespace, label: str, samples: Sequence[Path], brief: str, run_dir: Path,
    *, evidence: str = "", extra_refs: Sequence[Path] = (),
) -> str:
    """Extract the compact STAGING directive (how this style frames AND poses a single subject)
    from the style manual, and save it as style-staging.txt. Returns "" when unavailable
    (dry-run / no-vision / cli backend / empty brief), in which case callers fall back to their
    default framing behavior."""
    if args.dry_run or not getattr(args, "vision", True) or args.backend != "codex" or not brief:
        return ""
    print(f"[{label}] extracting the staging / framing / pose directive...")
    stdout = run_codex_text(prompt_text=staging_instruction(label, brief, evidence),
                            refs=list(samples) + list(extra_refs), effort=args.analysis_effort)
    staging = ""
    if stdout:
        found = PROMPT_RE.findall(stdout)
        if found:
            staging = found[-1].strip()
    if not staging:
        print("  ! no staging directive parsed; falling back to default framing.", file=sys.stderr)
        return ""
    (run_dir / "style-staging.txt").write_text(staging + "\n", encoding="utf-8")
    print(f"  staging -> style-staging.txt ({len(staging)} chars)")
    return staging


def oneshot_prompt(core: str, output: Path, mode: Optional[str] = None, staging: str = "") -> str:
    """The single generation prompt: the extracted style directive (technique + abstract
    form-language). Each attempt invents its OWN original subject, drawn from this hand's form
    vocabulary and biased toward a different archetype slot for range — never copying a specific
    sample subject or any real-world property. The attached samples are the ground truth."""
    directive = core.strip() if core else (
        "Render in the EXACT medium, finish, and level of refinement the attached references "
        "show — whether traditional physical media or digital, polished or deliberately crude — "
        "matching their marks faithfully. Do NOT 'upgrade' a rough, lo-fi, or crude look into "
        "clean, smooth, polished concept-art; match the samples as they actually are."
    )
    if mode is FRONTIER_MODE:
        subject_line = (
            f"For THIS image, {FRONTIER_MODE}. Draw it in this hand's form vocabulary and "
            "technique so it plainly belongs to the same body of work — a genuine continuation, "
            "not a departure."
        )
    elif mode:
        subject_line = (
            f"For THIS image, invent {mode} — entirely original, drawn from this hand's form "
            "vocabulary so it plainly belongs to the same body of work."
        )
    else:
        subject_line = (
            "Invent your own ORIGINAL subject, drawn from this hand's form vocabulary so it "
            "plainly belongs to the same body of work."
        )
    staging_block = (
        "\nSTAGING & POSE — compose and pose your invented subject this way. This framing / pose "
        "system is load-bearing, as important as the figure proportions: do NOT default to a flat, "
        "frontal, dead-centered, generic composition. Follow it for crop, the subject's scale in "
        "the frame, anchoring, camera height/angle, the line of action and weight of the pose, "
        "gaze, horizon, negative space, and depth — while still inventing your own subject:\n"
        f"{staging.strip()}\n"
    ) if staging.strip() else ""
    return f"""\
You are a master illustrator fluent in every medium. The attached images are reference for
this hand's TECHNIQUE and FORM-LANGUAGE — study HOW the marks are made AND what KINDS of forms,
figures, and motifs this artist draws (their archetypes, stylization, gesture, and energy).
Make ONE new finished piece that CONTINUES this hand — matching its actual medium, finish, and
level of refinement (traditional or digital, polished or deliberately crude), its line and
curve quality, mark-making, value, and color, AND inventing a subject that belongs to the same
body of work. Do not make a rough or crude source look cleaner or more polished than it is.

{subject_line} Do NOT reproduce, quote, or evoke any specific character, creature, scene, or
property shown in the references, and include no pop-culture / franchise / game / brand
references of any kind.

{directive}
{staging_block}
PRESENTATION: Make it a finished, fully-resolved, confidently-composed and well-presented piece —
strong readable silhouette, a clear focal point, and a deliberate composition with NO half-finished,
garbled, or accidentally-sloppy passages. This is an execution/quality bar, NOT a style change: hold
the SAME medium, density, and finish level as the references — do not make it cleaner, smoother, or
more polished than they are, nor rougher. Compose it as a TALL 5:7 PORTRAIT (e.g. 1500x2100), filling
the frame top-to-bottom with no added borders or framing. Fit the ENTIRE subject inside the frame —
the full head and hair, both feet, and the whole weapon including its tip must sit comfortably within
the image with a clear margin of empty ground on all four sides; do NOT let any part of the figure or
its weapon touch, run off, or be clipped by any edge.

{AVOID}

Output: PNG, saved to {output}.
"""


def make_prompt(core: str, output: Path, subject: str, staging: str = "") -> str:
    """MAKE: render a NEW subject GIVEN AS TEXT (no content image) in the learned style hand.
    The three modes differ only in where the SUBJECT comes from: match INVENTS it, clone restyles
    a reference IMAGE, and make draws exactly what the TEXT asks. Everything else — medium, line,
    figure build, palette, surface, staging — comes from the style. The attached samples are
    reference for the HAND ONLY, never the subject."""
    directive = core.strip() if core else (
        "Render in the EXACT medium, finish, and level of refinement the attached references "
        "show — whether traditional physical media or digital, polished or deliberately crude — "
        "matching their marks faithfully. Do NOT 'upgrade' a rough, lo-fi, or crude look into "
        "clean, smooth, polished concept-art, nor coarsen a smooth, glazed one into something "
        "rougher; match the samples exactly as they are."
    )
    staging_block = (
        "\nSTAGING & POSE — compose and pose the subject this way. This framing / pose system is "
        "load-bearing, as important as the figure proportions: do NOT default to a flat, frontal, "
        "dead-centered, generic composition. Follow it for crop, the subject's scale in the frame, "
        "anchoring, camera height/angle, the line of action and weight of the pose, gaze, horizon, "
        "negative space, and depth — while rendering the requested subject:\n"
        f"{staging.strip()}\n"
    ) if staging.strip() else ""
    return f"""\
You are a master illustrator fluent in every medium. The attached images are reference for this
hand's TECHNIQUE and FORM-LANGUAGE ONLY — how the marks are made and what KINDS of forms, figures,
and motifs this artist draws (their archetypes, stylization, gesture, energy). They are NOT the
subject. Make ONE finished piece that depicts the REQUESTED SUBJECT below, drawn entirely in this
hand — matching its actual medium, finish, and level of refinement (traditional or digital,
polished or deliberately crude), its line and curve quality, mark-making, value, color, AND its
figure build / proportions, so the result looks like the STYLE artist drew this subject from
scratch. Do not make a rough or crude source look cleaner or more polished than it is, nor coarsen
a smooth, glazed one.

REQUESTED SUBJECT — draw exactly this: "{subject}".
Interpret it THROUGH this hand's form vocabulary — its archetypes, costume, anatomy, motif
families, proportion, and energy — rather than a generic or photographic depiction: design the
specific character / creature / object yourself so it plainly belongs to this body of work. Do NOT
reproduce, quote, or evoke any specific existing character, creature, scene, or property, and
include no pop-culture / franchise / game / brand references of any kind.

{directive}
{staging_block}
PRESENTATION: Make it a finished, fully-resolved, confidently-composed and well-presented piece —
strong readable silhouette, a clear focal point, and a deliberate composition with NO half-finished,
garbled, or accidentally-sloppy passages. This is an execution/quality bar, NOT a style change: hold
the SAME medium, density, and finish level as the references — do not make it cleaner, smoother, or
more polished than they are, nor rougher. Compose it as a TALL 5:7 PORTRAIT (e.g. 1500x2100), filling
the frame top-to-bottom with no added borders or framing. Fit the ENTIRE subject inside the frame —
the full head and hair, both feet, and the whole weapon including its tip must sit comfortably within
the image with a clear margin of empty ground on all four sides; do NOT let any part of the figure or
its weapon touch, run off, or be clipped by any edge.

{AVOID}

Output: PNG, saved to {output}.
"""


def clone_prompt(core: str, output: Path, content_ref: Path,
                 framing: str = "balance", staging: str = "") -> str:
    """The 1-to-1 STYLE-CLONE generation prompt: redraw the content/pose reference's subject in
    the extracted style hand (the directive). The `framing` dial sets how much of the COMPOSITION
    comes from the content file vs. the style — because how a subject is framed and posed is part
    of the style, not just the content:
      keep    — lock crop / camera / silhouette / layout to the content file (strict 1-to-1 restyle).
      balance — keep the subject + pose + action, but RE-STAGE the framing into the style's habits.
      style   — keep only the subject's identity + action; RE-STAGE the pose AND the framing.
    `staging` is the style's depictable framing/pose directive, injected for balance and style."""
    directive = core.strip() if core else (
        "Render in the EXACT medium, finish, and level of refinement the STYLE references show — "
        "whether traditional physical media or digital, polished or deliberately crude — matching "
        "their marks faithfully. Do NOT 'upgrade' a rough, lo-fi, or crude look into clean, "
        "smooth, polished illustration; match the style references as they actually are."
    )

    if framing == "keep":
        keep_block = (
            f"KEEP FROM THE CONTENT/POSE REFERENCE ({content_ref.name}) — do not change these: the "
            "subject and what it is; the pose, gesture, and action; the number of figures/objects "
            "and their arrangement; the camera framing and perspective, the overall composition and "
            "layout, and how much of the frame the subject fills. If it shows one figure standing a "
            "certain way, your figure stands that same way; if it shows a specific object or "
            "grouping, draw that same object or grouping. Do NOT invent a different subject, add or "
            "remove figures, or restage the scene. (The figure's BODY PROPORTIONS are NOT taken from "
            "here — those are rebuilt to the style's build; see FIGURE BUILD below.)"
        )
        present_tail = "— preserve the content reference's pose and composition while doing so."
    elif framing == "style":
        keep_block = (
            f"KEEP FROM THE CONTENT/POSE REFERENCE ({content_ref.name}) only the SUBJECT'S IDENTITY "
            "and its core action / mood: what the subject is and roughly what it is doing. Keep the "
            "same number of figures. Do NOT swap it for a different subject.\n\n"
            "RE-STAGE AND RE-POSE INTO THE STYLE'S COMPOSITION — do NOT copy the content "
            "reference's crop, camera, scale, placement, or pose angle. Following the STYLE STAGING "
            "directive below, set the shot size, the subject's scale in the frame, its anchoring, "
            "the camera height / angle, the line of action and weight of the pose, gaze, horizon, "
            "negative space, and depth the way the style artist would compose and pose this subject "
            "from scratch. You may re-pose and re-angle the figure to fit that staging, keeping its "
            "identity and action."
        )
        present_tail = ("— staging and posing the subject as the STYLE STAGING directive specifies, "
                        "not as the content file is framed.")
    else:  # balance (default)
        keep_block = (
            f"KEEP FROM THE CONTENT/POSE REFERENCE ({content_ref.name}): the subject and what it is; "
            "the pose, gesture, and action; the number of figures/objects. Your figure holds the "
            "same pose and does the same thing — do NOT invent a different subject, add or remove "
            "figures, or change what is happening.\n\n"
            "RE-STAGE THE FRAMING INTO THE STYLE'S COMPOSITION — do NOT simply copy the content "
            "reference's crop and placement. Following the STYLE STAGING directive below, set the "
            "shot size, how much of the frame the subject fills, where its mass is anchored, the "
            "camera height / angle, the horizon, the negative space, and the depth layering the way "
            "this style stages a single subject — so the SAME subject and pose are composed in the "
            "style's hand. Keep the subject's identity, pose, and action intact while you re-frame."
        )
        present_tail = ("— holding the content reference's subject and pose, but staging the frame "
                        "per the STYLE STAGING directive.")

    staging_block = ""
    if framing != "keep" and staging.strip():
        staging_block = (
            "\nSTYLE STAGING (how this hand frames and poses a single subject — follow it for "
            f"composition):\n{staging.strip()}\n"
        )

    # Figure proportion / build is the load-bearing, identity-defining part of a STYLE, not a
    # content property: cloning the EXACT style means adopting the precise build the style study
    # characterized (whatever it is), EVEN WHEN the content/pose reference shows a differently
    # proportioned figure. The model tends to anchor on the content figure's naturalistic
    # proportions, so push HARD to adopt the style's build in full — but defer the SPECIFICS to the
    # study-derived directive rather than injecting generic category labels here. The directive's
    # sophisticated, sample-measured description is what makes it the EXACT style; a generic
    # 'chibi' / 'cute' shorthand would flatten that distinct identity. Scale-in-frame (how much of
    # the page the figure fills) is the one proportion that stays content's — do NOT miniaturize the
    # subject into a tiny corner just because the style source packs many small figures on a page.
    build_block = (
        "FIGURE BUILD & PROPORTION — TAKE THIS FROM THE STYLE, NOT THE CONTENT. The figure's "
        "proportions and construction are a defining, distinctive part of this hand, so REBUILD "
        "the content figure's body to the EXACT build the STYLE directive above specifies — its "
        "head-to-body ratio, head size and shape, neck / torso / limb lengths and thickness, hand "
        "and foot size, and facial construction — reproducing that build precisely and IN FULL, "
        "exactly as the directive describes it and as the style references show. This holds EVEN "
        "IF the content/pose reference shows a taller, more naturalistic, or differently "
        "proportioned figure: do NOT keep the content figure's proportions and do NOT average the "
        "two. The persistent failure here is drifting back toward the content's naturalistic "
        "anatomy — a taller body, smaller head, longer limbs, a more detailed face — because the "
        "pose reference pulls you there; resist it. Build to the style's TYPICAL, most "
        "characteristic figures (not the tallest or least-stylized ones the references may also "
        "contain), and commit fully rather than splitting the difference. Reproduce the style's "
        "actual rendering character and level of detail too — its line, media, color, and surface "
        "as the directive specifies — do NOT simplify the figure into a flatter, cuter, or more "
        "generic cartoon than the references are. From the content reference take ONLY the pose, "
        "gesture, action, which objects / props are present, the composition and layout, the "
        "camera and perspective, and HOW MUCH OF THE FRAME the figure fills — the re-proportioned "
        "figure holds that same pose, from that same viewpoint, and fills the frame the same way, "
        "just rebuilt in the style's own proportions. Do NOT shrink the figure into a tiny part of "
        "the page: keep the content's scale-in-frame.\n"
    )

    # THE most-failed part of a clone when the content is a PHOTO (or any detailed portrait) of a
    # specific person: the model preserves the real face's likeness — modeled cheeks, a rendered
    # smile with teeth, photographic eyes, skin/stubble shading — instead of rebuilding the face to
    # the style's own face CONSTRUCTION. "Keep the subject's identity" (above) fights the face
    # rebuild and, for a style whose faces are minimal non-portrait signs, likeness wins unless we
    # force the split explicitly. So: faces are rebuilt to the style's face grammar; only a few
    # identity CUES survive, and only as the style's own flat marks. Style wins over likeness.
    face_block = (
        "FACE — REBUILD TO THE STYLE'S FACE; DO NOT PRESERVE THE PHOTOGRAPHIC LIKENESS. This is the "
        "single most important and most-failed part of this transfer. Draw every face using the "
        "style's OWN face construction exactly as the directive above specifies it (its eye shape "
        "and size, how open/closed and how far down the head the eyes sit, the nose mark, the mouth "
        "mark, brow marks, and — critically — its low FACIAL MARK-COUNT: the whole face is built "
        "from only a handful of simple flat marks). Do NOT render the content person's actual "
        "features as a detailed portrait: NO realistically modeled cheeks/jaw/brow, NO rendered "
        "smile with teeth, NO photographic or large expressive eyes, NO eyelashes/iris/lip "
        "modeling, NO skin shading or blush, NO stubble or beard drawn as real hair texture, NO "
        "likeness rendering. Skin is a flat fill inside the face outline. Keep ONLY a few "
        "identity-level CUES — e.g. glasses, a beard vs. clean-shaven, hair color/length, a hat — "
        "and draw EACH as the style's own minimal flat sign (a beard is a flat shape, not rendered "
        "hair; glasses are two simple marks), never as a rendered likeness. The face must read "
        "FIRST as one of the style's own faces and only incidentally resemble the specific person. "
        "If the person looking recognizable conflicts with the face matching the style's minimal "
        "construction, the STYLE WINS — sacrifice the likeness.\n"
    )

    # The single biggest leak in a clone: the model partly reproduces the CONTENT file's OWN art
    # style (its line cleanliness, flatness, palette, finish) instead of treating it as pure layout.
    # When the content's hand is crisp/flat/graphic and the style is painterly/dense, the output
    # comes out a cleaned-up halfway thing. Force a hard split: geometry from content, every actual
    # mark/surface/color rendered 100% in the style's medium at its FULL richness.
    render_block = (
        "RENDERING & FINISH — ALL FROM THE STYLE, NONE FROM THE CONTENT. Use the content/pose "
        "reference ONLY as a layout guide for geometry: the subject, pose, composition, placement, "
        "viewpoint, and which props appear. Do NOT reproduce the content reference's OWN art style "
        "in any way — ignore its line cleanliness, evenness, flatness, crisp/graphic/vector "
        "quality, color treatment, and level of finish entirely. Render EVERY contour, fill, "
        "surface, fold, texture, and color from scratch in the STYLE references' medium and hand: "
        "its painterly washes, layered and granulated pigment, hand-drawn ink linework with the "
        "style's own weight and wobble, scumbled colored-pencil and marker texture, dense localized "
        "detail on hair, fur, cloth, armor, and props, and its saturated-yet-paper-softened "
        "palette. Match the style references at their RICHEST and most fully-rendered — do NOT "
        "leave the image cleaner, flatter, more graphic, more evenly-lined, or more sparsely "
        "colored than the style references are. If the content reference looks crisp, flat, and "
        "graphic while the style is painterly and dense, the result MUST come out painterly and "
        "dense: the content's crispness, flatness, and clean line must NOT survive the transfer. "
        "Only the geometry crosses over; the entire surface is repainted in the style's hand.\n"
    )

    return f"""\
You are a master illustrator fluent in every medium. You are given STYLE reference(s) and ONE
CONTENT/POSE reference (the file named {content_ref.name}). Your job is a STYLE TRANSFER, not an
invention: reproduce the CONTENT reference's subject in the STYLE reference's hand.

{keep_block}

TAKE FROM THE STYLE REFERENCE(S) — apply all of these: the medium and surface, the line and curve
quality, mark-making, value/shading, color palette and how color is applied, edge quality, the
finish/level of refinement, AND the figure-proportion / build system — i.e. both HOW every mark is
made AND how the body is proportioned. Re-draw every contour, fill, and mark as the style hand
would make it, and rebuild the figure to the style's own proportions — so the result looks like
the style artist drew this subject from scratch. Hold the SAME medium, density, and finish as the
style references — do not make it cleaner, smoother, or more polished than they are, nor rougher.
See FIGURE BUILD below.
{staging_block}
{directive}

{build_block}
{face_block}
{render_block}
PRESENTATION: Make it a finished, fully-resolved piece with a clear, readable rendering of the
content reference's subject — no half-finished, garbled, or accidentally-sloppy passages (beyond
whatever deliberate roughness the style itself has). Compose it as a TALL 5:7 PORTRAIT (e.g.
1500x2100), filling the frame top-to-bottom with no added borders or framing, keeping the subject
and key detail clear of the outer edges so nothing important is lost when cropped to that aspect
{present_tail}

{AVOID}

Output: PNG, saved to {output}.
"""


def folder_images(folder: Path) -> list[Path]:
    """Every image file in a folder (natural-sorted), excluding our own generated outputs. Unlike
    sample_images() this takes ALL images, whatever they are named — the clone target folder holds
    arbitrary content/pose files, not just sample-* files."""
    if not folder.is_dir():
        return []
    found = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        and not p.stem.endswith("-clone-generated") and "-clone-generated-" not in p.stem
        and "-generated-" not in p.stem and p.name != SUPERSET_NAME
    ]
    return sorted(found, key=natural_key)


def resolve_style_refs(style_arg: str) -> list[Path]:
    """Resolve the --style source to one or more reference image paths. Accepts a single image
    FILE (the usual case, e.g. base_illustration/sample-1.png) or a FOLDER (then use its sample-*
    images if present, else every image in it)."""
    raw = Path(style_arg)
    candidates = [raw] if raw.is_absolute() else [ROOT / style_arg, raw]
    p = next((c for c in candidates if c.exists()), candidates[0])
    if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
        return [p]
    if p.is_dir():
        samples = sample_images(p)
        return samples if samples else folder_images(p)
    return []


def learn_style(
    args: argparse.Namespace,
    label: str,
    samples: Sequence[Path],
    run_dir: Path,
    *,
    want_staging: bool = True,
) -> tuple[str, str]:
    """Learn ONE style — the single shared pipeline behind match, make, and clone, so all three
    read a style identically. Writes the human references (objective metrics, measured fingerprint,
    reference pack) and runs the 3-stage vision build (7-lens manual -> compose -> concretize) into
    style-core.txt, plus the style's framing/pose directive (style-staging.txt). Returns
    (core, staging); staging is "" when want_staging is False or the directive is unavailable."""
    metrics = [image_metrics(p) for p in samples]
    write_inventory(run_dir / "style-inventory.md", label, metrics)
    pack = build_reference_pack(run_dir, label, samples)
    fingerprint = style_fingerprint(samples, metrics)
    (run_dir / "style-fingerprint.txt").write_text(fingerprint + "\n", encoding="utf-8")

    # Anti-"upgrade" evidence, injected into EVERY study pass. The model's image ingestion
    # downscales the attached samples, which smooths a crude / lo-fi / mouse-drawn hand into
    # what looks like clean anti-aliased illustration — so the study must be grounded in (a)
    # finish facts measured at native pixels and (b) a native-pixel technique-crop sheet it
    # can actually see the true marks in, plus (c) any user-asserted technique facts.
    hint = (getattr(args, "style_hint", "") or "").strip()
    tech_sheet = pack.get("technique")
    evidence = (
        "MEASURED GROUND TRUTH — computed from the sample FILES at NATIVE pixel resolution. "
        "Your view of the attached images is DOWNSCALED, which smooths and refines the true "
        "finish; wherever your visual impression of finish, line quality, or detail level "
        "disagrees with these measurements or with the technique sheet, TRUST THE MEASUREMENTS "
        "AND THE TECHNIQUE SHEET over your impression:\n"
        f"{fingerprint}\n"
        "The FINAL attached image is a TECHNIQUE SHEET of native-pixel 1:1 crops taken from the "
        "samples (it is an evidence aid, NOT a sample — never treat its crops as compositions). "
        "Read the true stroke edges, line wobble, mark size and bluntness, real detail level, "
        "and fill character from it.\n"
        + (f"USER-CONFIRMED FACTS about this style's medium and technique (authoritative — they "
           f"override any conflicting inference): {hint}\n" if hint else "")
        + "\n"
    )
    extra_refs = [tech_sheet] if tech_sheet else []
    manual = build_manual(args, label, samples, run_dir, evidence=evidence, extra_refs=extra_refs)
    draft = compose_oneshot_core(args, label, samples, manual, run_dir,
                                 evidence=evidence, extra_refs=extra_refs)
    core = concretize_core(args, label, samples, draft, run_dir,
                           evidence=evidence, extra_refs=extra_refs)
    staging = compose_staging(args, label, samples, manual, run_dir,
                              evidence=evidence, extra_refs=extra_refs) if want_staging else ""
    return core, staging


def _clone(args: argparse.Namespace, style_refs: Sequence[Path], folder: Path, label: str) -> list[dict]:
    poses = folder_images(folder)
    if not poses:
        print(f"  ! no image files in {folder}; nothing to clone.")
        return []
    run_dir = _new_run_dir(f"{label}-clone")
    out_dir = output_dir_for(folder)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Learn the STYLE source ONCE with the shared pipeline (multi-lens manual -> compose ->
    # concretize -> staging), then reuse that one style-core for every pose. The framing dial sets
    # how much COMPOSITION comes from the style vs the pose file: for balance/style we extract the
    # style's framing/pose system and re-stage each pose by it; keep skips it.
    print(f"[{label}] cloning {len(poses)} file(s) from {folder.name}/ in the style of "
          f"{', '.join(s.name for s in style_refs)} -> {out_dir.name}/")
    framing = getattr(args, "framing", "balance")
    core, staging = learn_style(args, f"{label}-style", style_refs, run_dir, want_staging=(framing != "keep"))
    print(f"  framing mode: {framing}" + ("" if framing == "keep" else " (re-staging poses into the style's composition)"))

    # 1-to-1: output index == pose index in natural order. Each pose -> exactly one clone, always
    # regenerated fresh (the run dir holds the working copy), overwriting the deliverable.
    results = []
    for i, pose in enumerate(poses, start=1):
        output = out_dir / f"{label}-clone-generated-{i}.png"
        prompt = clone_prompt(core, output, pose, framing, staging)
        refs = list(style_refs) + [pose]  # style first, content/pose LAST (codex_instruction splits on this)
        print(f"  clone {i}/{len(poses)}: {pose.name} -> {output.name}")
        try:
            ok = _one_shot(args, prompt=prompt, refs=refs, run_dir=run_dir,
                           key=f"{label}-clone-generated-{i}", output=output)
        except FatalBackendError as e:
            done = sum(1 for r in results if r.get("output"))
            print(f"\n  ✖ STOPPING — {e}")
            print(f"    {done}/{len(poses)} done, {len(poses) - i + 1} remaining. "
                  f"Re-run the SAME command to resume (finished outputs are skipped).")
            break
        results.append({"index": i, "source": pose.name, "output": str(output) if ok else None})
    summary = {
        "style_refs": [s.name for s in style_refs],
        "target_folder": folder.name,
        "framing": framing,
        "clones": results,
    }
    (run_dir / "selection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return results


def _superset(args: argparse.Namespace, folder: Path, label: str) -> list[dict]:
    samples = sample_images(folder)
    if not samples:
        print(f"  ! no sample-* files in {folder}; skipping {label}.")
        return []
    run_dir = _new_run_dir(label)
    out_dir = output_dir_for(folder)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # Learn the style with the shared pipeline: (1) multi-lens manual; (2) compose a potent
    # directive; (3) concretize into depictable English; (4) the framing/pose directive (the
    # technique-only core drops composition, so staging is recovered separately and stages every
    # invented subject — load-bearing, not random). No subject, no rigid numbers, no anti-external
    # wall — the attached samples carry color/value and the model invents its own subject in this
    # hand. (The measured fingerprint is a human reference only, not fed to the model.)
    attempts = max(1, getattr(args, "attempts", 5))
    print(f"[{label}] {attempts} fresh one-shot attempt(s) from ALL {len(samples)} samples -> {out_dir.name}/")
    core, staging = learn_style(args, label, samples, run_dir)

    # Accumulate, never overwrite: number new outputs past the highest existing
    # {label}-generated-N.png so every run's images stay visible in the shared generated/ folder.
    start = _next_output_index(out_dir, label)
    modes = batch_modes(attempts)
    results = []
    for i in range(attempts):
        n = start + i
        output = out_dir / f"{label}-generated-{n}.png"
        mode = modes[i]
        prompt = oneshot_prompt(core, output, mode, staging)
        print(f"  attempt {i + 1}/{attempts} -> {output.name}  [{mode_label(mode)}]")
        try:
            ok = _one_shot(args, prompt=prompt, refs=samples, run_dir=run_dir, key=f"{label}-generated-{n}", output=output)
        except FatalBackendError as e:
            done = sum(1 for r in results if r.get("output"))
            print(f"\n  ✖ STOPPING — {e}")
            print(f"    {done}/{attempts} attempts done. Re-run to generate the rest.")
            break
        results.append({"attempt": i + 1, "output": str(output) if ok else None})
    summary = {"attempts": results, "samples_used": [s.name for s in samples]}
    (run_dir / "selection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return results


def _make(args: argparse.Namespace, folder: Path, label: str, subject: str) -> list[dict]:
    """Learn the style from a samples folder (the shared pipeline), then render the TEXT-GIVEN
    subject in that hand N times. Like _superset, but the subject is specified instead of invented
    (and there is no archetype rotation or frontier probe — every attempt draws the same subject,
    so the variation across attempts is the model's own, for the human to pick from)."""
    samples = sample_images(folder) or folder_images(folder)
    if not samples:
        print(f"  ! no images in {folder}; nothing to learn the style from.")
        return []
    run_dir = _new_run_dir(f"{label}-make")
    out_dir = output_dir_for(folder)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    attempts = max(1, getattr(args, "attempts", 4))
    print(f"[{label}] making {attempts} one-shot(s) of \"{subject}\" in the style of ALL "
          f"{len(samples)} samples -> {out_dir.name}/")
    core, staging = learn_style(args, label, samples, run_dir)

    # Accumulate, never overwrite: number past the highest existing {label}-make-generated-N.png,
    # kept separate from match's {label}-generated-N.png and clone's {label}-clone-generated-N.png.
    start = _next_output_index(out_dir, f"{label}-make")
    results = []
    for i in range(attempts):
        n = start + i
        output = out_dir / f"{label}-make-generated-{n}.png"
        prompt = make_prompt(core, output, subject, staging)
        print(f"  attempt {i + 1}/{attempts} -> {output.name}  [{subject}]")
        try:
            ok = _one_shot(args, prompt=prompt, refs=samples, run_dir=run_dir,
                           key=f"{label}-make-generated-{n}", output=output)
        except FatalBackendError as e:
            done = sum(1 for r in results if r.get("output"))
            print(f"\n  ✖ STOPPING — {e}")
            print(f"    {done}/{attempts} attempts done. Re-run to generate the rest.")
            break
        results.append({"attempt": i + 1, "output": str(output) if ok else None})
    summary = {"subject": subject, "attempts": results, "samples_used": [s.name for s in samples]}
    (run_dir / "selection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return results


def step1(args: argparse.Namespace) -> int:
    # No cleanup: generated files are never used as inputs, and same-named outputs overwrite.
    target = getattr(args, "target", None) or "base_illustration"
    folder = resolve_folder(target)
    if folder is None:
        print(f"error: target folder not found: {target}")
        return 1
    results = _superset(args, folder, folder.name)
    print("\n=== SUMMARY (fresh one-shots — for you to evaluate) ===")
    for r in results:
        print(f"  attempt {r['attempt']}: {r.get('output')}")
    print(f"backend: {args.backend} | model: {args.model}")
    return 0


def clone(args: argparse.Namespace) -> int:
    """STYLE CLONE: learn ONE style (from --style) with the existing inference, then redraw EVERY
    file in --target in that style, 1-to-1, as generated/<target>-clone-generated-<n>.png."""
    args.mode = "clone"  # threads through generate() -> run_codex() -> codex_instruction()
    target = getattr(args, "target", None) or "base_poses"
    folder = resolve_folder(target)
    if folder is None:
        print(f"error: target folder not found: {target}")
        return 1
    style_refs = resolve_style_refs(args.style)
    if not style_refs:
        print(f"error: style reference not found / not an image: {args.style}")
        return 1
    results = _clone(args, style_refs, folder, folder.name)
    print("\n=== SUMMARY (1-to-1 style clones) ===")
    print(f"  style: {', '.join(s.name for s in style_refs)}")
    for r in results:
        print(f"  {r['index']}: {r['source']} -> {r.get('output')}")
    print(f"backend: {args.backend} | model: {args.model}")
    return 0


def make(args: argparse.Namespace) -> int:
    """MAKE: learn a style (from --style, the same inference match/clone use), then render a
    NEW, TEXT-SPECIFIED subject (--prompt, e.g. 'an archer') in that hand — N independent
    one-shots, as generated/<style>-make-generated-<n>.png. No content image; the subject is
    invented from the words, the look from the samples."""
    args.mode = "generate"  # only style refs are attached (no content/pose ref) -> generate path
    target = getattr(args, "style", None) or "base_illustration"
    folder = resolve_folder(target)
    if folder is None:
        print(f"error: style folder not found: {target}")
        return 1
    subject = (getattr(args, "prompt", None) or "").strip()
    if not subject:
        print("error: --prompt is required — the subject to draw, e.g. --prompt 'an archer'.")
        return 1
    results = _make(args, folder, folder.name, subject)
    print("\n=== SUMMARY (made in style — fresh one-shots for you to evaluate) ===")
    print(f"  subject: {subject}")
    for r in results:
        print(f"  attempt {r['attempt']}: {r.get('output')}")
    print(f"backend: {args.backend} | model: {args.model}")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_backend_flags(p: argparse.ArgumentParser) -> None:
    """Flags shared by every subcommand (backend, sizing, efforts, vision, force, dry-run)."""
    p.add_argument("--backend", choices=["codex", "cli"], default="codex",
                   help="codex = live Codex built-in image_gen (gpt-image-2, no API key). cli = bundled image_gen.py (needs OPENAI_API_KEY).")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--quality", default=DEFAULT_QUALITY, choices=["low", "medium", "high", "auto"])
    p.add_argument("--size", default=DEFAULT_SIZE, help="cli-backend gpt-image-2 size.")
    p.add_argument("--target-size", default=DEFAULT_TARGET_SIZE,
                   help=f"codex-backend: fit every output to WxH at 300 DPI "
                        f"(default {DEFAULT_TARGET_SIZE} = 5:7 portrait, 5\"x7\"). Pass 'auto' to keep native.")
    p.add_argument("--fit", choices=["smart", "contain", "cover"], default="smart",
                   help="how to fit the generated image to --target-size. smart (default): trim the "
                        "empty ground to the subject then scale it to fit with a margin — never clips "
                        "the figure. contain: pad whole image to fit. cover: scale-to-cover + center-"
                        "crop (fills frame but CAN clip head/feet).")
    p.add_argument("--cli", default=str(DEFAULT_IMAGEGEN_CLI))
    p.add_argument("--codex-effort", default="low", choices=["minimal", "low", "medium", "high"],
                   help="codex-backend agent reasoning effort (lower = faster; the image_gen tool quality is unaffected).")
    p.add_argument("--analysis-effort", default="high", choices=["minimal", "low", "medium", "high"],
                   help="reasoning effort for the vision style-analysis pass (deeper = richer style bible).")
    p.add_argument("--no-vision", dest="vision", action="store_false",
                   help="skip the Codex vision study (style manual); send only the attached samples + a generic prompt.")
    p.add_argument("--style-hint", dest="style_hint", default="",
                   help="authoritative user note about the style's TRUE medium/technique (e.g. "
                        "'mouse-drawn MS-Paint-like raster, low detail, flat bucket fills') — "
                        "injected into every style-study pass as ground truth that overrides "
                        "any conflicting inference from the (downscaled) sample views.")
    p.set_defaults(vision=True)
    p.add_argument("--force", action="store_true", help="overwrite existing outputs.")
    p.add_argument("--dry-run", action="store_true", help="plan only, no generation.")


def add_common(p: argparse.ArgumentParser) -> None:
    """step1 flags: shared backend flags + the one-shot batch knobs."""
    add_backend_flags(p)
    p.add_argument("--attempts", type=int, default=5,
                   help="number of fresh INDEPENDENT one-shots to fire from the same optimized "
                        "prompt (each is a pure one-shot; you pick the best). The final slot of "
                        "every batch is the FRONTIER adjacency probe; the rest rotate through the "
                        "safe archetype families. Default 5 (4 safe + 1 frontier).")
    # PURE ONE-SHOT TECHNIQUE: (1) study ALL samples -> exhaustive style manual; (2) compress
    # it into the single most potent gpt-image-2 directive (front-loaded traits + anti-prior);
    # (3) fire N independent one-shots with every sample attached. No candidates scored, no
    # critic, no refinement, no auto-select — the outputs are the user's to evaluate.
    p.add_argument("--style", "--target", dest="target", default="base_illustration",
                   help="style SOURCE — the samples folder to learn the hand from (name under "
                        "the repo root or an absolute path). --style and --target are synonyms here. "
                        "Default base_illustration; outputs go to generated/<style>-generated-<n>.png.")


def add_clone_args(p: argparse.ArgumentParser) -> None:
    """clone flags: shared backend flags + the style source and the target folder to restyle."""
    add_backend_flags(p)
    p.add_argument("--style", default="base_illustration/sample-1.png",
                   help="style SOURCE — an image file (e.g. base_illustration/sample-1.png) or a "
                        "folder (uses its sample-* images, else all images). The exact style is "
                        "pulled from this with the same inference step1 uses.")
    p.add_argument("--target", default="base_poses",
                   help="folder whose EVERY image is redrawn in the style, 1-to-1 (name under "
                        "the repo root or an absolute path). Default base_poses; outputs go to "
                        "generated/<target>-clone-generated-<n>.png.")
    p.add_argument("--framing", choices=["keep", "balance", "style"], default="balance",
                   help="how much COMPOSITION comes from the style vs the pose file (framing/pose "
                        "is part of the style). keep = lock crop/camera/silhouette/layout to the "
                        "pose (strict 1-to-1 restyle); balance (default) = keep the subject + pose "
                        "but re-stage the framing into the style's habits; style = keep only the "
                        "subject's identity + action and fully re-stage the pose AND framing in the "
                        "style's composition.")


def add_make_args(p: argparse.ArgumentParser) -> None:
    """make flags: shared backend flags + the style source, the text subject, and the batch size."""
    add_backend_flags(p)
    p.add_argument("--style", "--target", dest="style", default="base_illustration",
                   help="style SOURCE — the samples folder to learn the hand from (uses its "
                        "sample-* images, else every image; name under the repo root or an absolute "
                        "path). Default base_illustration; outputs go to "
                        "generated/<style>-make-generated-<n>.png.")
    p.add_argument("--prompt", "--subject", dest="prompt", required=True,
                   help="the NEW subject to draw, in words, e.g. --prompt 'an archer'. It is "
                        "rendered in the learned style; there is no visual reference for the "
                        "subject itself — only the words.")
    p.add_argument("--attempts", type=int, default=4,
                   help="number of fresh INDEPENDENT one-shots of the SAME subject (each a pure "
                        "one-shot; you pick the best). Default 4.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dynamic style tools (gpt-image-2). Three modes, one learned hand: "
                    "match = prove a folder's superset style with invented subjects; "
                    "make = draw a NEW text-given subject in that style; "
                    "clone = redraw existing images in that style, 1-to-1."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    # match (formerly step1): learn a folder's superset style, prove it with N invented one-shots.
    mt = sub.add_parser("match", aliases=["step1"],
                        help="learn a folder's superset style and prove it with N invented one-shots.")
    add_common(mt)
    mt.set_defaults(func=step1)
    # make: learn a style, then draw a NEW text-specified subject in it.
    mk = sub.add_parser("make",
                        help="learn a style, then draw a NEW text-given subject in it (e.g. --prompt 'an archer').")
    add_make_args(mk)
    mk.set_defaults(func=make)
    # clone: learn ONE style, then redraw every file in a target folder in it (1-to-1).
    cl = sub.add_parser("clone",
                        help="learn ONE style, then redraw every file in a target folder in that style (1-to-1).")
    add_clone_args(cl)
    cl.set_defaults(func=clone)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except FatalBackendError as e:
        # Safety net for any single-image path that isn't inside a batch loop: exit cleanly with
        # the reason (and a non-zero code) instead of a traceback. Re-run to resume.
        print(f"\n✖ STOPPED — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
