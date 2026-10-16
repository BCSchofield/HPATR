"""
window_check.py -- is there something on the window that was not there when it was clean?

A drop on the shadowgraph window (or lens) is counted as un-atomised liquid whenever it differs from
the run's background median: it lands mid-run, grows, drips. On the CCD day (2026-10-12) that cut the
atomised fraction of 10 runs, C20 from 10.5% to 6.0% (liquid stage 2.3.0 now masks most of it after
the fact; docs/notes/2026-10-13_area_vs_volume_and_window.md). Cheaper to catch it before the run:
compare a live frame with a reference taken when the window was known clean, and list the dark
spots that are new.

    ratio = live / reference, divided by its median (so a dimmer or brighter backlight does not count)
    smoothed over SMOOTH_PX, spots = connected pieces with ratio < DARK of at least MIN_AREA_PX
    whose darkest point is below CORE (a real drop has a dark core: 0.15-0.7 of the clean window on
    the CCD day; a faint backlight gradient does not)

The thresholds are first settings from the CCD day's background medians, to be tuned on the rig.

Numpy and OpenCV only (no Qt), so it is testable on its own. GUI_Clean's Camera tab saves the
reference and runs the check at Start Experiment.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:                       # the GUI starts without OpenCV; the check then says so
    cv2 = None

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "AI" / "Real_Data_Code"))
import optics  # noqa: E402  (one profile per optical set-up: config/optics/)

DARK = 0.90             # a spot's extent: at least 10% darker than the clean window there
CORE = 0.80             # ... and its darkest point at least 20% darker
UM_PER_PX = float(optics.current()["um_per_px"])     # the rig's set-up now
MIN_AREA_MM2 = 0.04     # a ~0.2 mm drop; single droplets in flight are far smaller
MIN_AREA_PX = int(round(MIN_AREA_MM2 / (UM_PER_PX / 1000.0) ** 2))   # 400 px at 10 um/px
SMOOTH_PX = 7           # box filter: pixel noise must not make spots
REFERENCE_DIR = os.path.join(os.path.expanduser("~"), ".hpatr")
REFERENCE_NAME = "window_reference.npz"


@dataclass
class WindowCheck:
    ok: bool                              # no new spots (or nothing to compare: see `skipped`)
    spots: list = field(default_factory=list)    # (x, y, w, h, area_px, darkest ratio), largest first
    area_pct: float = 0.0                 # share of the frame the spots cover
    skipped: str = ""                     # why the check did not run ('' when it did)

    def text(self) -> str:
        """One line for the log and run_summary: 'clean', '3 new dark spots, 0.42% of the frame,
        largest 0.31 mm2' or 'skipped: ...'."""
        if self.skipped:
            return f"skipped: {self.skipped}"
        if self.ok:
            return "clean"
        big = self.spots[0][4] * (UM_PER_PX / 1000.0) ** 2
        n = len(self.spots)
        return (f"{n} new dark spot{'s' if n != 1 else ''}, {self.area_pct:.2f}% of the frame, "
                f"largest {big:.2f} mm2")


def to_gray(frame) -> np.ndarray:
    """Any Phantom live frame (uint8 / uint16, grey or RGB) as float32 grey."""
    a = np.asarray(frame)
    if a.ndim == 3:
        a = a[..., :3].mean(axis=2)
    return a.astype(np.float32)


def compare(live, reference, dark: float = DARK, core: float = CORE, min_area_px: int = MIN_AREA_PX,
            smooth_px: int = SMOOTH_PX) -> WindowCheck:
    """The dark spots in `live` that are not in `reference` (both raw camera frames)."""
    if cv2 is None:
        return WindowCheck(True, skipped="OpenCV is not installed")
    L, R = to_gray(live), to_gray(reference)
    if L.shape != R.shape:
        return WindowCheck(True, skipped=f"the reference is {R.shape[1]}x{R.shape[0]}, the camera now "
                                         f"{L.shape[1]}x{L.shape[0]}: save a new reference at this size")
    ratio = L / np.maximum(R, 1.0)
    med = float(np.median(ratio))
    if not np.isfinite(med) or med <= 0:
        return WindowCheck(True, skipped="the live frame is black")
    ratio = cv2.blur(ratio / med, (smooth_px, smooth_px))
    mask = (ratio < dark).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    spots = []
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        if a < min_area_px:
            continue
        x, y, w, h = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                                  cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        darkest = float(ratio[y:y + h, x:x + w][lab[y:y + h, x:x + w] == i].min())
        if darkest < core:
            spots.append((x, y, w, h, a, round(darkest, 3)))
    spots.sort(key=lambda s: -s[4])
    area = 100.0 * sum(s[4] for s in spots) / mask.size
    return WindowCheck(not spots, spots, round(area, 3))


def overlay(live, check: WindowCheck, max_width: int = 900) -> np.ndarray:
    """The live frame as 8-bit RGB with each new spot boxed in orange, scaled to max_width (for the
    warning dialog)."""
    g = to_gray(live)
    lo, hi = np.percentile(g, (0.5, 99.5))
    g8 = np.clip((g - lo) * 255.0 / max(hi - lo, 1.0), 0, 255).astype(np.uint8)
    rgb = np.dstack([g8, g8, g8])
    if cv2 is not None:
        t = max(2, g.shape[1] // 400)
        for x, y, w, h, *_ in check.spots:
            cv2.rectangle(rgb, (x - 6, y - 6), (x + w + 6, y + h + 6), (255, 149, 0), t)
        if rgb.shape[1] > max_width:
            s = max_width / rgb.shape[1]
            rgb = cv2.resize(rgb, (max_width, round(rgb.shape[0] * s)), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(rgb)


def reference_path(folder: str | None = None) -> str:
    return os.path.join(folder or REFERENCE_DIR, REFERENCE_NAME)


def save_reference(frame, note: str = "", folder: str | None = None) -> str:
    """Keep this frame as the clean-window reference (on this PC: it belongs to this rig's camera)."""
    path = reference_path(folder)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    meta = {"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note,
            "shape": list(np.asarray(frame).shape), "dtype": str(np.asarray(frame).dtype)}
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, frame=np.asarray(frame), meta=json.dumps(meta))
    os.replace(tmp, path)
    return path


def load_reference(folder: str | None = None):
    """(frame, meta dict) or (None, None) when there is no reference."""
    path = reference_path(folder)
    if not os.path.isfile(path):
        return None, None
    with np.load(path, allow_pickle=False) as z:
        return z["frame"], json.loads(str(z["meta"]))
