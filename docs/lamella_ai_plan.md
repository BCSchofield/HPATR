# Lamella Thickness AI — Design Notes / Pre-Plan

Status: **Design agreed, not yet planned in detail or implemented.**
Purpose: capture decisions made in conversation so a detailed planning session can start from solid ground (survives context compaction).

---

## 1. Goal

Build a **fast AI model to detect liquid lamella thickness inside the nozzle exit orifice**, complementing the existing droplet/ligament detection AI.

"Lamella thickness" = the thickness of the liquid film (ring) around the central air core in the ACLR-style annular flow, measured inside the outlet channel. Reference: *Ballesteros Martínez & Gaukel (2023), Flow, Turbulence and Combustion 110:601–628* (ACLR Nozzle paper). Their method: high-speed camera images the outlet channel; a gradient/grayscale algorithm tracks the gas–liquid interface (largest intensity gradient) and measures film thickness at a mid-channel cross-section. Known limitation: optical refraction near the wall obscures thicknesses below ~0.05–0.08 mm.

We are replacing their gradient-tracking step with a learned model.

## 2. Why this is feasible

- The task reduces to **binary segmentation**: per-pixel label liquid vs gas inside the outlet channel.
- Lamella thickness is then a **geometric calculation** from the mask (occupied liquid width on a mid-channel probe line), same idea as the paper's line-integral approach.
- A lightweight segmentation model (U-Net style) is far smaller/faster than the existing Mask R-CNN droplet detector.

## 3. Key agreed decisions

| Decision | Choice | Reason |
|---|---|---|
| Model type | Lightweight binary segmentation (U-Net style), NOT Mask R-CNN | Speed; task is simpler than instance detection |
| Precision target | **Indicative, not precise** (esp. live mode) | User accepted this; batch TIFF mode is the "ground truth" analysis |
| Crop strategy | **Fixed crop** to outlet channel region before inference | Simpler/faster/reliable; fixed test-rig geometry. (Detect-then-measure rejected as over-complex.) *Open Q: confirm outlet position stability in live feed.* |
| Two run modes | (a) Live real-time, (b) Batch over recorded TIFF frames | Both share ONE inference core function (frame in → thickness out) |
| Live cadence | One frame every **0.2 s (5 fps)** | User's choice — 5 sections/sec |
| Frame handling | **Latest-frame-only slot, NOT a queue** | Critical: avoids processing stale/out-of-order frames and reporting wrong values. If inference is busy when a new frame arrives, replace the pending frame; skipping a frame is fine |
| Live overlay | Draw detected interface lines + thickness value onto the live feed frame | Only when toggle is on |
| Toggle | Single boolean flag via a **"Lamella Analysis"** button | When OFF: live feed behaves exactly as today, zero inference/overlay, zero interference with droplet detection |
| Separation | Lamella inference must NOT run during droplet detection or any other mode | Controlled purely by the flag |

## 4. Speed sanity check

- Small segmentation model on a cropped region: ~20–50 ms/frame, even on CPU.
- Budget at 5 fps = 200 ms/frame → comfortable headroom.
- Live mode is post-display indicative; 20 kHz real-time per-frame is explicitly NOT the goal.

## 5. Architecture — how it slots into existing GUI

GUI file: `src/gui/GUI_Clean.py` (PySide6, Fusion dark theme).

Existing infrastructure we can reuse (already present):
- `_live_feed_timer` — QTimer, currently 100 ms (~10 fps). Lamella mode wants 200 ms.
- `_live_feed_tick()` (≈ line 3911) — grabs one frame in a background `threading.Thread`, throttled by `_live_feed_pending` so only one grab is in flight at a time. **This is essentially the latest-frame-only pattern already.**
- `_live_feed_update(frame)` (≈ line 3929) — main-thread callback that paints the frame to the feed label.
- `_phantom_frame_to_pixmap(frame)` (≈ line 3856, static) — converts a pyphantom numpy frame to a QPixmap.

Proposed design:
- When a new live frame arrives, route the **raw numpy `frame`** to BOTH the display path AND (if lamella flag on) a lamella inference step, before it gets scaled down for display.
- Inference runs off the main thread; result (thickness + overlay) marshalled back via `QTimer.singleShot(0, self, ...)` like the existing code.
- Piggyback on the existing live-feed tick rather than adding a separate camera-grab thread — **zero extra camera calls**.

## 6. Frame quality / bit depth (investigated)

- Phantom live frame from `self.phantom.cam.get_live_image()` returns **12-bit data packed in a uint16 array** — same bit depth as recorded TIFFs.
- `_phantom_frame_to_pixmap` normalises to 8-bit uint8 only for *display*. The raw frame is available before that.
- **Open question (Phantom SDK, not answered in code):** is the live image the same full resolution as recorded frames, or a downsampled preview stream? User believes live is lower quality. If model is trained on TIFFs it may underperform on live → either train on both, or accept live = indicative (already accepted).

## 7. Two input sources, one core

- **Live mode:** camera frame every 0.2 s → inference core → overlay on live feed + rolling thickness readout/graph.
- **Batch TIFF mode:** user has thousands of `.TIFF` frames per recorded video. Same inference core fed from a directory → outputs CSV (thickness vs frame/timestamp) + progress bar (reuse existing CINE/TIFF progress-bar pattern). Can run with GUI open or standalone.

## 8. Data / training (to be detailed in plan)

- User has images they can mark up for annotation.
- Images need a **consistent pixel scale** (or scale supplied per image) since thickness is physical (mm). Channel walls serve as the reference; the paper measures thickness proportional to channel diameter so optical distortion partly cancels.
- Varying pressure/viscosity (different lamella thickness) across training images is GOOD — that's the variation to learn.
- Annotation tool, dataset format, train/val split, augmentation, scale-calibration handling: **TBD in detailed plan.**

## 9. Model naming convention

Existing droplet/ligament models use human names (Dennis, Benedict, Claudia, etc.). New lamella model should follow a name convention TBD.

## 10. Open questions for the planning session

1. Confirm outlet channel position stability in the live feed → fixed crop coords vs. configurable crop.
2. Phantom live-feed resolution vs recorded TIFF resolution.
3. Annotation toolchain + dataset format (reuse Detectron tooling or go lighter, e.g. plain masks for U-Net).
4. Pixel-to-mm scale handling — reuse the GUI's existing Calibration sub-panel scale?
5. Where the "Lamella Analysis" button lives (Camera tab, disabled until camera connected).
6. CPU vs GPU at inference time on the target machine.

## 11. Workflow note

- Plan on **Opus 4.8**, implement bulk on **Sonnet 4.6**, escalate tricky bits (Phantom SDK frame interception, model/training script) back to Opus.
- Use **plan mode** for the detailed planning session; review plan before any code is written.
