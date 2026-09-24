#!/usr/bin/env python3
"""
_dust.py -- shared dust-speck map for the validation tooling.

WHAT DUST IS, AND WHY IT IS INVISIBLE TO HALF THE PIPELINE
-----------------------------------------------------------
Specks on the camera sensor are STATIC: same pixels, every frame. The temporal
median background therefore CONTAINS them, so in transmission space they divide
out -- dark / equally-dark = 1.0. Dust is plainly visible in the 8-bit view a
human labels on, and simultaneously invisible in T. Both readings are correct;
they are different quantities.

Consequences that make this worth a shared module:

- `clean_backgrounds.py` never removed dust, and could not have: it detects
  objects in T, where dust does not exist. So all 2000 training composites
  contain these specks, UNLABELLED -- the model is trained that dust is
  background.
- A human labelling the 8-bit view sees droplet-like specks and labels them.
  That puts ~19 objects per frame into the ground truth that the model was
  explicitly trained to ignore, creating guaranteed false negatives which
  punish correct behaviour.

So dust must be identified from the BACKGROUND, not from any single frame.
"""

import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

# A pixel this much darker than the global static field is a sensor speck, not
# illumination roll-off. Measured specks on this rig run 10-35% down; the
# vignette is a broad gradient rather than discrete spots, so a fixed fraction
# separates them cleanly.
DUST_DARKNESS = 0.93
DUST_MIN_AREA = 4
# Dust absorbs nothing beyond what is already in the background, so a shape
# sitting on it stays near T=1. A real droplet on top of a speck would pull
# this down and is therefore not treated as dust.
DUST_MAX_ABSORPTION = 0.85
DUST_COVERAGE = 0.5


def dust_mask(bg: np.ndarray, darkness: float = DUST_DARKNESS,
              min_area: int = DUST_MIN_AREA) -> np.ndarray:
    """Discrete dark specks in the static background field."""
    glob = float(np.median(bg))
    raw = (bg < glob * darkness).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(raw, 8)
    keep = np.zeros_like(raw, dtype=bool)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[lab == i] = True
    return keep


def is_dust(shape_mask: np.ndarray, T: np.ndarray, dust: np.ndarray,
            coverage: float = DUST_COVERAGE,
            max_absorption: float = DUST_MAX_ABSORPTION) -> bool:
    """
    True if this shape is a sensor speck rather than liquid.

    Both conditions must hold: most of it sits on a known speck, AND it never
    gets dark in transmission. The second is what protects a genuine droplet
    that happens to land on a speck -- that absorbs, so its t_min drops.
    """
    area = int(shape_mask.sum())
    if area < 1:
        return False
    on_dust = int((shape_mask & dust).sum()) / area
    if on_dust < coverage:
        return False
    return float(T[shape_mask].min()) > max_absorption


def describe(bg: np.ndarray) -> str:
    d = dust_mask(bg)
    n, _, stats, _ = cv2.connectedComponentsWithStats(d.astype(np.uint8), 8)
    specks = sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= DUST_MIN_AREA)
    return (f"{specks} sensor specks, {int(d.sum())} px "
            f"({d.sum() / d.size * 100:.3f}% of frame)")
