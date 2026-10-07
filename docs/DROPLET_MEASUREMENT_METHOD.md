# Droplet measurement method: review and target design

**Written 2026-10-07** after the sizer 2.1.0 vs 2.2.0 comparison. This is the plan for making the
droplet sizes and the droplet/ligament fraction defensible as *measurements*, not just consistent
rankings. It is not started. Current state of the pipeline: `docs/STATUS.md`.

**What this is for:** (1) the fraction of the spray that is droplets vs ligaments (a Taguchi
response; ranking accuracy is enough), and (2) droplet sizes as accurately as the images allow:
D32, Dv50, size bins by number and volume.

**What this is NOT:** a reason to stall the Taguchi study. Sizer 2.1.0 is biased the same way in
every run, so it ranks conditions consistently. This plan decides whether absolute D32 and size
distributions stand up in the thesis and against the literature.

---

## Verdict

The established method for shadowgraph droplet sizing is calibrated **particle/droplet image
analysis (PDIA)**. The current pipeline lacks the one thing that makes its sizes trustworthy:
**a physical calibration of edge, focus and depth of field.** Every sizing argument so far (half-max
vs the eye, the `t_min <= 0.70` gate, the 2.2.0 sharpness rule) is the same missing calibration in
different forms. Stop tuning thresholds against eye labels (the eye draws ~30% larger than
half-max, so it is not ground truth either). Calibrate against objects of known size. ML detects
and classifies; it never defines a size.

---

## What is wrong, ranked

### 1. No calibration of edge and focus (biggest)

Whether a blurred droplet counts, and where its edge is, are set by convention (half-max) or by
eye. A **dot reticle** (opaque chrome dots of known diameters on glass) traversed through focus on
a micrometer stage measures, per dot size:

- the edge threshold that returns the true diameter, which settles half-max vs eye;
- how a focus parameter (edge gradient, PSF width) decays with defocus, which gives a calibrated
  acceptance test to replace `t_min <= 0.70` and the eye-fitted 2.2.0 rule;
- the depth of field as a function of droplet size (see 2).

Cost: a few hundred pounds of hardware and about a day. Highest value per hour on this list.
Setup is in "Calibration: what to buy and how to run it" below.

### 2. Size-dependent depth of field over-counts big droplets

A large droplet stays acceptably sharp over a deeper slab of spray than a small one, so it is
accepted from a larger volume. Every distribution produced so far over-counts large droplets
relative to small ones, which biases D32 and the size bins upward. The standard correction weights
each accepted droplet by `1 / DOF(d)`, from the calibration.

The frame border (and our 800 px tile seams) do the same: a large droplet is more likely to be cut,
and cut droplets are dropped from sizing. Standard correction: weight by
`(W*H) / ((W - d)(H - d))`. Neither 2.1.0 nor 2.2.0 applies either correction.

### 3. Focus and shape are confused

The 2.2.0 rule rejects droplets for being blurred (a *measurability* question) and for being
non-round (a *what is it* question). The 2026-10-07 diagnosis showed the second dominates its
gas-flow gradient: droplets are genuinely less round at higher gas flow (unrelaxed fragments of a
viscous liquid). A sharp deformed fragment is real liquid and should be measured, not discarded.

Separate the two decisions:

- **Focus** (calibrated, item 1): is the object measurable at all?
- **Shape** (aspect ratio, solidity, skeleton): droplet / deformed fragment / ligament / blob.

Then size every class by **volume**:

- droplets and fragments as spheroids, `V = pi/6 * a * b^2` (a = major, b = minor axis), reported
  as the volume-equivalent diameter `d_v = (6V/pi)^(1/3)`;
- ligaments as `sum(pi * w(s)^2 / 4) ds` along the skeleton, `w` from the distance transform;
- lamellae / large blobs: thickness unknown, so flag as uncertain and report separately.

### 4. D32 is fragile here; report Dv50 alongside it

D32 is dominated by the largest droplets, so it swings with every decision at the droplet/blob
boundary (the 200 um ceiling moved it ~2 um; the 2.2.0 rule ~31%). Report **Dv50** (volume
median) and Dv10/Dv90/span next to D32, all with frame-bootstrap CIs. Make the droplet/blob
boundary an explicit, reported classification rule, not a side effect of a focus test.

### 5. Resolution limits small droplets, but barely matters for D32

At 10 um/px everything under ~50 um is <= 5 px and sits on the pixel lattice (2026-10-03: the sizer
cannot improve it). But droplets under 50 um carry only ~10% of droplet volume (2.1.0 size bins),
so **for D32, Dv50 and volume distributions, calibration matters far more than magnification.**

Magnification matters for number distributions and D10. If those are needed, add a second, zoomed
configuration (~2-3 um/px, long-working-distance lens, ideally **telecentric**, which keeps
magnification constant with depth and removes a depth-dependent size error). At that scale motion
blur dominates (4 us at a few m/s is several px at 3 um/px), so a pulsed backlight would likely be
needed. Keep the wide view for spray structure, the liquid fraction and large droplets.

### 6. Images measure concentration, not flux

A snapshot counts what is in the frame at an instant. Slow objects linger and are over-represented
relative to what flows through. If droplets and ligaments move at different speeds, the image
fraction is not the flow fraction, and imaging D32 is not comparable with phase Doppler (flux)
D32. Fine for ranking if consistent and stated; for absolute claims, weight by velocity. One
velocity measurement (high fps, windowed) also settles the inferred 20.5 ms decorrelation time and
bounds motion blur.

### 7. The liquid fraction depends on where the field of view is

Break-up progresses downstream. A fraction at one axial station confounds "atomises better" with
"breaks up sooner", and gas flow also changes velocity. Fix the station deliberately and record it;
ideally image 2-3 axial distances on one condition to see how sensitive the response is. A
**liquid volume fraction** (droplets as spheroids, ligaments from skeletons) is more physical than
projected area; projected area remains acceptable as a ranking response because it is consistent.

---

## Target pipeline

1. **Calibrate** per optical configuration: dot reticle through focus, plus transparent glass
   beads (silicone droplets are transparent and lens the backlight into a bright centre, so their
   edge differs from an opaque dot). Store the calibration with the run metadata; redo it whenever
   focus, aperture, lens or camera distance changes.
2. **Per frame:** background-normalise (`T = I / I_bg`), classical segmentation, per object: size
   at the calibrated threshold, focus parameter, contrast, aspect ratio, solidity, skeleton.
3. **Classify:** focus accept/reject (calibrated); shape class (droplet / fragment / ligament /
   blob). ML belongs here only: classification and splitting overlaps.
4. **Weight** each accepted object: `1 / DOF(d)` x border correction (x velocity, if measured).
5. **Report:** number- and volume-weighted size bins; D10, D32, Dv10/50/90, span; a sphericity
   distribution; liquid volume fraction in droplets / fragments / ligaments; frame-bootstrap CIs at
   a decorrelated stride.
6. **Cross-check once** against an independent instrument on a few conditions if the department
   has one (laser diffraction, e.g. Malvern Spraytec).

## Priorities

1. **Reticle calibration + DOF weighting.** Turns the sizes into measurements. Cheap.
2. **Replace "reject" with "classify by shape" and size by volume.** Mostly code, on top of what
   exists (`measure_run.measure_droplet`, `sharpness_metrics`, the skeleton prototype).
3. **One velocity measurement:** motion blur bound, decorrelation time, whether flux weighting is
   needed.
4. **Zoom optics:** only if number-based statistics or sub-50 um droplets matter to the thesis.

---

## Calibration: what to buy and how to run it

### Shopping list

| item | suggestion | why |
|---|---|---|
| Dot reticle with a range of dot sizes | **Graticules Optics PS20 "universal image analysis calibration slide"** (UK, Tonbridge; formerly Pyser-SGI). 76 x 25 x 1.5 mm soda-lime glass, evaporated chrome. Has a root-2 progression of 21 dots from 3.5 um to 3.5 mm, including **39.6, 56.0, 79.2, 112, 158, 224, 317 um**, which spans our droplet range; plus a 0.25 mm dot array (0.5 mm pitch) for checking scale and distortion across the field. Quoted accuracy 0.5 um; UKAS certificate available. Ask for a quote. | one slide covers every size we need; certificate makes it traceable for the thesis |
| Alternative / addition | Edmund Optics or Thorlabs chrome-on-glass **dot distortion targets** (fixed dot size per target, regular grid) | fills the field with one dot size: good for distortion and for many dots per frame |
| Transparent spheres, certified | **Whitehouse Scientific** (UK, now LGC) monodisperse glass microspheres, 10 um to >1000 um, certificate of traceability, sold as sets of single-dose packs. Pick ~3 sizes, e.g. near 50, 100 and 200 um. | checks the transparent-droplet edge against a certified size |
| Transparent spheres, cheap | **Cospheric** soda-lime glass microspheres in narrow ranges (e.g. 90-106 um; >90% in range) | cheaper sanity check; ranges, not monodisperse |
| Translation stage | 25 mm travel manual linear stage with a metric micrometer (e.g. Thorlabs PT1/M), plus a slide holder | moves the reticle along the optical axis in known steps |

### Setup and procedure

1. **Freeze the optics exactly as for experiments:** same lens, focus ring, aperture (f-number sets
   the depth of field, so it must not move), camera-to-spray distance, backlight intensity,
   resolution and 4 us exposure. Record them; any later change voids the calibration.
2. **Mount the reticle at the spray plane**, chrome side facing the camera, on the stage so that
   the stage moves it **along the optical axis** (towards/away from the camera). Check it is
   perpendicular to the axis: a tilted slide shows the same dot at different sharpness across the
   field (check with the 0.25 mm dot array).
3. **Background:** image a clear area of the slide (glass, no chrome) so `T = I / I_bg` includes
   the slide's own attenuation.
4. **Find best focus:** step the stage until a 112-317 um dot has the steepest edge. Call that
   z = 0. Confirm the 10 um/px scale from the 0.5 mm-pitch dot array (and look for distortion
   towards the frame corners).
5. **Traverse:** z from -5 to +5 mm; 0.1 mm steps within +/-1 mm of focus, 0.25 mm beyond. At each
   step record ~20 frames (averages out camera noise). Move laterally between the dots of the
   root-2 progression as needed so each of 39.6-317 um is imaged at every z.
6. **Beads:** the spray plane is vertical, so loose beads on a slide would fall off. Make a
   **bead sandwich**, one bead size per sandwich: lay a clean slide flat, sprinkle a sparse layer of
   beads, lower a coverslip onto them (the beads act as spacers and are clamped in place), seal the
   edges with tape or nail varnish, then stand it in the slide holder like the reticle and repeat
   steps 3-5. The beads stay in an air gap, which is what matters optically. Compare the size
   measured at the reticle-derived threshold with the certificate, and see how the bright centre of
   a transparent sphere affects the core estimate.
   - **Do not glue or embed the beads.** Glass beads in adhesive, epoxy or varnish are nearly
     index-matched (n ~1.5) and lose their edge; even a thin glue fillet changes the edge profile.
   - Optional realism check later: drop beads through the field of view from a small sieve or slot
     above it, so they fall through air at random depths, like droplets. It gives the measured size
     distribution and in-focus fraction against a known size, with real depth spread and slight
     motion.
7. **Analysis (code to write):** for each dot size and z, the transmission profile gives apparent
   diameter vs threshold, contrast, and edge width / PSF width. From those:
   - the threshold whose diameter stays correct across the in-focus range (may or may not be
     half-max; now measured, not assumed);
   - the focus parameter and its acceptance limit;
   - `DOF(d)`: the z-range over which a dot of size d is accepted and sized within e.g. 5%.
   Store as a calibration file the pipeline reads, versioned like `SIZER_VERSION`.

### Gotchas

- Chrome dots are opaque; droplets are transparent. That is why the beads matter.
- Sandwiched beads are seen through a coverslip; good enough for the edge check, not for DOF.
  The reticle traverse gives DOF; the falling-bead check confirms it.
- The reticle sits at one depth per frame; the spray fills a slab. The traverse is how DOF is
  measured, so do not skip the out-of-focus steps.
- Re-run the calibration after any optical change, and store which calibration each run used.

---

## References (starting points)

- N. Fdida and J.-B. Blaisot, "Drop size distribution measured by imaging: determination of the
  measurement volume by the calibration of the point spread function", *Meas. Sci. Technol.* 21
  (2010) 025501. The DOF / measurement-volume method this plan follows.
- J.S. Shrimpton, J.T. Kashdan, A. Whybrew, "Two-phase flow characterization by automated digital
  image analysis", Parts 1 (fundamental principles and calibration) and 2 (comparison with phase
  Doppler on a hollow-cone spray), 2003-2004. The PDIA approach: sizing defocused droplets from
  calibrated image properties. https://eprints.soton.ac.uk/64551 and https://eprints.soton.ac.uk/64553/
- J.-B. Blaisot and J. Yon published on droplet size and morphology characterisation in dense
  (diesel) sprays by image processing (INSA Rouen / CORIA, mid-2000s): relevant to ligament vs
  droplet morphology. Exact citation not yet verified.

## Related records

- `docs/STATUS.md`: the 2.1.0 / 2.2.0 results and the gas-gradient diagnosis this plan comes from.
- `docs/archive/HANDOFF_real_data_pipeline_LEGACY.md`: "2026-10-02 (late)" (free-hand vs
  half-max), "2026-10-03" (split, degeneracy, lattice), "2026-10-02 (night)" (the eye-labelled
  sharpness rule).
