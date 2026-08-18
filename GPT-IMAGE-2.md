# GPT-IMAGE-2.md

What's optimal when prompting **gpt-image-2** — with a focus on *style extraction* (pull a
hand's technique out of reference art and generate new forms that continue it), which is what
`imagegen.py` does in its three modes (`match` / `make` / `clone`; see `RUN_MATCH.md`,
`RUN_MAKE.md`, `RUN_CLONE.md`).

> Compiled 2026-06-28. Model: `gpt-image-2-2026-04-21`, released 2026-04-21. Sources are
> linked inline and listed at the bottom; claims from non-OpenAI pages are marked *(community)*.

---

## 1. What kind of model it is

gpt-image-2 is OpenAI's current state-of-the-art image model: an **instruction-following,
multimodal** generator/editor (text **and** images in), not a CLIP/keyword diffusion model
like older Stable Diffusion / Midjourney. Practical consequences:

- It **reads natural-language sentences** and honors structure, ordering, and constraints. You
  do **not** "spam tags."
- Strong instruction following and near-perfect in-image text rendering; up to **4K
  (4096×4096)**; ~2× faster than its predecessor; context-aware multi-turn editing.
- It still **"may occasionally struggle to maintain visual consistency for recurring
  characters or brand elements,"** and with **"precise text placement."**

Sources: [gpt-image-2 model doc][m2], [Introducing ChatGPT Images 2.0][intro],
[Image generation guide][guide].

---

## 2. Prompt length

- **Hard maximum: 32,000 characters** for GPT image models (vs 1,000 for dall-e-2, 4,000 for
  dall-e-3). ([Create image API reference][apiref]) ~2000 words ≈ ~12,000–13,000 characters —
  comfortably **within** the limit.
- **OpenAI does NOT say long prompts are worse.** The prompting guide states plainly:
  *"Long prompts can work well, but debugging is easier when you start with a clean base prompt
  and refine with small, single-change follow-ups."* It is explicitly length- and
  format-agnostic: *"Minimal prompts, descriptive paragraphs, JSON-like structures,
  instruction-style prompts, and tag-based prompts can all work well as long as the intent and
  constraints are clear."* What it rewards is **clarity, structure, and maintainability**, not
  brevity. ([Prompting guide][pg])
- For casual ChatGPT use, *"a good image prompt does not need to be long — in most cases, 1–3
  clear sentences are enough"* — a statement about *sufficiency*, not a cap. ([Academy][academy])

**Honest caveat (NOT from OpenAI):** the worry that a very long prompt "dilutes" earlier
instructions is a **general LLM heuristic**. OpenAI does not document any such penalty for
gpt-image-2, and there is no measured evidence here that 2000 words hurts. So a ~2000-word,
well-structured, front-loaded technique directive is a legitimate, in-spec choice. The thing
the docs reward **regardless of length** is structure + front-loading + clear constraints
(Sections 3–5) — so a long prompt should still be sectioned and lead with the make-or-break
traits.

---

## 3. Optimal structure

OpenAI's recommended section order ([Prompting guide][pg]):

1. **Background / scene**
2. **Subject**
3. **Key details**
4. **Constraints** (explicit do's/don'ts — what to preserve vs change)
5. **Intended use** (sets the "mode" and level of polish)

Plus:
- **Clarity beats cleverness** — *"soft natural light from a window on the left"* outperforms
  *"beautiful lighting."*
- **Front-load** what matters; use labeled segments for anything complex.

---

## 4. Style transfer / style extraction

This is the relevant part for us.

- **Separate what stays from what changes:** *"describe what must stay consistent (style cues)
  and what must change (new content)."* The canonical move is to attach a style image and say
  *"use the same style from the input image,"* then specify the **new** subject. ([Prompting
  guide][pg])
- **Reference images are descriptive anchors, not a replacement for text.** With multiple
  inputs, *"reference each input by index and description"* and describe how they interact.
  The images carry the *texture* (paper grain, wash behavior, line quality); the text names
  **what to honor and prioritize**. ([Prompting guide][pg])
- **gpt-image-2 input is already high-fidelity.** `input_fidelity` (`low`/`high`) exists only
  for `gpt-image-1.5` / `gpt-image-1`; for gpt-image-2 it **does not apply — "output is already
  high fidelity by default."** So you don't need a fidelity knob; you rely on the attached
  references directly. ([Prompting guide][pg])

**Implication:** for "pull out the style and generate new forms," the **attached samples do
most of the work.** The text's job is to (a) name the make-or-break technique, (b) say
"continue this hand, invent a new subject," and (c) constrain out what would betray the hand.

---

## 5. Negative / "avoid" instructions

- Frame negatives as **constraints (preserve vs change)** rather than a wall of "no X."
- **State exclusions explicitly** (e.g., *"no watermark," "no extra text"*) and **repeat the
  preservation list across iterations.** ([Prompting guide][pg])
- Positive description ("do this") is more reliable than a long list of negatives — keep the
  avoid-list short.

---

## 6. Recommended configuration for our pipeline

Goal: extract the superset hand's **technique** and generate **new forms** that continue it
(no subject, no pop-culture references), kept **loose/economical**.

| Lever | Recommended | Why |
|---|---|---|
| Final directive length (`style-core.txt`) | **~2000 words, front-loaded & sectioned** (any length ≤32k chars is in-spec) | OpenAI: "long prompts can work well"; structure + front-loading matter more than word count |
| What the text carries | the 3–5 make-or-break traits, one numeric proportion spec, medium/value/palette in plain words, short avoid-list | Names priorities; lets images carry texture |
| What the **images** carry | paper grain, wash/line texture, mark quality | gpt-image-2 input is high-fidelity by default |
| Subject | none; "continue this hand, invent an original subject" | Style extraction, not subject copy |
| Constraints | explicit, short: no subject copy, no franchise/brand, no smooth-digital finish | Negatives work best when few + explicit |

**On the 2000-word directive:** it's well within the 32k limit and is a valid choice — OpenAI
says long prompts can work well. To keep it effective at that length, lean on the levers the
docs actually reward: front-load the make-or-break traits, keep clear labeled sections, and
state constraints explicitly. An A/B against a shorter directive would *measure* (rather than
assume) whether length helps here — optional, not a correction.

---

## Sources

- [GPT Image Generation Models — Prompting Guide (OpenAI Cookbook)][pg]
- [GPT Image 2 — model doc (OpenAI API)][m2]
- [Image generation — guide (OpenAI API)][guide]
- [Create image — API reference (32,000-char limit)][apiref]
- [Introducing ChatGPT Images 2.0 (OpenAI)][intro]
- [Creating images with ChatGPT — academy (OpenAI)][academy]
- [OpenAI Developer Community — clarifies the 32,000-*character* (not token) prompt limit][community] *(community)*

[pg]: https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide
[m2]: https://developers.openai.com/api/docs/models/gpt-image-2
[guide]: https://developers.openai.com/api/docs/guides/image-generation
[apiref]: https://developers.openai.com/api/reference/resources/images/methods/generate
[intro]: https://openai.com/index/introducing-chatgpt-images-2-0/
[academy]: https://openai.com/academy/image-generation/
[community]: https://community.openai.com/t/bug-in-the-new-image-generation-api-with-large-prompt-size/1239920
