# RUN_CLONE.md

**STYLE CLONE**: learn the *exact* style of ONE reference image (the same inference used in
`RUN_MATCH.md`), then **redraw every single file in a target folder in that style** —
a strict **1-to-1 restyle**. Each input keeps WHAT it shows (its subject, pose, composition);
only HOW it is drawn changes (the cloned style).

When the user prompts `RUN_CLONE.md`, actually run the clone, generate the assets, and
report the saved paths. Do not just summarize.

> **Sibling tools — one learned hand, three jobs.** `RUN_MATCH.md` proves a style by INVENTING subjects in it. `RUN_MAKE.md` draws a NEW subject you name in words ("an archer") in that same hand. **`RUN_CLONE.md` redraws existing images in that hand, 1-to-1.** All three learn the style with the identical pipeline (`learn_style`): 7-lens manual → compose → concretize → staging.

## What it does

```text
style source:  base_illustration/sample-1.png        (one image — the style)
target folder: base_poses/*                          (every image — the content)
        ->     generated/base_poses-clone-generated-<n>.png   (one clone per input)
```

- **One style, learned once.** The style is pulled from the `--style` reference with the SAME
  three-stage vision inference MATCH uses — a 7-lens study (`style-brief.md`) → compose
  (`style-core-draft.txt`) → concretize (`style-core.txt`). That single style-core is reused for
  every input; the study runs ONCE, not per file.
- **Every file in the folder is regenerated.** ALL image files in the target folder are restyled
  (not just `sample-*` — whatever the folder holds), in natural-sorted order.
- **Strictly 1-to-1.** Each input image produces exactly ONE output. No archetype rotation, no
  frontier probe, no N-attempts, no critic, no auto-selection — this is a transfer, not an
  invention. Output index `n` maps to the `n`-th input file in natural order.
- **Keep the content, clone the style.** For each input, the model is given the style
  reference(s) AND that one content/pose file, and is told to **keep the subject, pose, gesture,
  and number of figures from the content file**, but **render every mark, line, fill, color,
  surface, and the figure's PROPORTIONS / BUILD in the cloned style's hand**. It must not invent a
  different subject, add/remove figures, or change what is happening.
- **Build/proportion is part of the style — it transfers; scale-in-frame is content — it stays.**
  A style's figure proportions and construction (e.g. small bodies with large heads and quiet,
  minimal faces — or, for another hand, elongated/heroic) are a DEFINING trait of that hand, so
  the clone **rebuilds each content figure to the style's own build**, committing fully to the
  *exact* build the study measured. The study leads with the style's dominant signature and uses
  precise, distinctive language rather than generic shorthand like "chibi" — so a tall,
  naturalistically-proportioned pose is rebuilt to that signature build in the *same pose,
  viewpoint, and composition*, at the style's true rendering character and detail level, not
  simplified into a flatter or cuter cartoon. What does NOT transfer is the style source's
  *scale-in-frame* — if the source packs small figures onto a big page, the clone still fills its
  own 5:7 card with the re-proportioned subject at the content file's framing.
- **Faces are rebuilt to the style's face — likeness is subordinate.** When the content is a
  photo (or any detailed portrait) of a specific person, the biggest failure is the model
  preserving the real face's *likeness* — modeled cheeks, a rendered smile with teeth,
  photographic eyes, skin/stubble shading — instead of the style's own face construction. The
  clone **rebuilds every face to the style's face grammar** (its eye/nose/mouth marks and its low
  facial mark-count) and keeps only a few identity CUES (glasses, beard vs. clean-shaven, hair
  color/length, a hat) drawn as the style's own flat marks. The face reads FIRST as one of the
  style's faces and only incidentally resembles the person: **if likeness conflicts with the
  style's minimal face, the STYLE WINS.** (A style with detailed, portrait-like faces is rebuilt
  to *that* — the rule is "match the style's face," not "always minimize".)
- **Framing/pose is part of the style, too — `--framing` dials it.** How a subject is staged
  (crop, camera height/angle, scale in the frame, anchoring, line of action, negative space,
  depth) is itself a technique, so the clone learns the style's framing/pose **system** (saved as
  `style-staging.txt`) and, by default, **re-stages each pose into it**. `--framing keep` locks
  composition to the content file (strict 1-to-1 restyle, the old behavior); `--framing balance`
  (default) keeps the subject + pose but re-frames it in the style's composition; `--framing
  style` keeps only the subject's identity + action and fully re-stages the pose AND framing.
  This matters most for painterly/atmospheric styles, where the look lives partly in the staging;
  for flat line-art styles `keep` and `balance` look nearly identical.
- **Match the style's real medium & finish — never "upgrade".** Same rule as replication: clone
  the style at its own level (traditional or digital, polished or deliberately crude). Do NOT
  prettify a rough/lo-fi source or coarsen a polished one.
- **Samples are the only authority.** No external artist/era/genre/style labels and no
  recognizable pop-culture / franchise / game properties.

## Card dimensions (same as before)

Every output is the same deliverable format as MATCH: a **5:7 portrait at 300 DPI =
1500x2100 px** (codex backend cover-crops to exactly this). The content file's pose and
composition are preserved while filling that frame top-to-bottom with no added borders, keeping
key detail clear of the edges so nothing important is lost in the crop.

## Output naming

```text
generated/<target-folder-name>-clone-generated-<n>.png
```

e.g. `base_poses-clone-generated-1.png … base_poses-clone-generated-19.png`. `n` is the 1-based
index of the input file in natural-sorted order, so the clone set mirrors the source folder.
Re-running regenerates the set fresh (overwriting these deliverables); a full run copy + the
exact prompt for each is also kept in the run dir.

## Run it

```bash
# Default: clone base_illustration/sample-1.png's style onto every file in base_poses/.
python3 imagegen.py clone

# Explicit (equivalent to the default):
python3 imagegen.py clone --style base_illustration/sample-1.png --target base_poses

# Any style source (a single file OR a folder) onto any target folder:
python3 imagegen.py clone --style base_illustration_2/sample-1.png --target base_poses

# Plan only — no generation, no cost (lists every input -> output mapping):
python3 imagegen.py clone --dry-run
```

Flags:

- `--style PATH` — the style SOURCE. An image **file** (the usual case, e.g.
  `base_illustration/sample-1.png`) or a **folder** (uses its `sample-*` images if present, else
  every image in it). Default `base_illustration/sample-1.png`.
- `--target FOLDER` — the folder whose EVERY image is restyled, 1-to-1 (name under the repo root
  or an absolute path). Default `base_poses`.
- `--framing {keep,balance,style}` — how much of the COMPOSITION comes from the style vs. the
  pose file (default `balance`). `keep` = lock crop/camera/silhouette/layout to the pose (strict
  1-to-1 restyle); `balance` = keep the subject + pose, re-stage the framing into the style's
  habits; `style` = keep only the subject's identity + action, fully re-stage pose AND framing.
- `--analysis-effort {minimal,low,medium,high}` — depth of the style-study vision passes (default high).
- `--style-hint TEXT` — optional authoritative note about the style's TRUE medium/technique
  (e.g. `"mouse-drawn raster, low detail, flat bucket fills"`), injected into every study pass
  as ground truth. Normally unnecessary — the study now measures finish at native pixels and
  sees a native-pixel technique-crop sheet — but decisive when a style is easy to misread.
- `--codex-effort {minimal,low,medium,high}` — image-worker reasoning effort (default low; image quality unaffected).
- `--target-size WxH` — cover-crop output to exact pixels (default `1500x2100` = the 5:7 card; `auto` keeps native).
- `--no-vision` — skip the study passes; send only the style + content images with a generic transfer prompt.
- `--backend {codex,cli}` — `codex` (default, gpt-image-2 via the live session) or `cli` (needs `OPENAI_API_KEY`).
- `--force` — overwrite existing outputs (deliverables are regenerated fresh regardless).

> **Do not run two image jobs at once** (a `clone`, a `match`, or a `make`) — concurrent
> generations can cross-contaminate the engine's per-call output capture.

## Backend & requirements

Identical to `RUN_MATCH.md`:

- **`codex` (default):** drives a headless `codex exec` whose built-in `image_gen` tool renders
  with **gpt-image-2** (no API key). The vision study passes run through the same session.
  Requires an account whose headless `codex exec` actually exposes `image_gen`. Quick check:
  `printf 'output IMAGE_GEN=yes if you have a built-in image generation tool, else IMAGE_GEN=no' | codex exec -s read-only -c approval_policy='"never"' -c model_reasoning_effort='"low"' -`.
- **`cli`:** the bundled imagegen CLI with `--model gpt-image-2`; needs `OPENAI_API_KEY` and the
  `openai` SDK.

## Run artifacts

`_temporary/<target>-clone-<timestamp>/`:

```text
├── style-inventory.md       # objective metrics of the style source
├── style-fingerprint.txt    # measured signature of the style source, incl. NATIVE-pixel finish facts (stroke width/wobble, edge softness, detail scale, flat-fill coverage) — injected into every study pass as ground truth
├── style-brief.md           # the 7-lens style manual for the cloned style
├── style-core-draft.txt     # composed style directive (pre-concretization)
├── style-core.txt           # final depictable style directive actually sent to gpt-image-2
├── style-staging.txt        # the style's framing/pose system (re-stages each pose; balance/style only)
├── prompt-<target>-clone-generated-<n>.txt   # the exact full prompt per input
├── <target>-clone-generated-<n>.png          # a copy of each clone (also placed in generated/)
├── reference_pack/          # contact / edge / value / palette sheets of the style source (human reference)
└── selection.json           # style refs + every input->output mapping
```

## How to judge the result

Open each `generated/<target>-clone-generated-<n>.png` next to its source input: does
it keep the SAME subject, pose, and composition as the input, while reading as a real piece in
the **style source's hand** — the same medium and finish (traditional or digital, polished or
deliberately crude), line/curve quality, color, and humanoid proportions? The key failure to
watch for is the model (a) drifting off the input's pose/subject, or (b) "upgrading" the style —
making it cleaner, smoother, or more professional than the style reference actually is.
`style-brief.md` and `style-core.txt` show exactly what the model was told to honor.

If clones drift the same way, the levers are input-side: pick a clearer/stronger `--style`
reference (or a small style folder instead of one file), tune `style-core` emphasis (e.g. a
specific proportion ratio), raise `--analysis-effort`, or assert the true technique with
`--style-hint`. The most common drift — "upgrading" a crude/lo-fi hand into polished
illustration — is countered automatically: the study passes receive native-pixel finish
measurements and a 1:1 technique-crop sheet, which override the smoothed impression the
model gets from its downscaled view of the samples.

## Final report

Report: the new output paths (`<target>-clone-generated-<n>.png` + their source files), the run
dir, the `style-brief` and `style-core` paths, the backend (`codex`), and the model
(`gpt-image-2`).
