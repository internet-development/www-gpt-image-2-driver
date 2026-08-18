# RUN_MATCH.md

Focused test card for **MATCH** (the `match` command; `step1` remains an alias): reproduce the
*soul* of a folder of reference art with **pure one-shots** — independent single generations,
produced from ALL the samples at once, each **inventing its own original subject in the same
hand**, for the wielder of the tool to evaluate.

When the user prompts `RUN_MATCH.md`, actually run MATCH, generate the assets,
and report the saved paths. Do not just summarize.

> **Sibling tools — one learned hand, three jobs.** `RUN_MATCH.md` proves a style by INVENTING
> subjects in it. `RUN_MAKE.md` draws a NEW subject **you name in words** ("an archer") in that
> same hand. `RUN_CLONE.md` redraws **existing images** in that hand, 1-to-1. All three learn the
> style with the identical pipeline (`learn_style`): 7-lens manual → compose → concretize →
> staging — so an improvement to the shared study, or to the **descriptive register** it writes
> in, lifts all three at once.

## Philosophy

- **One shot.** Each output is a single generation. No critic, no candidate scoring,
  no refinement loop, no auto-selection — those would have the machine judge quality
  behind closed doors, which it can never get exactly right.
- **N fresh attempts, kept.** We fire several INDEPENDENT one-shots from the same
  prompt; the human picks. Nothing is scored or discarded — every attempt is saved,
  and new runs *accumulate* (see Output numbering) so you can compare everything.
- **Every sample feeds each shot.** All `sample-*` files are attached to every
  generation — not one image per sample, nothing dropped.
- **The superset, never a sub-style.** The prompt must FUSE the full range across
  ALL samples — the rough/loose/odd ones weighted equally with the polished ones.
  Do NOT sideline samples to chase one dominant look; that throws away the breadth
  that makes it *this* body of work. (Learned the hard way: committing to one dominant
  sub-style — e.g. assuming a clean "airy watercolor" hand — throws away the rest of the
  range, including any crude/digital sub-styles the samples actually contain.)
- **Style = technique + form-language.** Two halves, both required. *Technique* is
  HOW marks are made (line, fill, value, surface — in whatever medium the samples use).
  *Form-language* is WHAT this hand draws — its archetypes, motifs, energy, and recurring
  formats (derived from the samples, not assumed). Capturing technique alone
  reproduces the brushwork but invents generic subjects that don't feel like the work;
  the form-language lens (#7) is what makes new pieces *belong* to the body of work.
- **Staging & pose is a technique, not a coincidence.** How a subject is framed and posed —
  crop, camera height/angle, scale in the frame, anchoring, line of action, weight/contrapposto,
  gaze, negative space, depth layering — is as load-bearing as the figure proportions, and it is
  what makes a figure read as deliberate and alive rather than flat, frontal, and dead-centered.
  The technique-only core deliberately drops composition (so each shot is free to invent), so the
  style's framing/pose **system** is recovered as its own directive (`style-staging.txt`, lens #4)
  and every one-shot is **staged by it** — the subject is still invented, but composed in this
  hand's way, not the model's generic default.
- **No specific subject, but an archetype per attempt.** The prompt never names a
  subject; the model invents an ORIGINAL one in this hand. But each attempt is nudged
  into one archetype FAMILY (hero figure / creature / party scene / gear-or-study) so
  a batch spreads across the KINDS of forms the samples contain instead of all
  defaulting to the model's own prior. The new form is drawn from the extracted form
  vocabulary, not copied from any sample.
- **One frontier probe per batch.** The archetype families above are *instance-novelty*
  — fresh draws of KINDS the samples already show. The **final slot of every batch** is
  instead a **frontier / adjacency** attempt (*category-novelty*): it asks the model to
  infer the WORLD the samples imply and draw the piece this same body of work would plausibly
  contain NEXT — a subject family the references imply but never actually show. It is
  higher-variance by design (it leans on technique alone to stay on-brand), so it stays a
  single slot, extrapolates ONLY from the samples' own logic, and is grounded by the
  adjacency catalogue from study lens #6 — never the model's outside prior.
- **Medium, density & finish are read off the samples — never assumed, and weighted by
  majority.** Do NOT default to traditional media, watercolor, "airy/economical", or "polished".
  Derive the actual medium (traditional OR digital — including crude raster / MS-Paint-grade /
  pixel / mouse-drawn looks), the density (sparse OR busy), and the level of refinement (polished
  OR deliberately crude) from the attached samples, and match THAT at its own level. **The failure
  runs in BOTH directions, equally:** the model may "upgrade" a rough, lo-fi source into something
  cleaner and more professional — OR "coarsen" a smooth, cleanly-rendered source by adding paper
  grain, crosshatching, dry-brush, or scan-noise "traditional texture" it does not have. Forbid
  both. Read the **dominant** finish across the set (if 3 of 4 samples are smooth and one is
  textured, smooth is the verdict and the textured one is a secondary variant — never let a single
  outlier or mere scan/JPEG grain set the medium), and **distinguish real surface from
  reproduction noise**. Whatever the samples are, neither prettify nor coarsen them.
- **The describing English is itself a lever — match its register to the medium.** The fidelity of
  a one-shot is bounded by the precision of the prose that defines it; the model obeys register as
  much as nouns, and the most compressed, exact word is also the most depictable. So the study
  writes in **museum-grade, master-draughtsman English** keyed to the medium it finds — *lapidary,
  glazed, luminous* vocabulary (glaze, graded wash, soft terminator, reserved highlight, specular
  spark, lost-and-found edge) for a smooth, clean hand; *loaded / impasto* for thick paint;
  *abraded / lo-fi* for crude raster — and never the forge-and-grunge words (batter, scuff,
  scumble, dry-brush) on a smooth surface. Depictable means **exact, not coarse**: a graded sheen
  is described as a gradient, never posterized into "abrupt value jumps". (Enforced in code by the
  shared `DICTION` directive.)
- **Samples are the only authority.** No external artist/era/genre/style labels
  ("90s", "RPG", "anime"…), and no recognizable pop-culture / franchise / game
  characters or properties — those drag in irrelevant reference points.
- **Less is more, except proportions.** The prompt does NOT pin exact hex codes or
  palette percentages (color is read off the attached samples) and carries no long
  anti-reference wall. The ONE place it stays strictly numeric is **figure
  proportions**, because loose proportions were why earlier humanoids were off.

## What MATCH does

```text
base_illustration/sample-*  ->  generated/base_illustration-generated-<n>.png  (x N attempts)
```

Three-stage prompt build, then N independent one-shots:

1. **Multi-lens ensemble study** (vision) — seven dedicated deep passes over all
   samples, each with full attention on one dimension, assembled into `style-brief.md`:
   1. **Shape & technique census** — goes sample-by-sample so every sample's
      line/curve/form/shape is captured; outliers weighted equally.
   2. **Figure proportion & construction** — pins humanoid proportions in
      *measurable* terms (height in head-lengths, head ratio, eye-line placement,
      feature/limb/hand ratios, stylization), enough to construct a new figure to
      the same measurements.
   3. **Draftsmanship — how it's drawn** (line/curve construction, mark by mark).
   4. **Staging, framing & composition — how the subject sits in the frame** — reverse-engineers
      the framing/pose *system*: crop/shot size, the subject's scale in the frame and anchoring,
      camera height/angle, line of action and weight of the pose, horizon, negative space, depth
      layering, and any recurring compositional template — stated so a NEW subject could be staged
      and posed the same way. This is what MATCH distils into `style-staging.txt`.
   5. **Medium, surface & color** — FIRST determines, from visible evidence only, what the
      work is actually made WITH (traditional physical media OR digital — including crude
      raster / MS-Paint-grade / pixel / mouse-drawn looks), citing the concrete tells; never
      assumes traditional art.
   6. **Charm & soul** (gesture, deliberate imperfection, the human-hand quirks).
   7. **Subject, iconography & form-language — archetypes, not instances** — catalogues
      IN THE ABSTRACT *what* this hand draws and how it imagines form: recurring subject
      families and their frequency, figure archetypes and their stylization spread,
      pose/gesture/energy, motif families, and the world/genre flavour — stated so a NEW
      original subject could be invented that plainly belongs to this body of work. It
      ALSO emits an **adjacency / frontier** list: 4–8 subject families this body of work
      clearly IMPLIES but does NOT itself show — the pieces this body of work would plausibly
      contain next — each tied to the present motifs that imply it, to ground the frontier
      attempt in stage 4. Strictly abstract: never names a specific character, scene, brand,
      or property.
2. **Compose** (vision) → fuse the manual into a potent gpt-image-2 directive
   (`style-core-draft.txt`), **~2000 words (≥1700)**, front-loaded & sectioned:
   make-or-break traits, the line/curve technique, the **exact numeric proportion spec**,
   palette in plain words, a compact **FORM VOCABULARY** (technique + form-language), the
   **sample-derived medium/density/finish lever** (match the samples' real medium and
   refinement — traditional or digital, sparse or dense, polished or crude — never a default),
   a short avoid-list. Must **cover the FULL range (superset)** across all samples — no
   subject, no pop-culture.
3. **Concretize** (vision) → rewrite into the MAXIMALLY DEPICTABLE form
   (`style-core.txt`, the directive actually sent): show-don't-tell (every abstraction →
   the concrete marks that cause it), **keep the full ~2000-word length — do not compress**,
   preserve the breadth and the samples' actual density/finish (do not prettify a crude/digital
   look or coarsen a polished one), keep the proportion spec exact, keep technique +
   form-language, cut only what a camera couldn't see.
   Alongside compose/concretize, the style's **staging/pose system** is distilled from the manual
   into `style-staging.txt` (because the technique-only core drops composition) — a tight,
   depictable directive for how this hand frames and poses a single subject.
4. **Fire N one-shots** — each attempt: gpt-image-2 makes one image from
   `style-core.txt` + ALL samples attached as references. The model invents its own
   ORIGINAL subject, nudged into a per-attempt **archetype family** (hero / creature /
   party / gear-or-study, rotating across the batch) drawn from the extracted form
   vocabulary, **staged and posed per `style-staging.txt`** (load-bearing — no flat,
   frontal, dead-centered default), with the **final slot reserved for the frontier /
   adjacency probe** (infer the world, draw the implied-but-absent next page). Independent draws.

A measured `style-fingerprint.txt` is also computed (k-means palette %, notan,
linework density, etc.) but kept as a **human reference only — never fed to the model.**

> Ceiling: this maxes out one-shot prompt/data quality, but gpt-image-2 is a frozen
> model with its own prior. True mark-level replication has a ceiling that only
> training (a LoRA on these samples) can break.

## Output numbering (accumulate, never overwrite)

New outputs are numbered **past the highest existing** `generated-N.png` in
`generated/`. If `generated-1..4.png` exist, the next run writes
`generated-5..8.png`, the one after `9..12`, and so on — so every run's images stay
visible side by side. (Only pure `generated-N.png` names are counted.) Nothing is
deleted automatically; prune the folder by hand when you want a clean slate.

Each output is reliably bound to **its own fresh generation**: the engine snapshots
the image-gen output set before each call and uses the image that newly appears
(robust against stale files). **Do not run two image jobs at once** (a `match`, a `make`, or a
`clone`) — concurrent generations can cross-contaminate that capture.

## Run it

```bash
# Default: 5 fresh one-shot attempts (4 safe archetypes + 1 frontier probe), accumulated.
python3 imagegen.py match

# Pick the style folder (--style and --target are synonyms here):
python3 imagegen.py match --style base_illustration_2 --attempts 10

# Skip the vision passes (send only the sample images + a generic prompt):
python3 imagegen.py match --no-vision

# Plan only — no generation, no cost:
python3 imagegen.py match --dry-run
```

Flags:

- `--style FOLDER` (alias `--target`) — the samples folder to learn the hand from (name under
  the repo root or an absolute path). Default `base_illustration`; outputs go to
  `generated/<style>-generated-<n>.png`.
- `--attempts N` — number of fresh independent one-shots (default 5: the last slot is the
  frontier probe, the rest rotate through the safe archetypes). `N=1` stays safe (no frontier).
- `--no-vision` — skip the study/compose/concretize passes; send only the samples + a generic prompt.
- `--analysis-effort {minimal,low,medium,high}` — reasoning depth of the vision passes (default high).
- `--codex-effort {minimal,low,medium,high}` — image-worker reasoning effort (default low; image quality unaffected).
- `--target-size WxH` — cover-crop output to exact pixels (default: native).
- `--backend {codex,cli}` — see Backend below.

## Backend & requirements

- **`codex` (default):** drives a headless `codex exec` whose built-in `image_gen`
  tool renders with **gpt-image-2** (no API key). The vision passes run through the
  same session.
  - This requires an account whose **headless `codex exec` actually exposes
    `image_gen`** (not all do — some only expose it in the interactive app). Quick
    check: `printf 'output IMAGE_GEN=yes if you have a built-in image generation tool, else IMAGE_GEN=no' | codex exec -s read-only -c approval_policy='"never"' -c model_reasoning_effort='"low"' -`.
  - If a run shows `image_gen tool is not available` or `You've hit your usage
    limit`, switch to an account that has the tool + quota, or use `--backend cli`.
- **`cli`:** the bundled imagegen CLI with `--model gpt-image-2`; needs
  `OPENAI_API_KEY` and the `openai` SDK. Bypasses Codex entirely.

## Run artifacts

`_temporary/base_illustration-<timestamp>/`:

```text
├── style-inventory.md     # objective per-sample metrics
├── style-fingerprint.txt  # measured signature incl. NATIVE-pixel finish facts — injected into every study pass as ground truth
├── style-brief.md         # the 7-lens style manual (census, proportion, draftsmanship, staging, color, soul, form-language)
├── style-core-draft.txt   # composed directive (pre-concretization)
├── style-core.txt         # final depictable directive actually sent to gpt-image-2
├── style-staging.txt      # the style's framing/pose system, injected into every one-shot
├── prompt-generated-<n>.txt # the exact full prompt per attempt
├── generated-<n>.png      # a copy of each one-shot (also placed in generated/)
├── selection.json         # attempt output paths + samples used
└── reference_pack/         # contact / edge / value / palette sheets (human reference)
```

## How to judge the result

Open the new `generated/<style>-generated-<n>.png` and pick the
best — does it read as a real piece by the same hand as the samples: **the same
medium and finish the samples actually use** (traditional or digital, polished or
deliberately crude — e.g. if the samples are rough mouse-drawn raster sketches, the
output should look rough and raster too, NOT cleaned up into smooth illustration),
charm/soul intact, **and humanoid proportions matching the samples' system** (e.g.
the heads-tall figure spec in `style-core.txt`)? The key failure to watch for is the
model "upgrading" the look — making it cleaner, smoother, or more professional than
the samples. `style-brief.md` and `style-core.txt` show exactly what the model was
told to honor.

If all attempts drift the same way, the levers are input-side: tune `style-core`
emphasis (e.g. a specific proportion ratio), raise `--attempts`, or curate which
samples are in the folder (adding a known-good output as a sample nudges toward it).

## Final report

Report: the new output paths (`generated-<n>.png`), the run dir, the `style-brief`
and `style-core` paths, the backend (`codex`), and the model (`gpt-image-2`).
