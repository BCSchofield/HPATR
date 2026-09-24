# Validation labelling protocol — Step 6

Written 2026-09-21. Read before masking, keep open while masking.

Applies to the **15 validation frames** in
`06_validation/frames/8bit/`. These are the only hand-made ground truth in the
project. Everything the model's accuracy number means depends on them.

---

## What these labels are for — read this before the rules

> **Rewritten 2026-09-23.** This section previously told you to mask to the
> extractor's standard, matching its focus rule by eye. That was wrong and is
> reversed below.

These 15 frames are the **benchmark**. They are never trained on (verified: the
frames are physically absent from the 493-frame training pool, and none were used
as compositing backgrounds). Whatever ends up in these files *defines* what
"correct" means for this project.

That only works if they are **independent of the thing being measured**. The
training set was built by `extract_candidates.py`, so if you label to that same
rule, the benchmark measures "does the model reproduce the extractor" rather than
"does the model find real spray" — and it would hide the extractor's known
small-object focus bias by construction. **Your disagreement with the code is
exactly the signal this set exists to capture.**

So the division of labour is:

| decision | who |
|---|---|
| Is this a real object? | **you**, always |
| Which class is it? | **you**, always |
| Is it dark enough to measure? | **measured in code**, afterwards |
| Where exactly is its edge? | **`refine_labels.py`**, afterwards |

You judge existence and class. Everything numeric is measured from the 16-bit
data afterwards and stored per annotation, so the thresholds can be changed,
swept, or reported by size band later **without re-labelling anything**. The old
worry — that human/extractor disagreement would be confounded with model error —
is handled by recording both, not by forcing you to imitate the code.

One consequence worth stating plainly: **a mislabelled object here matters far
more than one in training.** A training error is one of 33,456 instances and
washes out; an error in these 15 frames goes straight into the D32 and atomised
fraction you report.

---

## Setup

```bash
conda activate phantom

labelme /Volumes/LaCie/Experiments/Real_Data/06_validation/frames/8bit \
  --labels droplet,filament,blob \
  --validate-label exact \
  --output /Volumes/LaCie/Experiments/Real_Data/06_validation/labels
```

> **`--output` is NOT optional.** Without it, LabelMe does not load the existing
> JSON for a frame, treats it as unannotated, and **overwrites it with an empty
> file** when you navigate away or close. This destroyed 33 shapes on
> `frame_0072_n719` on 2026-09-22. Always launch with the full command above.

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

**Draw loosely — the boundary is not your job.** `refine_labels.py` dilates your
shape by 5 px and finds the true half-maximum edge inside it, so a generous
outline at the outer fuzzy edge is ideal and costs nothing. Do not fight SAM's
over-masking, and do not spend time nudging points.

**But the centre does matter.** The refiner picks *which* blob to keep using
your shape's centroid. If your centre lands off the object, or on a neighbour,
it refines the wrong thing. Roughly concentric and generous is the target.

**Where to spend your effort:** filaments and blobs, not droplets. They are
large, far fewer, and they are the un-atomised side of the atomised-fraction
ratio, so each one moves the reported numbers far more than any droplet does.
Small droplets are quantisation-limited anyway (at ~4 px across, one pixel of
mask is ~8% of the area) — be quick and generous on them.

---

## The rules

### 1. Focus — DO NOT JUDGE IT BY EYE

> **Changed 2026-09-23. This section previously told you to skip anything
> lighter than 8-bit 161. That is now wrong — do not follow it.** Earlier frames
> labelled under the old rule are unaffected: nothing was lost, because
> `<frame>.original.json` preserves every shape ever drawn.

**Label every object you can recognise. Never decide whether something is dark
enough — that is measured for you afterwards, from the 16-bit data.**

Your eye cannot reliably separate T=0.70 from T=0.78 on a screen, and it should
not have to. After you save, every annotation gets `min_transmission`,
`in_focus` and `measurable` attached automatically by `validation_to_coco.py`.
Out-of-focus objects are then **kept for detection scoring and excluded from
size statistics** (D32, atomised fraction) — so a soft droplet costs you nothing
by being labelled, and costs you a false negative in the benchmark if it isn't.

Because the raw number is stored, **the cutoff can be moved or swept later
without re-labelling anything.** That is only true if the object is in the file
to begin with.

**The floor is recognisability, not darkness:**

| what you see | do |
|---|---|
| clearly a droplet / filament / blob, any darkness | **label it** |
| recognisable but soft-edged | **label it** — it'll be flagged unmeasurable automatically |
| vague grey haze; can't tell what it is, or whether it's one object or three | **skip it** — you can't be right about it, and neither can the model |

**Consistency matters more than where exactly you draw that line.** Being
generous on frame 1 and strict on frame 15 because you're tired is a real bias
in the benchmark; being uniformly generous, or uniformly strict, is not.

`06_validation/focus_cutoff_reference.png` still exists and still shows the
T = 0.90 / 0.80 / 0.75 / 0.70 / 0.65 discs. It is now **reference only** — useful
for understanding what the numbers mean, not for making a keep/drop decision.

**Do not add a class for blurry droplets.** A soft droplet is labelled
`droplet` like any other. The validation classes must match the training classes
exactly, and focus is an attribute, not a class.

Likewise, ignore the old "if it breaks into scattered specks it's out of focus"
test. Fragmentation is checked automatically, and it is unreliable for filaments
(brightness varies along their length). Label what you recognise.

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
- **Haze you cannot identify** — grey with no discernible form, or where you
  cannot tell whether it is one object or several. Not "anything soft": a
  soft-edged object you can still recognise **does** get labelled (rule 1). The
  test is whether you can say what it is, not how dark it is.

---

## After each frame

```bash
python AI/Real_Data_Code/refine_labels.py --frame frame_0072_n719
```

Snaps **droplets** to the half-maximum edge. Filaments and blobs are left
exactly as you drew them by default — the refiner truncates filaments (it ate
>20% of the length on 23 of 51 on frame 2), and extent is your call, not its.
So trace filaments as accurately as you can: nothing downstream will correct
them. **Never pass `--drop-flagged`** —
that lets the extractor's cutoff delete your judgements, which is the one thing
this whole protocol exists to prevent. Shapes it cannot refine keep your
hand-drawn boundary and get tagged in their description with the reason and the
measured `t_min` (visible in LabelMe when you click the shape). Nothing is ever
removed.

It copies your file to `<frame>.original.json` on first touch. **Never delete
those.** Every number can be recomputed from the image; your judgement about what
is an object cannot. `--from-original` rebuilds a working file from the backup if
anything goes wrong.

---

## When all 15 are done

```bash
python AI/Real_Data_Code/validation_to_coco.py --run-name 125917_NNA_3000sccm
```

This converts the 15 LabelMe JSONs into `06_validation/instances.json` in the
same COCO/RLE format and the same category IDs as the training set, so
evaluation compares like with like. It also reports:

- per-class counts, D32 and median size **computed on `measurable=true` objects
  only** — out-of-focus and border-touching objects are real, and count for
  detection, but their sizes are not trustworthy
- how many objects were excluded from sizing, and why
- how much the focus gate moves droplet D32 (2 µm on frame 1 — it is a small
  effect, because D32 is dominated by the largest objects)
- how many objects touch the frame border
- **any frame with zero annotations** (almost certainly a frame you skipped,
  not a genuinely empty one — the sparsest frame in the whole run still had 44
  detected regions)

Sanity-check those numbers before trusting them. If your droplet count is
wildly below the extractor's rate of ~55 objects per frame, the likely cause
is rule 1 being applied too strictly, not a genuinely empty run.
