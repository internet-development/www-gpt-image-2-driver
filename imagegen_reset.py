#!/usr/bin/env python3
"""Reset the imagegen workspace back to a clean slate.

Wipes the two disposable output locations imagegen.py writes to:

  _temporary/   -- all per-run working dirs, logs, reference packs (RUNS_DIR)
  generated/    -- every rendered deliverable (output_dir_for)

Nothing else is touched: the style sample folders (base_illustration_*, base_poses, ...)
and the source scripts are all left alone. The two dirs are recreated empty so the next
imagegen.py run has somewhere to write.

Because `generated/` holds real deliverables, this PROMPTS before deleting unless you pass
--yes. Preview with --dry-run.

Usage:
  python3 imagegen_reset.py                # summarize, then ask before wiping both
  python3 imagegen_reset.py --yes          # wipe both, no prompt
  python3 imagegen_reset.py --dry-run      # show what would be removed, delete nothing
  python3 imagegen_reset.py --temp-only    # only _temporary (keep deliverables)
  python3 imagegen_reset.py --generated-only  # only generated/ (keep run artifacts)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REF_DIR = Path(__file__).resolve().parent
# Kept in sync with imagegen.py: RUNS_DIR = ROOT / "_temporary"; output_dir_for -> ROOT / "generated".
RUNS_DIR = REF_DIR / "_temporary"
GENERATED_DIR = REF_DIR / "generated"


def summarize(path: Path) -> tuple[int, int]:
    """Return (entry_count, total_bytes) for everything directly/recursively under `path`."""
    if not path.exists():
        return (0, 0)
    entries = 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file() or p.is_symlink():
            entries += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return (entries, total)


def human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.0f}{unit}" if unit == "B" else f"{f:.1f}{unit}"
        f /= 1024
    return f"{f:.1f}TB"


def clear_dir(path: Path, dry_run: bool) -> None:
    """Remove every entry inside `path` (keep the dir itself), recreating it if missing."""
    if dry_run:
        return
    if path.exists():
        for child in path.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    path.mkdir(parents=True, exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset imagegen temp + generated folders to a clean slate.")
    ap.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--dry-run", action="store_true", help="show what would be removed; delete nothing")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--temp-only", action="store_true", help="only clear _temporary/ (keep deliverables)")
    group.add_argument("--generated-only", action="store_true",
                       help="only clear generated/ (keep run artifacts)")
    a = ap.parse_args()

    targets: list[Path] = []
    if not a.generated_only:
        targets.append(RUNS_DIR)
    if not a.temp_only:
        targets.append(GENERATED_DIR)

    print("imagegen_reset — the following will be cleared:")
    grand_files = grand_bytes = 0
    for t in targets:
        n, b = summarize(t)
        grand_files += n
        grand_bytes += b
        state = "(missing)" if not t.exists() else f"{n} files, {human(b)}"
        print(f"  {t}   {state}")
    print(f"  total: {grand_files} files, {human(grand_bytes)}")

    if a.dry_run:
        print("\n[dry-run] nothing deleted.")
        return 0

    if grand_files == 0:
        print("\nAlready clean — nothing to do.")
        # still ensure the dirs exist for the next run
        for t in targets:
            t.mkdir(parents=True, exist_ok=True)
        return 0

    if not a.yes:
        try:
            reply = input("\nDelete these and start over? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    for t in targets:
        clear_dir(t, dry_run=False)
    print(f"Done — cleared {grand_files} files. Workspace reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
