# Velocity capture plan

2026-10-13. Builds on the B2 note (`docs/notes/2026-10-13_droplet_rate_investigation/b2/B2_velocity_feasibility.md`;
its scripts are in `.../b2/scripts/`). Nothing here has been run. Numbers marked **est.** are estimates and
must be checked on the rig or in PCC.

> **Check first (review note):** on many high-speed CMOS sensors, Phantoms included, the frame rate is set
> mainly by the number of ROWS, not by the width. If PCC shows that, the unrotated 256 × 1152 window will
> not reach 10 kfps, and the camera must be **rotated 90°** so the flow runs along the rows. Then type a
> short, wide window (e.g. 1152 × 128–256) and read its rate off PCC. Do the PCC check in §5 step 1 before
> planning the rig day around either orientation.

## 0. Why

The count response, "in-focus droplets per frame", is a concentration: production rate × residence
time in the field.

- The mass balance puts the liquid at 4–8 m/s, rising in proportion to gas flow.
- The field is 11.52 mm long along the flow, so a droplet spends only 1.4–2.8 ms in it. A faster
  spray reads lower for the same production rate.
- A flux (rate) response needs the axial velocity per condition.
- B2 showed the 390 fps cines cannot supply it. Frames are 2.56 ms apart, so no droplet appears in
  two frames. The 4 µs blur only bounds the velocity of detected droplets at ≤ ~4 m/s.

So velocity needs its own capture.

## 1. Step 1: exposure series (no hardware change, ~20 min)

**Settings.**

- Condition: 1.2 mm, 9000 sccm, 500 rpm, feed 4000 (the CCD centre).
- Camera as today: 2048 × 1152, 390 fps, pre-trigger 0, post-trigger 2 s (780 frames, 2.8 GB).
  "Run AI analysis" off.
- Exposures: 1, 4, 16 and 40 µs, one short run each. Start Experiment will flag the non-standard
  exposure; choose "Keep mine".
- Backlight: keep the live-view background at ~800–2500 counts (12-bit) for each exposure. At 1 µs
  that probably means maximum LED (record the level). At 16 µs and 40 µs, dim the LED rather than
  touch the aperture, which sets the DOF.
- Record the LED setting and the background level in Notes.

**What motion would look like.** Streak length is L = v × t_exp / 10 µm. At 4–8 m/s that gives:

| t_exp | 1 µs | 4 µs | 16 µs | 40 µs |
|---|---|---|---|---|
| streak L (px) | 0.4–0.8 | 1.6–3.2 | 6–13 | 16–32 |
| contrast of a 40 µm (4 px) droplet, ≈ d / (d + L) | ~0.85 | ~0.6 | ~0.3 | ~0.15 |

**Outcomes and the decision each feeds.**

| outcome | meaning | decision |
|---|---|---|
| along-flow elongation grows ∝ t_exp (clear 6–13 px streaks at 16 µs) | it is motion; streak length gives the in-plane speed per droplet | set Step 2's Δt from the measured median v: aim for 30–60 px between frames |
| in-focus count per frame at 1 µs clearly above 4 µs (beyond frame-to-frame scatter) | 4 µs is already losing fast droplets | today's counts are velocity-biased; consider 1–2 µs as the sizing standard (light permitting) |
| no elongation growth even at 40 µs | v ≲ 0.5 m/s, which contradicts the mass balance | re-check the mass balance; Step 2 could then use today's frame at its maximum rate (~1,360 fps, est.) |

Streak velocimetry from the 16 µs frames could on its own give a mean speed per condition. It is
biased against small droplets, whose streaks fade, and it gives no sign. Use it as a cross-check on
Step 2, not a replacement.

**Analysis.** Reuse the B2 code: `common.segment`, `blur.droplet_measures` (D_flow = μyy − μxx and
edge widths) and `streak_profiles.measure` (L_app).

A ~60-line wrapper, `exposure_series.py`, needs writing. It should:

- read ~300 mid-cine frames per capture;
- build a 40-frame median background;
- report, per exposure: median D_flow with CI, L = √(12 [D_flow(t) − D_flow(1 µs)]),
  v = L × 10 µm / t, and in-focus count per frame.

The B2 scripts are kept in `docs/notes/2026-10-13_droplet_rate_investigation/b2/scripts/` (their frame
cache paths point at a temporary folder: adjust before re-running). Move them into
`AI/Real_Data_Code/velocity/` when the wrapper is written. Then:

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 /Users/benschofield/Documents/GitHub/HPATR/AI/Real_Data_Code/velocity/exposure_series.py --cines "<1us.cine>" "<4us.cine>" "<16us.cine>" "<40us.cine>"
```

(The script and its flags do not exist yet.)

## 2. Step 2: windowed high-fps capture

**The key fact.** The VEO-E 340L moves about 3.2 Gpx/s. That is published as 800 fps at
2560 × 1600; a retailer quotes 1541 fps at 1920 × 1080, which agrees. **est.** At constant
throughput:

- Δt = W × H / 3.2e9.
- The displacement as a fraction of the along-flow length is d / L_along = v × (across-flow px) /
  32,000.

**So the across-flow width alone sets the top speed.** For d ≤ ¼ of the along-flow length up to
20 m/s, the window must be ≤ ~400 px across the flow. A "slightly smaller" frame that keeps the full
2048 px width never helps: d / L_along stays at v / 15.6 m/s however much height you cut.

Expected speeds 2–20 m/s, 10 µm/px. Droplet blobs per frame assume today's density (~60 per full
frame; mean spacing ~200 px). Record time assumes the full 18 GB at the maximum rate.

| window W × H (typed as today) | max fps **est.** | Δt | field across × along flow (mm) | d at 2 / 5 / 10 / 20 m/s (px) | d(20 m/s) / L_along | blobs per frame | record time | verdict |
|---|---|---|---|---|---|---|---|---|
| 2048 × 1152 (today) | 390 | 2564 µs | 20.5 × 11.5 | 513 / 1282 / 2564 / 5128 | 4.5 | 59 | 13 s | no pairing (B2) |
| 2048 × 1152 at max rate | ~1,360 | 737 µs | 20.5 × 11.5 | 147 / 369 / 737 / 1475 | 1.3 | 59 | 3.7 s | ≤ ~4 m/s only |
| 1280 × 800 | ~3,100 | 320 µs | 12.8 × 8.0 | 64 / 160 / 320 / 640 | 0.8 | 26 | 3.7 s | ≤ ~6–8 m/s; needs 3-frame tracks |
| 2048 × 256 (full width, cut height) | ~6,100 | 164 µs | 20.5 × 2.6 | 33 / 82 / 164 / 328 | 1.3 | 13 | 3.7 s | ≤ ~4 m/s; no better than full frame |
| **512 × 1152 (fallback)** | ~5,400 | 184 µs (200 µs at 5,000) | 5.1 × 11.5 | 40 / 100 / 200 / 400 | 0.35 | 15 | 3.7 s | works to ~10 m/s with 2-frame tracks, 20 m/s with 3-frame |
| **256 × 1152 (recommended)** | ~10,800 | 93 µs (100 µs at 10,000) | 2.6 × 11.5 | 20 / 50 / 100 / 200 | 0.17 | 7 | 4.1 s at 10 kfps | works to 20 m/s; 2-frame tracks to ~10 m/s |
| 128 × 1152 | ~21,700 | 46 µs | 1.3 × 11.5 | 9 / 23 / 46 / 92 | 0.08 | 4 | 3.7 s | if speeds are > 20 m/s |

**Is ~5 kfps on a bigger window workable?** At 200 µs, a 5 m/s droplet moves 100 px. Three things
decide whether that pairs:

- *Ambiguity.* The chance of a wrong partner inside the search region (along-flow d ± 50 %, across
  ±0.2 d) is n × d × (0.4 d + 10), with n = 2.5e-5 px⁻². That is 0.13 at d = 100 px, 0.45 at 200 px
  and 1.7 at 400 px. Size matching (±30 %) cuts it ~3×. So 2-frame pairing is safe to d ≈ 150 px.
  Beyond that you need 3-frame constant-velocity tracks, which are safe to d ≈ spacing (~200 px).
- *Focal slab.* Assume a lateral (z) velocity ~15 % of axial. Over d = 200 px (2 mm), a droplet moves
  ~0.3 mm in z, comparable to a plausible DOF (not calibrated). Expect losses above ~150 px.
- *Window length.* 3-frame tracks need 2d inside the along-flow length.

So 5 kfps handles the expected 4–8 m/s (d = 80–160 px) with 3-frame tracking, and is marginal at
20 m/s. 10 kfps keeps everything ≤ 100 px at ≤ 10 m/s and needs no special tracking. 20–50 kfps is
not needed unless Step 1 shows speeds above 20 m/s.

**Recommend: 256 × 1152 at 10,000 fps (Δt = 100 µs), 1 µs exposure, no rotation.**

- Along-flow length, focus and position are identical to the sizing captures. Only the width is cut,
  to a 2.56 mm strip.
- In 3 s it records ~30,000 frames (13 GB). Expect thousands of droplets crossing (est. ~3,800 blobs/s
  at 6 m/s), enough for a mean and 3–4 size classes.

**Fallback: 512 × 1152 at 5,000 fps (200 µs), 1 µs.** It gives a wider strip and twice the
statistics, but needs 3-frame tracking above ~8 m/s.

**Rotate the camera?** Only if PCC shows that narrowing the width does not raise the frame rate (a
row-limited sensor). In that case rotate 90° and type the transposed window (1152 × 256): rows are
then cut, which always speeds up a CMOS readout. Rotation costs a remount, a focus and scale re-check
(dot slide or ruler at the spray plane), and the flow then runs along x. Do not rotate otherwise.

**Exposure.**

- At 1 µs, blur is 0.2 / 0.5 / 1 / 2 px at 2 / 5 / 10 / 20 m/s; at today's 4 µs it would be
  0.8 / 2 / 4 / 8 px.
- The minimum is quoted as 1 µs (VEO-E datasheet via search; check in PCC).
- If the light is too low at 1 µs, 2 µs is acceptable for velocity (≤ 4 px at 20 m/s). Blur is
  symmetric about the centroid, so the displacement stays unbiased.

**Light budget.** Background is ~800 of 4095 counts at 4 µs, so ~200 at 1 µs with the same LED.

- Pixel noise today is ~18 counts at an ~826-count background, i.e. 2.2 % in T (measured from two
  B2 frames).
- At ~200 counts, T noise becomes 4–9 %: the low end if shot-noise-limited, the high end if
  read-noise-limited.
- The T < 0.6 seed then sits 4.5–9σ below background: workable, but small droplets get noisier.

Aim for ≥ 400 counts:

1. raise the LED;
2. then use EI / gain (the GUI's `exp_index` field; check what it maps to in PCC);
3. never open the aperture.

**Keep identical to the sizing captures:** lens, focus ring, aperture, camera-to-spray distance and
camera position. **Record the stand-off distance** (orifice exit to image centre, ±1 mm) in Notes. It
is §13 item 11, still open, and it is needed to compare with any jet or literature velocity.

## 3. Which conditions

**Short answer to "do we need a high-fps video of each gas flow state?"** Not of every run.

- Velocity should depend mainly on exit velocity ~ Q_gas / A_orifice, and on P0 when the rig is
  pressure-limited. It may depend somewhat on feed.
- In the flow-controlled regime it should hardly depend on rpm.
- So: one calibration set, a fit, and the fit applied to every CCD run.

**Velocity calibration set (15 captures + the 4 exposure-series captures):**

| block | captures | Q/A, nominal gas exit (m/s) |
|---|---|---|
| 1.2 mm × gas 7000 / 9000 / 11000, feed 4000, 500 rpm | 3 | 103 / 133 / 162 |
| 0.8 mm × gas 7000 / 9000 / 11000, same | 3 | 232 / 298 / 365 |
| 1.8 mm × gas 7000 / 9000 / 11000, same | 3 | 46 / 59 / 72 |
| 1.2 mm, 9000, feed 3000 and 5000 | 2 | 133 |
| 1.2 mm, 9000, feed 4000, 900 rpm (rpm check) | 1 | 133 |
| 1.2 mm, **12,000**, feed 4000, 500 rpm (top of the rig's range, for the next design) | 1 | 177 |
| 0.5 mm, 7000 set, 900 rpm, feed 3000 (C7-like, pressure-limited, ~5,400 sccm delivered) | 1 | ~460 at delivered flow |
| 1.2 mm centre repeat at the end (drift and repeatability) | 1 | 133 |

Q/A spans 46–460 m/s (10×), which gives good leverage for v_axial = a (Q/A)^b × f(feed).

**Rig time, est.:** ~3.5 h.

- Setup: PCC rate check, focus check, stand-off: 45 min.
- Exposure series: 20 min.
- 15 captures × ~6 min (fill, start, steady, trigger, ~2 min save of ~13 GB): 90 min.
- 4 orifice swaps × ~10 min: 40 min.
- Restoring the standard capture and one reference sizing run: 20 min.

**How to use it.**

- **(a) Recommended: fit and apply.**
  - Fit v_axial (mean and per size class) against Q/A (or Q and orifice), feed and P0.
  - Apply it to every CCD run: flux index = in-focus count per frame × v_fit / 11.52 mm.
  - Log P0 and delivered flow on the velocity day and compare them with the CCD runs at the same
    settings. If they match within ~0.1 bar, the fit transfers.
- **(b) Velocity burst in every run.** Possible, but later and only if (a) shows run-to-run
  velocity scatter that the fit cannot explain (e.g. pulsing).
  - What exists: the GUI configures the camera through `PhantomCamera.configure(width, height, fps,
    exposure_us, partition_count=1, post_trigger_frames, exp_index)` (`GUI_Clean.py:1119`, pyphantom
    `cam.resolution / frame_rate / exposure / post_trigger_frames`), then `start_recording` (`:1136`),
    `trigger`, `wait_for_stored` and `save_recording(cine_index=1)` (`:1185`). Every call a second
    recording needs is already there.
  - What would have to change:
    - Sequence a second configure → arm → trigger → save after the 15 GB sizing save. Reconfiguring
      mid-save is refused by `_cam_refuse_while_saving`.
    - Restore `STANDARD_CAPTURE` afterwards.
    - Give the second cine its own folder and metadata.
    - Keep the spray running longer. Today's 36 mm of travel at feed 4000 lasts ~61 s and the 13 s
      capture already ends at ~60 s.
  - The alternative, two partitions, would halve the sizing record (13 s → 6.5 s). It is unknown
    whether partitions can differ in resolution or rate.
  - Estimate: ~1 day of GUI work plus rig testing. It also only works unrotated, i.e. only if narrow
    widths give the rate.

## 4. Analysis needed (later code)

`ptv_velocity.py`, outline:

1. **Background:** per-pixel median of ~100 frames spread across the cine; T = I / I_bg.
2. **Detection:** the pipeline's thresholds. Seed T < 0.6, grow to the half-max edge, focus gate
   core ≤ 0.70 (2.2.0), d_eq ≥ 2 px. Drop droplets touching the window edge; that matters for a
   256 px strip.
3. **Pairing:**
   - Search along +flow over d ∈ [0.5, 30] m/s × Δt, with |across| ≤ 0.2 × along + 3 px.
   - Size ratio within ±30 %.
   - Take the candidate nearest the predicted position. Do two passes: a broad prior, then the
     median velocity from pass 1.
   - Keep 3-frame tracks whose third position is within 3 px of the constant-velocity prediction.
     Velocity = central difference.
4. **Per run outputs:**
   - axial (and across) velocity distribution: mean, median, SD; per size class (the app's bins);
     track yield by size;
   - the fraction moving downstream;
   - **flux** = in-focus count per frame (from the sizing capture) × v̄_axial / L_along (11.52 mm),
     per size class and summed. Also volume flux Σ Ṅ × πd³/6, compared with Q_liq × atomised
     fraction (B1). This closes the balance up to the DOF.
5. **Validation:**
   - (i) Synthetic: real frames with droplets re-placed at a known shift and velocity spread, at the
     real density. Report bias, yield and false-pair rate. B2's `piv.synthetic_test` is the model.
   - (ii) A slow dribble capture (as C3 in B2): tracks at mm/s–cm/s with high yield, and k+2 = 2 × (k+1).
   - (iii) Physics: v rises with gas and falls with orifice size at fixed Q. The centre repeat
     agrees within ~5 %. ≥ 95 % of tracks go downstream. Step 1 streak speeds agree within their bias.

## 5. Run sheet (on the day)

1. **Before the session, in PCC (camera only):**
   - type 256 × 1152 and 512 × 1152 and note the max fps of each;
   - type 2048 × 256 and compare it with 256 × 1152, to see whether cutting the width or the height
     raises the rate;
   - check whether the window is centred or can be offset, and the minimum exposure;
   - check the live background at 1 µs with the LED at maximum.
2. Do not move the camera. Measure the stand-off: orifice exit to image centre, mm.
3. **Exposure series:** 1.2 mm, 9000, 500 rpm, 4000. Camera 2048 × 1152, 390 fps, pre 0 s, post 2 s,
   AI off. Four runs at 1, 4, 16 and 40 µs, adjusting the LED to ~800–2500 counts.
   Notes: `VEL-EXP <t>us | LED <level> | bg <counts> | standoff <mm>`.
4. **Velocity window:** 256 × 1152, 10,000 fps (or PCC's max below that), 1 µs, pre 0 s, post 3 s,
   AI off. LED at maximum, background ≥ 400 counts (else EI). Use the fallback 512 × 1152 at
   5,000 fps if PCC can't reach 10 kfps. If Step 1 shows median v > 10 m/s, use 128 × 1152.
5. **Captures**, in this order, one run each (Start Experiment → steady → Trigger → save):
   1. 1.2 mm block: 9000/500/4000 (centre) → 7000 → 11000 → 12000 → feed 3000 → feed 5000 → 900 rpm.
   2. Swap to 1.8 mm: 7000, 9000, 11000.
   3. Swap to 0.8 mm: 7000, 9000, 11000.
   4. Swap to 0.5 mm: 7000 set / 900 / 3000.
   5. Swap to 1.2 mm: centre repeat.

   Notes for each: `VEL <orifice> <sccm> <rpm> <sps> | 256x1152 <fps> 1us | LED <level> | bg <counts> | standoff <mm>`.
   Keep AI analysis off and the `VEL` tag, so these runs are never mistaken for sizing runs in
   `master_log` or the Taguchi app.
6. **Restore the standard capture** (2048 × 1152, 390 fps, 4 µs, 13 s) and the LED. Take one
   reference sizing run at the centre; its D32 and count should match the CCD centres.

## 6. Open questions

**Camera (PCC / Vision Research):**

- the real max fps at 256 × 1152, 512 × 1152 and 2048 × 256;
- whether narrowing the width raises the rate, which decides rotation;
- whether the window can be offset, which would allow a radial velocity profile from 2–3 strips;
- the minimum exposure and whether EI adds noise;
- whether the VEO-E has a frame-straddling / PIV mode;
- the Ethernet save time for a ~13 GB cine.

**Rig:**

- Backlight headroom at 1 µs: what background does maximum LED give?
- Is the LED continuous, and can its driver be modulated with ~0.5 µs pulses? The lab's Tektronix
  AFG1062 (`AFGController` in the GUI) could generate a double pulse 10–20 µs apart from the camera
  sync. That is the route to a full-field velocity in every sizing run, with no second cine.
- Calibrated DOF (`DROPLET_MEASUREMENT_METHOD.md`), needed for an absolute rather than a relative
  flux.
- The stand-off distance.
