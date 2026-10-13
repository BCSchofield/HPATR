# CCD day (2026-10-12): atomised fraction by area vs by volume (F2), and window drops (H1)

2026-10-13 (Mac), phases F2 + H1 of `docs/notes/2026-10-13_CCD_followup_plan.md`. Done by a sub-agent,
read-only on the LaCie; the headline numbers below were re-derived from `per_run_f2h1.csv` by the main
session (Spearman 0.836 / 0.883, round vs ribbon 0.999, ratio vs gas +0.65, the rank movers and the window
deltas all reproduce). 33 runs × 508 analysed frames = 16,764 frames. Figures, tables and scripts are in
`docs/notes/2026-10-13_area_vs_volume_and_window/` (the 171 MB of packed per-frame masks were left in the
session's scratch folder: regenerate with `scripts/run_all.py` + `scripts/vol_all.py`, ~45 min on the Mac).

**In one paragraph.** Area and volume rank the runs much the same (ρ 0.88 on the flow-controlled runs, no
effect changes sign), but volume is ~4× smaller in scale, doubles the gas effect, and is 3× noisier.
Separately, drops on the window inflate un-atomised liquid in 8 runs, by up to 7 points of atomised
fraction (C9), through two different routes; a volume measure is ~10× more sensitive to them, so any
window fix has to come before any volume response.

## Gate

- The masks were rebuilt with `classical_liquid.measure_frame` itself, unchanged. `hysteresis` and
  `model_masks` were wrapped to capture their outputs. Arguments came from each run's
  `classical_summary.json` provenance: seed 0.70, ceiling 0.95, min area 20, cover 0.5, max extent
  100, score 0.30, sharpness rule on, focus_max 0.70, split 40 µm, robust core.
- **`droplet_px` and `total_liquid_px` match `classical_per_frame.csv` exactly on 16,764 / 16,764
  frames.** The pooled fraction equals `rsm_results.csv` `af` to 1e-15 on every run.

## F2: area vs volume

Method:
- **Droplets:** sphere from the area-equivalent diameter of each connected component of the numerator
  mask.
- **Un-atomised pieces:** skeleton slicing, chord = 2√(R² − (R − e)²), where e = edt − 0.5 and
  R = edt − 0.5 at the nearest skeleton pixel of the same piece. Holes are filled for the geometry,
  because a droplet inside a blob is cut out of the un-atomised mask and leaves a hole.
- **Ribbon bound:** chord = R.
- **Out-of-focus model-only pieces:** treated the same way.
- **Primary numbers use all 508 frames** (computed from the saved masks). The 30-frame sample is too
  noisy for volume: sample vs all-frame volume Spearman is 0.82 (all runs) and 0.65 (orifice ≥ 0.8).

**Spearman, area vs volume (all frames):**

| set | round | ribbon |
|---|---|---|
| all 33 | +0.84 | +0.82 |
| orifice ≥ 0.8 mm (23) | +0.88 | +0.87 |
| orifice ≥ 0.8, excl. 0 rpm (22) | +0.88 | +0.87 |

- Round vs ribbon: +0.999. The cross-section assumption changes the scale (ribbon ≈ 1.6 × round in
  volume fraction), not the order.
- With window pixels (P20, below) removed from both measures: +0.70 (all) and +0.82 (FC). With the
  mean-T fix (30-frame sample): +0.86 and +0.85. Window blobs depress both measures in the same runs,
  which inflates the raw correlation.

**Scale:**
- Volume fraction ≈ 0.27 × area fraction on the FC runs (median ratio; range 0.08–0.33). The 0.5 mm
  runs sit at a median of 0.15 (0.05–0.38).
- Depth carried per pixel: droplets about 50 µm (29–56); un-atomised pieces 235 µm (median), 171–695 µm
  FC, 180–764 µm on 0.5 mm.
- The ratio is set almost entirely by the un-atomised depth (Spearman −0.98).

**Rank movers** (rank by area → rank by volume, round):
- All 33:
  - C1 (0.5 mm, 11k/900/5000): 4 → 18
  - C2 (0.5 mm centre): 7 → 21
  - C24 (1.8 mm, 11k/900/3000): 21 → 9
  - C23: 24 → 16
  - C27 (0.8 mm): 3 → 11
  - C4: 15 → 23
  - C10r4: 12 → 5
  - Mean |Δrank| is 3.8.
- FC (23):
  - C27: 1 → 9
  - C24: 15 → 7
  - C10r4: 8 → 3
  - C14: 6 → 11
  - Mean |Δrank| is 2.3.
- The 0.5 mm runs fall because their un-atomised pieces are thick (340–760 µm).

**Top 5, FC runs:**

| by area | by volume (round) |
|---|---|
| C27 (9k/500/4000/0.8) 20.2% | C11 (11k/500/4000/1.2) 6.4% |
| C11 (11k/500/4000/1.2) 20.0% | C13 (9k/100/4000/1.2) 6.3% |
| C16 (9k/500/3000/1.2) 19.6% | C10r4 (centre, 1.2) 5.9% |
| C15 (9k/0/4000/1.2) 19.2% | C16 (9k/500/3000/1.2) 5.8% |
| C13 (9k/100/4000/1.2) 19.0% | C15 (9k/0/4000/1.2) 5.6% |

- Four of five are shared; C27 (the 0.8 mm check) drops out.
- All 33: C7 and C8 (0.5 mm, 3000 feed) stay first and second under both measures.

**Does the ratio track the factors?** Spearman:

| factor | FC runs | all 33 |
|---|---|---|
| gas | **+0.65** (p 0.001) | +0.28 |
| orifice | −0.35 (p 0.10) | +0.29 |
| feed | −0.11 | −0.22 |
| rpm | −0.09 | +0.13 |

More gas gives thinner un-atomised pieces, so the volume measure amplifies the gas effect.

**Factor picture, FC runs:** linear fit on 22 runs (0 rpm control excluded). Factors are coded −1..+1
over their FC range. The coefficient is half the low-to-high change, as a percentage of the response
mean (t in brackets).

| response | R² | gas | rpm | feed | orifice |
|---|---|---|---|---|---|
| area (all frames) | 0.88 | +16% (5.3) | +6.6% (2.1) | +5.9% (1.9) | −31% (−9.7) |
| volume, round | 0.77 | +34% (5.1) | +5.9% (0.9) | +2.5% (0.4) | −39% (−5.6) |
| volume, ribbon | 0.79 | +34% (5.3) | +5.4% (0.9) | +2.0% (0.3) | −38% (−5.8) |
| area, P20 window removed | 0.93 | +15% (7.8) | +3.7% (1.9) | −0.2% (−0.1) | −26% (−12.9) |
| volume, P20 window removed | 0.83 | +35% (6.9) | −1.9% (−0.4) | −6.9% (−1.4) | −30% (−5.7) |

- **The signs do not change.**
- Under volume, the gas effect doubles relative to the mean.
- The orifice effect stays about the same.
- rpm and feed lose what significance they had: t falls from about 2 to below 1. The volume measure
  is noisier, with a median 95% CI half-width of 24% of the value against 8% for area. 44% of FC
  run pairs are separated by volume against 65% by area.
- Main-effect means show the same picture. Gas 7k / 9k / 11k is 66 / 114 / 98% of the mean by area
  and 44 / 118 / 110% by volume. The levels are unbalanced across the blocks, so read the fit, not the
  means.

**Cross-checks:**
- **Droplets, Daves slicing vs sphere: 0.85** (range 0.83–0.93 across runs). That is not within a few
  per cent, but the reason is geometric:
  - Daves on a 2D ellipse gives a prolate spheroid, so Daves / sphere = √(b/a).
  - Against sphere × √(b/a), Daves agrees to 0.985.
  - On near-round droplets (aspect ≤ 1.15) the ratio is 0.944.
  - Sphere-from-area overstates droplet volume by about 15% for elongated droplets. The bias is nearly
    uniform across runs (SD 0.02), so the ranking is unaffected.
- **Compact un-atomised pieces:** Daves gives 1.34× (median; 1.16–1.98) the skeleton-round volume.
  Skeleton slicing reads low on blocky blobs (a synthetic square gives 0.84 of Daves). Synthetic
  tubes ≥ 10 px wide come out within ±10%. Thin even-width threads (2–4 px) read up to 35% low.
  Absolute un-atomised volume is uncertain by about ±40%.
- **Out-of-focus model-only pieces** carry 12% of un-atomised volume on average. Excluding C20 and C6,
  they carry 3–21%. In C20 they carry 96%, and in C6 60%: those two are window artefacts (H1 below).

## H1: window and lens drops

Two different mechanisms, which mostly affect different runs.

**A. A drop lands on the window during the run.**
- It is absent from the first half, then present in about 100% of frames. Because it is in fewer than
  50% of the background frames, it is not in the median, so the classical pass counts it as liquid in
  every frame after it lands.
- Runs and landing points (fraction of the run elapsed):

  | run | lands at |
  |---|---|
  | C9 | ~50% |
  | C21 | ~55% |
  | C2r2 | ~45% |
  | C4 | ~60% |
  | C10r2 | ~60% |

- The persistence maps show compact round blobs, not spray (`persistence_all_runs.png`).

**B. A drop sits in the median all run (C20, C6).**
- It divides out of T. It re-enters only through the model:
  - The model runs on the un-normalised frame and detects the drop.
  - A static object has T ≈ 1, so it always passes the "out of focus" test (T_min > 0.70).
  - Its whole model mask is then unioned into the denominator.
- In C20:
  - The drop is a 3.6 mm² blob at x 1380, y 1006.
  - It is detected (filament or blob class) in 507 / 508 frames, at score ≥ 0.30 in 315.
  - It is counted (≥ 50% covered) in 124 frames (24%), spread evenly across the run (10–15 per tenth
    of the run).
  - The counted piece sits at the blob position ±13 px.
  - T in the blob core is 0.998 when counted and 0.997 when not. Nothing about the blob changes.
  - Raw intensity drifts −5% over the run, and so does the surround (−3%). That is illumination, not
    growth.
  - In frame 0172 it enters as blob class, score 0.65, T_min 0.756, 49,593 px.
  - It accounts for 41% of C20's un-atomised pixels over the run.
- So "a static object divides out" holds for the classical pass but not for the model's out-of-focus
  union.

**Effect on the atomised fraction** (points; window pixels removed from numerator and denominator):

| run | af | P10 | P20 | P40 | bg < 70% | mean-T rule* |
|---|---|---|---|---|---|---|
| C9 (0.5) | 8.84 | +7.5 | **+7.2** | +5.1 | 0.0 | 0.0 |
| C21 (1.8) | 10.81 | +4.2 | **+4.0** | +1.9 | 0.0 | 0.0 |
| C2r2 (0.5) | 15.51 | +3.7 | **+3.5** | +2.3 | +0.7 | 0.0 |
| C26 (1.8) | 8.18 | +3.5 | **+3.1** | +2.2 | +1.1 | +0.8 |
| C20 (1.8) | 5.96 | +4.2 | **+2.8** | 0.0 | +2.2 | **+9.5** |
| C6 (0.5) | 14.41 | +4.6 | 0.0 | 0.0 | **+4.1** | **+4.1** |
| C4 (0.5) | 17.00 | +1.9 | +1.8 | 0.0 | +0.1 | 0.0 |
| C10r2 (1.2) | 16.53 | +2.1 | +1.6 | 0.0 | 0.0 | 0.0 |
| C23 (1.8) | 13.81 | +0.6 | +0.6 | 0.0 | 0.0 | 0.0 |
| C17 (1.2) | 15.64 | 0.0 | 0.0 | 0.0 | +0.2 | +0.5 |

\* Drop out-of-focus non-droplet detections whose mean T in the mask is ≥ 0.97: nothing left after
background division. Estimated on the 30-frame sample. Real out-of-focus liquid sits at mean T
0.70–0.95 (checked on 5 runs). Thresholds of 0.95 and 0.97 give the same deltas.

- **Window area** (P20): 0.16–1.80% of the frame in the 8 affected runs, and 0 in the other 25.
- **Share of the run's liquid area in window pixels** (P20): 5–46% in those 8 runs. C9 is highest at
  46%.
- **C20 under the mean-T rule:** the fraction goes from 5.6 to 15.1% on the sample. 63% of its sampled
  denominator is static-object model mask.
- **Ranking:**
  - Spearman of af vs af without the window: P20 0.946 (all), 0.985 (FC); DARK70 0.975 / 1.000;
    mean-T rule 0.966 (sample).
  - Big moves: C9 29 → 19 and C2r2 20 → 9 under P20; C6 22 → 11 under DARK70; C20 rises from the
    lowest non-0.5 mm run to mid-pack under the mean-T rule.
- **The definitions miss things or overreach:**
  - P10 also flags real dripping streams in the no-spray runs C3 and C5 (6.1% and 3.8% of the frame).
    P20 and above do not.
  - Persistence misses mechanism B when the drop is counted in fewer than 20% of frames (C6).
  - The dark-background definition misses mechanism A entirely.
- **Volume is about 10× more sensitive to window drops than area.** A 2 mm drop gets a depth of about
  1–2 mm:
  - C20 volume fraction: 0.47% → 1.43% with P20, and 0.35% → 7.0% (sample) with the mean-T rule.
  - Any volume response has to come after the window fix.

**Worst runs: C20, C9, C6, C21, C2r2, C26.** C20 and C6 are mechanism B; C9, C21, C2r2 and C4 are A;
C26 is mixed (counted in 80–100% of frames from the start).

## Cost of a liquid-stage re-run (F3 / H2)

- **Windows, actual** (`classical_summary` elapsed): 55.7 s per run, 0.110 s/frame, 31 min for the 33
  runs.
- **Mac:**
  - `measure_frame` compute 0.036 s/frame.
  - Reading from the LaCie is the bottleneck: about 32 MB/s whatever the parallelism, 0.15 s/frame for
    one process. This full pass took 45 min with 4 processes.
- **Volume add-on** (skeleton + EDT per piece, unoptimised Python): 0.33 s/frame, about 170 s per run
  in one process. That is about 1.6 h for the day in one process, or 10–15 min across 8–10 processes.
- **The mean-T rule** costs nothing measurable: one mean per out-of-focus detection.
- **A persistence mask** needs a second pass over the per-frame masks. Hold them packed (0.3 MB/frame)
  or re-read the frames.

## For Ben to decide

1. **Volume vs area.**
   - The ranking holds broadly: ρ 0.88 on FC, and the same signs.
   - What changes: the gas effect doubles relative to the mean; rpm and feed drop below noise; C27 and
     the 0.5 mm corners lose rank.
   - The volume number is 3× noisier and its scale is model-dependent (round vs ribbon ×1.6; Daves vs
     skeleton ×1.3 on blobs).
   - Option: keep area as the headline and report volume as a secondary response after the window fix.
2. **Window fix (H2), cheapest first:**
   - **(a)** The mean-T rule in `model_masks`, for mechanism B. One condition, then a version bump.
   - **(b)** P20 persistence or a rolling background, for mechanism A.
   - Both need the liquid stage re-run; F3 can share that run.
   - Also wipe the window between runs; mechanism A is drops landing mid-run.

## Assumptions and caveats

- Droplet volume is per connected component of the numerator union, not per detection. Touching
  droplets merge into one sphere, a small overestimate.
- The nearest skeleton pixel is Euclidean within the same piece, not geodesic. e is capped at R.
- Out-of-focus pieces use the model's mask, which reads wide. These are the least certain volumes.
- Frame bootstrap CIs treat frames as independent, so they are optimistic at low GLR.
- The mean-T rule was tested on the 30-frame sample only. Its threshold was set from 5 runs.

## Files (`docs/notes/2026-10-13_area_vs_volume_and_window/`)

- `per_run_f2h1.csv`: all per-run numbers (the `_all` columns are all 508 frames; the unsuffixed volume
  columns are the 30-frame sample).
- `per_run_meanT_fix.csv`, `c20_blob_per_frame_142150.csv`, `stats_report.txt` (full printout).
- Figures: `fig1_area_vs_volume.png`, `fig2_ratio_vs_factors.png`, `fig3_window_delta.png`,
  `persistence_all_runs.jpg`, `contact_sheet_window_P20.jpg` (C20, C9, C21, C2r2; downsized).
- `scripts/`: `f2h1_core.py` (mask rebuild with `classical_liquid` + volumes), `run_all.py`, `vol_all.py`,
  `aggregate.py`, `stats_f2h1.py`, `c20_dynamics.py`, `fix_check.py`, `figs.py`, `contact.py`, `gate.py`.
  They read the LaCie (never write to it) and write their outputs NEXT TO THEMSELVES (`runs/`, ~171 MB):
  copy `scripts/` to a scratch folder before running them, never run them inside the repo.
