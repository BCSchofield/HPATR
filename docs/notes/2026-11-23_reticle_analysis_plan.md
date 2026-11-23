# Reticle (PS20) analysis: the plan (2026-11-23)

For Ben and Claude on the Mac, the afternoon after the session. Read this, then `docs/STATUS.md` (the 12:05 entry)
and `docs/notes/2026-11-23_reticle_session_prep.md` ("Found at the rig"). **Phase-gated: do one phase, report, stop
for Ben's go.** Nothing here touches the captures; every output goes to the analysis folder below.

## The goal

Optics profile v2 for the current lens, for the new box's runs before January:
- the defocus look-up table's **top end** from the chrome dots (79 → 1792 µm), replacing the 2-bead 76.39 µm row
  that every larger size now reuses;
- the **scale** from the dot array;
- an answer to **why chrome and beads read different blur** (below), because that decides how dot rows go into a
  table indexed by the χ measured on droplets.

**Not in scope:**
- the small end, which stays with the beads (37.36 µm, 108 beads; 56.28 µm, 31 beads);
- re-measuring existing runs (Ben, 2026-11-23);
- a whole-column model of the merged small dots (decided against: nothing to check it on).

## The data

**Captures:** `/Volumes/LaCie/Calibration/Imaging Work/2026/11/23/` (on Windows: `E:\...`). There are 20 static GUI_Clean
runs. Notes are in each `run_summary.xlsx`, one `.cine` in `shadowgraph/raw/CINE/`:
- 59 frames, 390 fps, 4 µs, 2048 × 1152;
- auto exposure off;
- background 1376–1378 counts, dots ~50;
- frame-to-frame flicker ≤ 0.05 %.

| Run folder (`…_0sccm_norpm_0sps_or2_bh0.5`) | Notes | Quick-look χ, 1792 µm dot (µm) | Its diameter (µm) | Its centre (px) |
|---|---|---|---|---|
| 113042 | RETICLE z-6.00 | 47.8 | 1796.5 | 791.7, 215.3 |
| 113521 | RETICLE z-5.00 | 40.7 | 1797.1 | 790.9, 215.0 |
| 113614 | RETICLE z-4.00 | 33.6 | 1797.4 | 790.1, 214.7 |
| 113654 | RETICLE z-3.00 | 26.6 | 1797.6 | 789.4, 214.3 |
| 113741 | RETICLE z-2.00 | 20.1 | 1797.1 | 788.4, 213.9 |
| 113817 | RETICLE z-1.50 | 17.0 | 1796.6 | 788.1, 213.8 |
| 113854 | RETICLE z-1.00 | 14.2 | 1795.8 | 787.8, 213.6 |
| 113933 | RETICLE z-0.50 | 11.8 | 1794.6 | 787.5, 213.6 |
| 114013 | RETICLE z-0.25 | 11.0 | 1794.1 | 787.3, 213.4 |
| 114109 | RETICLE z+0.00 | 11.1 | 1794.1 | 787.0, 213.4 |
| 114154 | RETICLE z+0.25 | 11.8 | 1794.8 | 787.0, 213.2 |
| 114243 | RETICLE z+0.50 | 12.7 | 1795.7 | 786.7, 213.2 |
| 114346 | RETICLE z+1.00 | 15.1 | 1796.9 | 786.4, 213.1 |
| 114506 | RETICLE z+1.50 | 17.9 | 1797.7 | 786.0, 212.9 |
| 114612 | RETICLE z+2.00 | 20.7 | 1798.2 | 785.5, 212.8 |
| 114810 | RETICLE z+3.00 | 26.8 | 1798.6 | 784.7, 212.4 |
| 114856 | RETICLE z+4.00 | 33.4 | 1798.6 | 783.9, 212.0 |
| 114946 | RETICLE z+5.00 | 40.2 | 1798.3 | 783.2, 211.7 |
| 115033 | RETICLE z+6.00 | 47.4 | 1797.7 | 782.4, 211.3 |
| 115621 | RETICLE array c | n/a | n/a | n/a |

- The quick look is `focus_edge.disc_edge` on 12 frames averaged, at 10 µm/px. It is not the estimator the table
  uses.
- **z** is set by counting dial turns (0.5 mm per turn) from focus found by eye with the meter, after taking up the
  backlash at −6.5. The dial has no reading.
- **χ(z) fits** √(χ0² + (k(z − zf))²) with χ0 11.9 µm, k 7.97 before focus and 7.59 after (µm/mm), zf −0.10 mm,
  rms 0.6 µm. It is smooth and symmetric, so no turn was miscounted.
- **The image drifts sideways** 0.78 px/mm in x and 0.33 px/mm in y with z: the stage's axis is ~0.5° off the
  optical axis. Over ±6 mm that's ±4.7 px, **more than `blur.locate`'s RECENTRE_PX = 3**, so positions must be
  carried per capture (Phase 1).
- **Telecentric:** the diameter is 1796.5 at −6 and 1797.7 at +6 (0.07 %).
- **The frame** (one patch for the whole series):
  - the √2 dot column, 2534 µm (cut by the top edge), then 1792 µm whole at (787, 213), down to the merged tip;
  - a ruler at each side (1 mm ticks), the concentric line squares (1–5) with a crosshair;
  - a large filled chrome square and a grey (part-transmitting) rectangle along the bottom edge, ~1 mm below the
    column tip;
  - sharp dust specks everywhere, on the slide; they don't come off.
- **The array** is a separate patch (R20): 11 × 11 dots of 250 µm at 500 µm pitch (5 × 5 mm), beside a chrome block
  holding the clear-square series.
- **The dots' layout:** each centre sits one larger-dot diameter below the last, so the gap is 0.146 × the larger
  dot (46 µm at 317→224, 16 at 112→79, 3 at 20→14). At focus everything ≤ 56 µm merges.

**Not recorded** (Ben's calls): a background capture, a z0 repeat, the array corners, the wall offcut. The
consequences are noted where they matter.

**The analysis folder:** `/Volumes/LaCie/Calibration/Imaging Work/analysis/reticle_2026-11-23/`.

**Interpreter (Mac):** `/Users/benschofield/anaconda3/envs/phantom/bin/python3`. `bead_calibration.py` imports
`cine_reader`; check it imports in `phantom` first. If it doesn't, `pip install` it there; ask Ben before installing
anything.

## The big question: why the blur differs

| | χ0 (µm) | k (µm/mm) |
|---|---|---|
| Beads (optics profile v1, `blur.edge_sizes` Blaisot χ, mixed sandwich 2026-10-15) | 13.15 | 9.57 |
| Chrome 1792 µm dot (quick look, `focus_edge` σ fit) | 11.9 | ~7.8 |

There are three explanations, each with a test:
1. **The estimator.** `focus_edge` fits σ of an erf edge (χ = 2σ); the table's χ is Blaisot's √2 Δr / p_r(C0) from
   the 0.25 / 0.61 / 0.77 level radii. Run the same `blur.edge_sizes` on the dots (Phase 3). If k comes out ~9.6, it
   was only the estimator.
2. **The object.** A glass sphere refracts and has a bright centre; a chrome disc is a clean opaque edge. Test:
   compare at the same z:
   - the **158 µm dot** with the **155.8 µm falling beads** (χ per bead, single frames, 2026-10-15/16);
   - the **79.2 µm dot** (side arcs) with the 2 static 76.39 µm beads.
3. **The depth scale.** Today z is counted in turns (0.5 mm/turn, Ben). Find out how z was set on the bead day
   (micrometer reading? the same stage?). A 20 % pitch difference would give exactly this. Ask Ben; it can't be
   inferred from the images.

**How the dot rows go into the table depends on the answer:**
- **(1):** directly, by χ.
- **(2):** re-index through depth. Take Δ_dot(s, z) and χ_bead(z) from both fits and form Δ(s, χ_bead). This needs
  the two days' z scales to agree, so settle (3) first.
- **(3):** correct z, then decide between (1) and (2).

## The phases

### Phase 0: targets and the slide's geometry (no code)
- **`targets.json`** (`Calibration/Imaging Work/targets.json`), reticle block:
  - `"arrived": true`;
  - `dots_um`: the whole column as 3.5 × √2ⁿ, at least 79.2 … 2534, **nominal until the certificate's values are
    in** (Ben: photo of the certificate);
  - the array `dot_um` 250 and `pitch_um` 500 are already there;
  - add the layout: `"column_spacing": "centre to centre = the larger dot's diameter"`.
- **Ben:** does he have the certificate? What tolerance does it give for the large dots and for the array pitch?
- **Done when:** targets.json has the column, and Ben has said where the certificate values come from.

### Phase 1: find and identify the column dots in each capture
- **Reference: R10** (`114109`, z+0.00). Average 40 frames (`average_frames`).
- **Find the column:**
  - Take the dark objects in a band around the column's axis (the 1792 µm dot's x ± 150 px).
  - Fit the axis (a line through the centres; it may be slightly tilted).
  - Identify by order: the largest whole one is 1792, then each next is /√2. Check each centre is one
    larger-diameter below the last (±2 px), and each at-focus half-level diameter against nominal (±5 %).
  - Dots that fail are reported, not used. Expect 1792 … ~79 clean; the merged tip is dropped.
- **Carry positions through z:**
  - Measure the 1792 µm dot's centre in every capture (`focus_edge.disc_edge`, as in the quick look, or
    `blur.locate` with a wider search).
  - Shift every dot by that capture's offset.
  - Never rely on RECENTRE_PX alone: the drift is up to ±4.7 px.
- **The mask of everything else:** from R10, threshold T < 0.9 and remove the identified dots. That leaves the
  rulers, line squares, crosshair, the 2534 dot, the bottom square and rectangle, text and dust. Dilate per capture
  by ~2χ(z), from the 1792 dot's χ.
- **Output:** `column_dots.csv` (id, nominal_um, cx, cy at z0, measured d at focus); a PNG of R10 with the identified
  dots ringed and the mask shaded.
- **Done when:** every dot from 1792 down to the smallest clean one is identified, with its position in all 19
  captures, and the PNG looks right to Ben.

### Phase 2: the background
- **Why the current one fails:** `estimate_background` (101 px median, then a masked Gaussian average) assumes
  sparse objects far smaller than 101 px. Here the 1792 / 1267 µm dots are 179 / 127 px, and the bottom square is
  hundreds. So T would be wrong around the column.
- **New:**
  - Take the background from the pixels outside the Phase 1 mask *and* outside all column dots (dilated by ~3χ).
  - Fit a smooth surface: the normalised Gaussian average already in `estimate_background` pass (2), with σ ~40 px,
    or a low-order 2-D polynomial, whichever leaves the flatter residual on clear glass.
  - The backlight doesn't change between captures (1376–1378 counts), so one surface per capture is plenty.
- **Check:** T on clear glass reads 1.000 ± 0.005 across the frame, including between the column's big dots. Dust
  specks are excluded by the mask (T < 0.9 at R10; also add specks that are T < 0.97 and smaller than 5 px).
- **Output:** a T map PNG for R10 and R01, and the clear-glass T histogram.
- **Done when:** clear glass is flat to ±0.5 % everywhere the column dots' edges are measured.

### Phase 3: measure each dot at each depth, the same way as the beads
- **Per dot, per capture:** `bead_calibration.measure_at` (which calls `blur.locate` and `blur.edge_sizes`), at the
  carried position, with `blank` set to the mask plus the other column dots. Do this on the new T.
- **The facing sides are contaminated:** a neighbour's blur tail is in this dot's pixels, not only in its own,
  so blanking the neighbour's pixels doesn't remove it. So add a **side-arc variant**:
  - the level radii r_l measured only along azimuths within ±45° of perpendicular to the column axis (left and
    right arcs);
  - d_l = 2 r_l, with Blaisot χ and d_blaisot from those radii exactly as `edge_sizes` does.
  - Put it in `blur.py` as `edge_sizes(..., sectors=...)` (default: full circle, unchanged). Every existing caller
    keeps its behaviour; the beads' numbers mustn't move. Re-run the 2026-10-15 bead analysis and diff
    `beads_through_focus.csv`.
- **Validity:**
  - A dot's side-arc value counts at a depth while d ≥ 1.5 χ(z).
  - Its full-circle value counts while the gap to each neighbour ≥ 2 χ(z).
  - Report both, with the flag.
- **Cross-check:** where both are valid (big dots near focus), side-arc and full-circle d_l0.50 and χ must agree
  within 0.5 %. If they don't, the side-arc variant is wrong; stop and report.
- **Output:** `reticle_through_focus.csv` in the **same columns as `beads_through_focus.csv`**, plus `dot`, `nominal_um`,
  `method` (full / side) and `valid`, so `sizer_calibration.py` can read it as it reads beads.
- **Then answer the big question:**
  - χ(z) per dot with `sizer_calibration`'s hyperbola fit (k each side of focus);
  - compare with the beads' 13.15 / 9.57 and the quick look's 11.9 / 7.8;
  - the 158-dot / 155.8-bead and 79.2-dot / 76.39-bead comparisons at matched z or χ.
- **Done when:** the CSV is written, the cross-check passes, and the blur question has a stated answer (or a
  stated next test, e.g. Ben re-measuring the stage pitch).

### Phase 4: scale and distortion
- **The array (R20, `115621`):**
  - Centroid all 121 dots (the dark-blob centres, then `blur.locate` re-centring).
  - Fit a lattice: an affine fit (µm/px in x and y, rotation, shear) plus one radial distortion term about the
    frame centre.
  - Report µm/px against 10.0, x against y, and the residuals.
  - `bead_calibration.array_scale` (median nearest-neighbour spacing, by quadrant) is a quick check, but it assumes
    the array fills the frame. Here it's one 5 × 5 mm patch, so its quadrants are meaningless; use the fit.
- **The rulers (R10):** the left and right rulers have 1 mm ticks along y. Fit tick centres for the scale in y at
  both sides of the field, the only off-centre scale data there is.
- **Expect:** within ~0.2 % of 10.0 µm/px (the beads gave slope 1.002; the 1792 dot reads +0.12 % with the edge
  offset in it).
- **Output:** `scale.json`.
- **Done when:** one µm/px for profile v2, with its uncertainty, and a statement of what is and isn't known about
  distortion (the centre 5 mm only).

### Phase 5: the table and profile v2
- **Run** `sizer_calibration.py` on the bead analysis folder(s) and the reticle folder together:
  - Rows **37.36 / 56.28** come from the beads.
  - Rows from **79.2** (or **112**, if 79.2's side arcs fail) up to **1792** come from the dots.
  - The 2-bead 76.39 row is dropped if the 79.2 dot row is good.
  - The dot rows are indexed according to the answer to the big question.
  - `sizer_calibration.py` takes bead CSVs today; it needs a small change to also accept `reticle_through_focus.csv`
    (and the `nominal_um` column).
- **Check against the falling beads** (98.1, 155.8), which never build the table: the table must size them within
  ±5 % up to χ_max (v1: +4.7 %).
- **Write profile v2:**
  - a NEW file, `config/optics/lens1_2026-11.json`, `valid_from` 2026-11-23, `version` 2, with the same
    `um_per_px` unless Phase 4 says otherwise;
  - `optics.py` picks a profile by the capture's date, so runs from 2026-11-23 on use v2 and older ones stay on v1;
  - don't edit `lens1_2026-10.json`.
- **Done when:** profile v2 is written, the falling-bead check passes, and the report (`report.md` in the
  analysis folder) is read by Ben.

## Known gaps and risks
- **No wall in the light path.** The runs go through the new box's 5 mm wall; this calibration didn't. The lens is
  telecentric, so the scale is safe, but if the wall adds blur, droplets read higher χ than the table expects. One
  capture of the column at focus through an offcut settles it; flag it in the report until done.
- **No drift check** (no z0 repeat). The 20 minutes were stable (background ±1 count, positions smooth), so it's
  probably negligible.
- **Distortion** is known only over the central 5 × 5 mm.
- **Nominal sizes** until the certificate is in.
- **The square series** (clear squares in chrome, beside the array) isn't used; it's an option for shape work later.

## For January (the 3× lens)
Same column, same method. At ~3.3 µm/px the 14–56 µm dots are measurable near focus on their side arcs (each while
χ ≲ 2/3 of its diameter). The small end at large χ still needs isolated targets: certified 20–25 µm beads, or a
reticle with spaced dots. The field is ~6.8 × 3.8 mm: turn the slide so the column runs along the long side.
Record a background row and the wall check that time.
