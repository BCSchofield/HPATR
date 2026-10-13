"""Read a small number of full-rate frames from three CCD-day cines (read-only) into a local cache.

Bursts per run:
  A: 30 consecutive frames from the middle (2500..2529)
  B: 20 consecutive frames elsewhere (1000..1019)
  C: 10 frames at 2550..2559 (control partners for A: k vs k+50)
Also copies (reads) background_median.tiff into memory and saves it to the cache.
Nothing is written under /Volumes.
"""
import json, sys, time
from pathlib import Path
import numpy as np
import cv2
from cine_reader import Cine

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)
ROOT = Path("/Volumes/LaCie/Experiments/2026/10/12")
RUNS = {
    "low_7000": "135146_7000sccm_500rpm_4000sps_or1.2_bh0.5",
    "centre_9000": "130918_9000sccm_500rpm_4000sps_or1.2_bh0.5",
    "high_11000": "125754_11000sccm_500rpm_4000sps_or1.2_bh0.5",
    # slow-flow control: C3, 0.5 mm, 33 sccm delivered (gas-starved dribble); A and C bursts only
    "dribble_C3": "112022_11000sccm_100rpm_5000sps_or0.5_bh0.5",
}
BURSTS = {"A": range(2500, 2530), "B": range(1000, 1020), "C": range(2550, 2560)}

meta = {}
for tag, run in RUNS.items():
    raw = ROOT / run / "shadowgraph" / "raw"
    cine_path = next((raw / "CINE").glob("recording_*.cine"))
    bg = cv2.imread(str(raw / "background_median.tiff"), cv2.IMREAD_UNCHANGED)
    np.save(CACHE / f"{tag}_bg.npy", bg)
    with Cine(cine_path) as cine:
        info = dict(run=run, cine=str(cine_path), first=cine.first_frame_number,
                    last=cine.last_frame_number, fps=float(cine.frame_rate),
                    exposure_s=float(cine.exposure_time_seconds), total=cine.total_frames)
        for b, nums in BURSTS.items():
            if tag == "dribble_C3" and b == "B":
                continue
            out = CACHE / f"{tag}_{b}.npy"
            if out.exists():
                continue
            t = time.time()
            stack = []
            for n in nums:
                cine.load_frame(n)
                stack.append(np.asarray(cine.frame).astype(np.uint16).copy())
            np.save(out, np.stack(stack))
            print(tag, b, len(stack), f"{time.time()-t:.1f}s", flush=True)
        info["bursts"] = {b: [nums.start, nums.stop - 1] for b, nums in BURSTS.items() if not (tag == "dribble_C3" and b == "B")}
        info["frame_shape"] = [1152, 2048]
    meta[tag] = info
(CACHE / "meta.json").write_text(json.dumps(meta, indent=2))
print(json.dumps(meta, indent=2))
