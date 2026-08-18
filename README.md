# www-gpt-image-2-driver

Learn the *hand* of a folder of reference art (7-lens study → compose → concretize → staging),
then work it with one of three verbs. Run everything from the repo root.

|           | Use it to…                                        | Subject from…    | Card           |
| --------- | ------------------------------------------------- | ---------------- | -------------- |
| **MATCH** | make more originals in the style (invent subjects) | the model        | `RUN_MATCH.md` |
| **MAKE**  | draw a subject you name, in the style             | your text prompt | `RUN_MAKE.md`  |
| **CLONE** | restyle images from another folder, 1-to-1        | an image folder  | `RUN_CLONE.md` |

## Prompts

Paste one into an agent session (Claude Code / Codex) at this repo. Swap the **bold** parts.
Outputs land in `generated/`; scratch goes to `_temporary/` (gitignored, safe to delete).

**MATCH** — more samples of the same style:

```text
Using `base_illustration` as the style, MATCH it: generate new images that invent their own subjects in this style. Outputs go to `generated/`.
```

**MAKE** — a picture of a subject you name:

```text
Using `base_illustration` as the style, MAKE **an archer**: a new image of that subject in this style. Outputs go to `generated/`.
```

**CLONE** — restyle every picture in another folder:

```text
Using `base_illustration` as the style, CLONE `base_illustration_2`: redraw every image in that folder in this style, 1-to-1. Outputs go to `generated/`.
```

Or run the verbs directly:

```bash
python3 imagegen.py match                                  # invent subjects in the hand
python3 imagegen.py make  --prompt "an archer"             # draw a named subject
python3 imagegen.py clone --style base_illustration --target base_illustration_2
```

Every command takes `--dry-run` (plan only, no cost), `--style FOLDER`, and `--attempts N`
(match/make). Full flags live in the cards.

## Layout

```text
imagegen.py            the driver — match / make / clone
RUN_MATCH.md           MATCH card + manual
RUN_MAKE.md            MAKE card + manual
RUN_CLONE.md           CLONE card + manual
GPT-IMAGE-2.md         gpt-image-2 prompting notes
base_illustration/     default style folder (sample-* art)
base_illustration_2/   a second style folder
base_poses/            default CLONE --target (create it, drop images in)
generated/             deliverables (accumulate, never overwritten)
_temporary/            per-run scratch — gitignored
bayer.py               post: Bayer dithering  -> generated/processed-bayer-*
palette.py             post: fixed-palette PNG -> generated/processed-palette-*
imagegen_reset.py      wipe _temporary/ and generated/ (asks first)
```

A **style folder** is any folder of images (`sample-*` preferred); pass a name under the repo
root or an absolute path. CLONE's `--target` is the folder to restyle (default `base_poses/`).
Outputs are 5:7 cards, 1500×2100 @ 300 DPI: `<style>-generated-<n>.png` (match),
`<style>-make-generated-<n>.png` (make), `<target>-clone-generated-<n>.png` (clone).

## Requirements

- Python 3.10+ with **Pillow** (`pip install pillow`)
- **`codex` backend (default):** logged-in Codex CLI whose headless `codex exec` exposes the
  built-in `image_gen` tool — no API key. Check:
  `printf 'output IMAGE_GEN=yes if you have a built-in image generation tool, else IMAGE_GEN=no' | codex exec -s read-only -c approval_policy='"never"' -c model_reasoning_effort='"low"' -`
- **`cli` backend (`--backend cli`):** bundled CLI; needs `OPENAI_API_KEY` and the `openai` SDK.

Don't run two image jobs at once — concurrent generations cross-contaminate the per-call capture.

## Cleanup

```bash
python3 imagegen_reset.py             # summarize, then ask before wiping both
python3 imagegen_reset.py --temp-only # keep deliverables, drop scratch
```
