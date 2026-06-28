"""
Draw lamella analysis overlay onto a numpy frame (BGR or grayscale).
Mirrors the cone-feed cv2 overlay pattern in GUI_Clean.py:4120.
"""
from __future__ import annotations
import numpy as np
import cv2

from .infer import Result


# Overlay colour constants (BGR)
_CLR_LIQUID   = (0, 200, 255)   # amber — liquid band markers
_CLR_PROBE    = (0, 255, 120)   # green — probe row line
_CLR_TEXT_BG  = (0, 0, 0)
_CLR_TEXT     = (255, 255, 255)
_FONT         = cv2.FONT_HERSHEY_SIMPLEX


def draw_overlay(frame: np.ndarray, result: Result) -> np.ndarray:
    """
    Composite the lamella analysis result onto frame (in-place copy).

    Draws:
      - A rectangle around the crop region.
      - Horizontal probe lines with liquid-band endpoint markers.
      - Thickness readout text in the top-left corner of the crop.

    Args:
        frame:  Full-frame numpy array (uint8, grayscale or BGR).
                If grayscale (2-D), it is promoted to BGR for colour drawing.
        result: Result from StubSegmenter or LamellaSegmenter.analyse_frame().

    Returns:
        BGR uint8 array same spatial size as frame.
    """
    # Ensure BGR so we can draw in colour
    if frame.dtype != np.uint8:
        f_min, f_max = int(frame.min()), int(frame.max())
        if f_max > f_min:
            frame = ((frame.astype(np.float32) - f_min) * 255.0 / (f_max - f_min)).astype(np.uint8)
        else:
            frame = np.zeros_like(frame, dtype=np.uint8)

    if len(frame.shape) == 2:
        out = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        out = frame.copy()

    cx, cy, cw, ch = result.crop_box

    # ── Crop bounding box ────────────────────────────────────────────────────
    cv2.rectangle(out, (cx, cy), (cx + cw, cy + ch), _CLR_LIQUID, 1)

    # ── Probe lines ──────────────────────────────────────────────────────────
    for (row_y, x_left, x_right) in result.thickness.probe_lines:
        fy = cy + row_y
        # Horizontal span of the liquid on this probe row
        cv2.line(out, (cx + x_left, fy), (cx + x_right, fy), _CLR_PROBE, 1)
        # Small tick marks at the liquid-band boundaries
        cv2.circle(out, (cx + x_left,  fy), 3, _CLR_LIQUID, -1)
        cv2.circle(out, (cx + x_right, fy), 3, _CLR_LIQUID, -1)

    # ── Thickness text ───────────────────────────────────────────────────────
    t = result.thickness
    if t.ok:
        if t.thickness_mm is not None:
            label = f"Lamella: {t.thickness_mm:.3f} mm"
        else:
            label = f"Lamella: {t.thickness_px:.1f} px  (no cal)"
    else:
        label = "Lamella: no liquid detected"

    font_scale = 0.45
    thickness_px = 1
    (tw, th), baseline = cv2.getTextSize(label, _FONT, font_scale, thickness_px)
    tx = cx + 4
    ty = cy + th + 4
    # Dark backing rectangle for readability
    cv2.rectangle(out, (tx - 2, ty - th - 2), (tx + tw + 2, ty + baseline + 2),
                  _CLR_TEXT_BG, -1)
    cv2.putText(out, label, (tx, ty), _FONT, font_scale, _CLR_TEXT, thickness_px,
                cv2.LINE_AA)

    return out
