# RUN_MAKE.md

**MAKE** (the `make` command): learn a hand from a folder of reference art, then **draw a NEW
subject you specify in words** — *"an archer"*, *"a sleeping dragon"*, *"a market stall"* — in that
same hand. There is **no visual reference for the subject**: the subject comes from the prompt, the
*look* comes from the samples. The model invents the specific design and renders it as if the style
artist had drawn it from scratch.

When the user prompts `RUN_MAKE.md` (with a subject), actually run MAKE, generate the assets, and
report the saved paths. Do not just summarize.

> **Sibling tools — one learned hand, three jobs.** `RUN_MATCH.md` proves a style by INVENTING its
> own subjects. **`RUN_MAKE.md` draws a subject YOU name, in words.** `RUN_CLONE.md` redraws
> EXISTING images, 1-to-1. All three learn the style with the identical pipeline (`learn_style`):
> 7-lens manual → compose → concretize → staging.

## Where MAKE sits

|              | Subject comes from…            | Look comes from…        |
| ------------ | ------------------------------ | ----------------------- |
| **match**    | the model **invents** it       | the sample folder       |
| **make**     | **your text prompt**           | the sample folder       |
| **clone**    | an **existing image** you give | the style source        |

MAKE is the bridge between the two: as free as `match` about the design (it invents the actual
character/creature/object), but as **directed** as `clone` about *what the thing is* (you asked for
an archer, you get an archer) — without needing a reference picture of one.

## Philosophy

MAKE inherits the whole `RUN_MATCH.md` philosophy — read it first. The same rules bind here:

- **One shot, N fresh attempts, kept.** Each output is a single independent generation of the same
  subject; nothing is scored, critiqued, or auto-selected. The variation across attempts is the
  model's own, for the human to pick from. New runs **accumulate** (see Output numbering).
- **Every sample feeds each shot.** All `sample-*` files are attached to every generation as
  reference for the **hand only — never the subject**.
- **Style = technique + form-language; the subject is filtered through both.** You name *what* to
  draw; the hand decides *how it looks AND how this world imagines that thing* — its archetypes,
  costume, anatomy, proportion, motifs, and energy. "An archer" rendered in a stocky big-head
  heroic hand is a *different* archer than in a tall romantic one, and MAKE must produce the
  former's archer, built to the former's proportion spec, not a generic one.
- **Staged by the style.** The subject is composed and posed by the style's framing/pose system
  (`style-staging.txt`, the same one `match` and `clone` use) — never a flat, frontal,
  dead-centered default.
- **Medium, density & finish are read off the samples — never assumed, weighted by majority, and
  the failure runs both ways.** Do not "upgrade" a rough source into something cleaner, and do not
  "coarsen" a smooth, cleanly-rendered source by adding paper grain, crosshatching, dry-brush, or
  scan-noise texture it does not have. Match the **dominant** finish; distinguish real surface from
  reproduction noise.
- **Museum-grade describing register, matched to the medium.** The style is studied and the
  directive written in master-draughtsman English keyed to the medium found — *glazed/luminous*
  for a smooth hand, *loaded/impasto* for thick paint, *abraded/lo-fi* for crude raster — and
  depictable means **exact, not coarse** (a graded sheen stays a gradient, never a posterized
  jump). Enforced in code by the shared `DICTION` directive.
- **No specific named subject, no pop-culture.** Draw *an* archer, never a *named* archer from any
  franchise/game/property; design an original one that belongs to this body of work.
- **Samples are the only authority.** No external artist/era/genre/style labels.

## What MAKE does

```text
style: <style>/sample-*  +  prompt: "an archer"
   ->  generated/<style>-make-generated-<n>.png   (x N attempts)
```

Same three-stage prompt build as `match` (learned once, reused for every attempt):

1. **Multi-lens ensemble study** (vision) → `style-brief.md` — seven deep passes (census,
   proportion, draftsmanship, staging, medium, charm, form-language).
2. **Compose** (vision) → `style-core-draft.txt` — fuse the manual into a potent technique-only
   directive.
3. **Concretize** (vision) → `style-core.txt` — rewrite into the maximally depictable form (the
   directive actually sent). Alongside, **`style-staging.txt`** distils the framing/pose system.
4. **Fire N one-shots** — each attempt: gpt-image-2 makes one image from `style-core.txt` + ALL
   samples attached as references, drawing **your named subject**, staged per `style-staging.txt`,
   built to the style's proportion spec. Independent draws of the same subject.

A measured `style-fingerprint.txt` is also computed but kept as a **human reference only — never
fed to the model.**

> Ceiling: this maxes out one-shot prompt/data quality, but gpt-image-2 is a frozen model with its
> own prior. True mark-level replication has a ceiling that only training (a LoRA on these samples)
> can break.

## Output numbering (accumulate, never overwrite)

New outputs are numbered **past the highest existing** `<style>-make-generated-N.png` in
`generated/`. MAKE outputs are kept **separate** from `match`
(`<style>-generated-N.png`) and `clone` (`<style>-clone-generated-N.png`), so the three never
collide. Nothing is deleted automatically; prune by hand for a clean slate.

Each output is reliably bound to **its own fresh generation** (the engine snapshots the image-gen
output set before each call and uses the image that newly appears). **Do not run two image jobs at
once** (a `make`, a `match`, or a `clone`) — concurrent generations can cross-contaminate that
capture.

## Run it

```bash
# Draw "an archer" in the base_illustration hand (default style folder), 4 attempts:
python3 imagegen.py make --prompt "an archer"

# A different style folder + more attempts:
python3 imagegen.py make --style base_illustration_2 --prompt "an archer" --attempts 6

# Plan only — no generation, no cost:
python3 imagegen.py make --style base_illustration_2 --prompt "a sleeping dragon" --dry-run
```

Flags:

- `--prompt "…"` (alias `--subject`) — **required.** The new subject to draw, in words. Rendered in
  the learned style; there is no visual reference for the subject itself.
- `--style FOLDER` (alias `--target`) — the samples folder to learn the hand from (uses its
  `sample-*` images, else every image; name under the repo root or an absolute path). Default
  `base_illustration`. Outputs go to `generated/<style>-make-generated-<n>.png`.
- `--attempts N` — number of fresh independent one-shots of the SAME subject (default 4).
- `--analysis-effort {minimal,low,medium,high}` — depth of the style-study vision passes (default high).
- `--codex-effort {minimal,low,medium,high}` — image-worker reasoning effort (default low; image quality unaffected).
- `--target-size WxH` — cover-crop output to exact pixels (default `1500x2100` = the 5:7 card; `auto` keeps native).
- `--no-vision` — skip the study passes; send only the samples + a generic prompt with the subject.
- `--backend {codex,cli}` — `codex` (default, gpt-image-2 via the live session) or `cli` (needs `OPENAI_API_KEY`).

## Card dimensions

Same deliverable as the siblings: a **5:7 portrait at 300 DPI = 1500x2100 px** (codex backend
cover-crops to exactly this), filling the frame top-to-bottom with no borders, the subject and key
detail kept clear of the edges.

## Backend & requirements

Identical to `RUN_MATCH.md`:

- **`codex` (default):** drives a headless `codex exec` whose built-in `image_gen` tool renders
  with **gpt-image-2** (no API key). The vision study passes run through the same session. Requires
  an account whose headless `codex exec` actually exposes `image_gen`. Quick check:
  `printf 'output IMAGE_GEN=yes if you have a built-in image generation tool, else IMAGE_GEN=no' | codex exec -s read-only -c approval_policy='"never"' -c model_reasoning_effort='"low"' -`.
- **`cli`:** the bundled imagegen CLI with `--model gpt-image-2`; needs `OPENAI_API_KEY` and the
  `openai` SDK.

## Run artifacts

`_temporary/<style>-make-<timestamp>/`:

```text
├── style-inventory.md     # objective per-sample metrics
├── style-fingerprint.txt  # measured signature incl. NATIVE-pixel finish facts — injected into every study pass as ground truth
├── style-brief.md         # the 7-lens style manual
├── style-core-draft.txt   # composed directive (pre-concretization)
├── style-core.txt         # final depictable directive actually sent to gpt-image-2
├── style-staging.txt      # the style's framing/pose system, injected into every one-shot
├── prompt-<style>-make-generated-<n>.txt # the exact full prompt per attempt
├── <style>-make-generated-<n>.png        # a copy of each one-shot (also placed in generated/)
├── selection.json         # subject + attempt output paths + samples used
└── reference_pack/        # contact / edge / value / palette sheets (human reference)
```

## How to judge the result

Open the new `generated/<style>-make-generated-<n>.png` and pick the best. Two questions:
(1) **Is it the subject you asked for?** — an archer should read as an archer. (2) **Does it read as
a real piece by the same hand as the samples?** — the same medium and finish the samples actually
use (smooth or textured, traditional or digital, polished or deliberately crude — *not* upgraded or
coarsened), charm/soul intact, and humanoid proportions matching the samples' system. The key
failure to watch for is the model defaulting to its OWN generic depiction of the subject instead of
filtering it through this hand's form-language and proportion spec. `style-brief.md` and
`style-core.txt` show exactly what the model was told to honor.

If every attempt drifts the same way, the levers are input-side: sharpen the subject wording, raise
`--attempts`, tune `style-core` emphasis (e.g. a proportion ratio), or curate which samples are in
the style folder.

## Final report

Report: the subject, the new output paths (`<style>-make-generated-<n>.png`), the run dir, the
`style-brief` and `style-core` paths, the backend (`codex`), and the model (`gpt-image-2`).
