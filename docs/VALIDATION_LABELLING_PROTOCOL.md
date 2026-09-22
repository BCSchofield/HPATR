# Validation labelling protocol — Step 6

Written 2026-09-21. Read before masking, keep open while masking.

Applies to the **15 validation frames** in
`06_validation/frames/8bit/`. These are the only hand-made ground truth in the
project. Everything the model's accuracy number means depends on them.

---

## Why the rules below are not negotiable

The extractor makes three decisions **by rule**, in code: what counts as
in-focus, what is too small to measure, and where droplet ends and blob
begins. The training set was built entirely under those rules.

If you mask by a different standard than the code used, the accuracy figure
measures *the disagreement between you and the extractor*, not the model. A
model that is working perfectly will look broken, or vice versa, and there is
no way to tell which afterwards.

So: the rules below are the code's rules, translated into things you can judge
by eye. Follow them even where your instinct says otherwise — and if your
instinct disagrees strongly with a rule, that is worth raising as a change to
the *pipeline*, not a one-off exception here.

---

## Setup

```bash
conda activate phantom

labelme /Volumes/LaCie/Experiments/Real_Data/06_validation/frames/8bit \
  --labels droplet,filament,blob \
  --validate-label exact \
  --output /Volumes/LaCie/Experiments/Real_Data/06_validation/labels
```

- `--labels` pre-fills the three class names; `--validate-label exact`
  **refuses anything else**, so a typo cannot silently create a fourth class.
- Autosave is on by default in 6.3.1 (`--no-auto-save` turns it off — don't).
- Image data is *not* embedded in the JSON by default, which is what we want:
  the JSONs stay small and reference the images by filename.
- Work on the **8-bit** frames. LabelMe cannot display 16-bit TIFFs usefully,
  and it does not matter — masks are pixel geometry, and the 8-bit and 16-bit
  frames share an identical pixel grid, so a mask drawn on one applies exactly
  to the other.

## Using LabelMe efficiently

Your install has **SAM2 weights already cached locally** (781 MB, no network
needed), so use the AI tools rather than tracing by hand:

| Tool | When | How |
|---|---|---|
| **AI-Box** | almost everything | Pick the AI-Box tool, drag a box loosely around one object, SAM returns its outline. Fastest path for droplets and filaments alike. |
| **AI-Points** | when the box grabs a neighbour too | Click inside the object; click again to refine. |
| **Create Polygon** | tiny objects, and fixing SAM | Manual. Below ~6 px SAM has nothing to lock onto, so just place 4–6 points. |

Keys worth knowing: `D` next image, `A` previous, `Ctrl+Z` undo, `Ctrl+J` edit
polygon points, `Delete` remove selected shape, `Ctrl+H` hide/show all shapes
(use this constantly to check you haven't missed anything underneath).

**One shape per object.** Do not merge two droplets into one polygon because
they are close together.

---

## The rules

### 1. Focus — the cutoff that decides if it exists at all

**An object must reach 8-bit brightness 161 or darker somewhere inside it.**
Background is ~234. If its darkest point is lighter than 161, do not label it
at all.

Open `06_validation/focus_cutoff_reference.png` alongside your work — it shows
grey discs at T = 0.90 / 0.80 / 0.75 / **0.70** / 0.65 / 0.55 against the real
background, with the cutoff marked. Compare against it whenever you are unsure.

| what you see | T | 8-bit | verdict |
|---|---|---|---|
| barely there | 0.90 | 210 | ignore |
| clearly visible, soft | 0.80 | 185 | ignore |
| obvious but grey | 0.75 | 173 | ignore |
| **cutoff** | **0.70** | **161** | **label** |
| solidly dark | 0.65 | 149 | label |

This is `--focus-max 0.70` in `extract_candidates.py`. It exists because
defocus inflates apparent size, so anything softer than this cannot be
measured honestly. **Soft grey blobs are not missed objects — they are
deliberately excluded, and the model is trained to ignore them.** Leaving them
unlabelled is correct.

Second focus test, from the same decision: if an object's edge is so ragged it
breaks into scattered specks rather than one coherent shape, it is
out of focus. Don't label it.

### 2. Minimum size

**Do not label anything smaller than about 4 pixels of area** — roughly a 2×2
block. The measurement floor is ~23 µm; below that the extractor does not
produce objects either.

### 3. Which class

Decide in this order:

1. **Is it long and thin?** Measure *along* the object, not around it: length
   ÷ its own width. If that ratio is **≥ 3** *and* it is **≥ 20 px long** →
   `filament`. This holds for curved, V-shaped and looped threads — a
   horseshoe is still a filament even though its bounding box is square.
2. **Otherwise it is compact.** Equivalent diameter **≤ 20 px (200 µm)** →
   `droplet`. Larger → `blob`.

20 px ≈ 200 µm is the Rayleigh-derived ceiling from handoff decision 2. Judge
it by area, not by longest dimension: a 30 × 8 px crescent is well under the
ceiling and is a `droplet`.

### 4. Objects that touch each other

**Label them separately, one shape each**, even where they visually merge.
This matches the training data: composited objects overlap and keep separate
masks, because in a shadowgraph nothing occludes anything — light passes
through both.

### 5. Objects running off the frame edge

**Label them normally.** The model will detect them at inference, so leaving
them unlabelled would score real detections as false positives. Their measured
size is meaningless, but the converter flags them automatically so they can be
dropped from size statistics later. You do not need to mark them.

---

## Things that are NOT objects

- **The static smudge along the top edge and the vignette at right.** Present
  in every frame including pre-trigger. Dirt and illumination, not spray.
- **Bright regions.** Only *dark* (absorbing) regions are liquid. White rims
  beside dark objects are refraction at the liquid boundary — part of the
  scene, never their own object.
- **Faint digit-like marks inside near-opaque objects.** Dust inside the
  camera, only visible where an object blocks nearly all light. Part of the
  object it sits inside; do not carve it out.
- **Soft grey out-of-focus blobs** — see rule 1.

---

## When you're done

```bash
python AI/Real_Data_Code/validation_to_coco.py --run-name 125917_NNA_3000sccm
```

This converts the 15 LabelMe JSONs into `06_validation/instances.json` in the
same COCO/RLE format and the same category IDs as the training set, so
evaluation compares like with like. It also reports:

- per-class counts, and size distribution versus the training set
- how many objects touch the frame border
- **any frame with zero annotations** (almost certainly a frame you skipped,
  not a genuinely empty one — the sparsest frame in the whole run still had 44
  detected regions)

Sanity-check those numbers before trusting them. If your droplet count is
wildly below the extractor's rate of ~55 objects per frame, the likely cause
is rule 1 being applied too strictly, not a genuinely empty run.
