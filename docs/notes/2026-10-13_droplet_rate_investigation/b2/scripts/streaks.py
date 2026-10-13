"""Look for faint motion streaks: thin, elongated, low-contrast objects aligned with the flow axis.
A fast small droplet at 4 us exposure is a streak of length d + L (L = v * 4 us / 10 um px) whose
contrast drops roughly as d / (d + L); these would fail the T < 0.6 seed and the focus gate.
Faint objects: seed T < 0.85, grow T < 0.93, T_min in [0.6, 0.85], minor axis 2-7 px, aspect >= 2.5.
Compares the orientation distribution with the in-focus droplet elongation axis, and saves a gallery."""
import json
import numpy as np
import cv2
from common import load, segment, RUNS, CONTROL, HERE

OUT = HERE / "results"; LOOK = HERE / "look"
res = {}
for tag in RUNS + [CONTROL]:
    D = load(tag)
    frames = [T for st in D.values() for T in st]
    angs, lens, wids, crops = [], [], [], []
    for T in frames:
        _, bl = segment(T, seed=0.85, grow=0.93)
        for b in bl:
            if b["border"] or not (0.6 <= b["tmin"] <= 0.85):
                continue
            if not (2 <= b["minor"] <= 7) or b["major"] / max(b["minor"], 1e-6) < 2.5:
                continue
            angs.append(b["ang_from_vertical"]); lens.append(b["major"]); wids.append(b["minor"])
            if len(crops) < 48:
                cy, cx = int(b["cy"]), int(b["cx"])
                c = T[max(cy - 24, 0):cy + 24, max(cx - 24, 0):cx + 24]
                if c.shape == (48, 48):
                    crops.append(c)
    angs = np.array(angs); lens = np.array(lens)
    # angle relative to the in-focus droplet elongation axis (~ -14 deg from vertical)
    rel = (angs + 14 + 90) % 180 - 90
    res[tag] = dict(n_frames=len(frames), faint_elongated_per_frame=len(angs) / len(frames),
                    frac_within_20deg_of_flow_axis=float(np.mean(np.abs(rel) < 20)) if len(rel) else None,
                    frac_within_20deg_of_perpendicular=float(np.mean(np.abs(rel) > 70)) if len(rel) else None,
                    median_length_px=float(np.median(lens)) if len(lens) else None)
    print(tag, res[tag], flush=True)
    if crops:
        rows = [np.hstack(crops[i:i + 8]) for i in range(0, len(crops) - len(crops) % 8, 8)]
        g = np.vstack(rows)
        img = (np.clip((g - 0.4) / 0.65, 0, 1) * 255).astype(np.uint8)
        cv2.imwrite(str(LOOK / f"faint_elongated_gallery_{tag}.png"), cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
(OUT / "streak_summary.json").write_text(json.dumps(res, indent=1))
