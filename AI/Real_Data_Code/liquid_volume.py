#!/usr/bin/env python3
"""
liquid_volume.py -- liquid VOLUME from a 2D shadowgraph mask (classical_liquid's
secondary, volume-based atomised fraction; 2026-10-13).

WHY. The atomised fraction is a ratio of projected AREAS. A sphere carries 2d/3 of
depth per pixel of its projection (~27 um for a 40 um droplet); a round ligament
or stream of thickness D carries pi D / 4 (~390 um for 0.5 mm). So one pixel of
un-atomised liquid holds 5-15x the liquid of one pixel of droplet, and the area
ratio overstates the atomised VOLUME share by an amount that differs run to run
(thicker pieces at low gas). On the CCD day (2026-10-12) volume ranked the runs
like area (Spearman 0.88 on the flow-controlled runs) at ~1/4 of its scale, with
the gas effect doubled: docs/notes/2026-10-13_area_vs_volume_and_window.md.

HOW.
    droplets      each connected piece of the droplet mask is a sphere of the
                  same projected area: pi d^3 / 6, d = sqrt(4 A / pi). (Slicing
                  along the principal axis, Blaisot & Yon 2005 s3.4 after Daves
                  et al. 1993, gives 0.85x this for the elongated ones: a uniform
                  bias across runs, SD 0.02.)
    un-atomised   every piece is a body with a ROUND cross-section: each pixel's
                  chord through it is 2 sqrt(R^2 - (R - e)^2), with e the pixel's
                  distance to the piece's edge and R the local radius at its
                  nearest RIDGE point (the distance map's local maxima: the
                  medial axis, without needing a skeletonising library). For a
                  disc this is exactly a sphere and for a strip a cylinder, and
                  it follows a curved ligament, which one principal axis cannot.
                  A hole left by a DROPLET cut out of a blob is closed for the
                  geometry (pass the droplet mask as `fill`); a genuine hole (a
                  loop of ligament) stays open. Chords are summed over the
                  piece's own pixels.

UNCERTAINTY. The round cross-section is an assumption: a flat ribbon (chord = R)
gives ~0.6x; on compact blobs principal-axis slicing gives ~1.3x; 2-4 px threads
read up to 35% low. Absolute un-atomised volume is good to about +/-40%; the
ranking of runs is much better than that (round vs ribbon Spearman 0.999).

OpenCV and numpy only: the pipeline's Windows env does not promise scipy or
scikit-image. Volumes are in px^3 (multiply by um_per_px^3).
"""

import cv2
import numpy as np

_K3 = np.ones((3, 3), np.uint8)


def sphere_volume_px3(area_px) -> float:
    a = np.asarray(area_px, float)
    d = np.sqrt(4.0 * a / np.pi)
    return float(np.sum(np.pi * d ** 3 / 6.0))


def droplet_volume_px3(dmask) -> float:
    """Sum over connected pieces of the droplet mask, each as a sphere of equal projected area."""
    n, _lab, stats, _ = cv2.connectedComponentsWithStats(np.asarray(dmask, np.uint8), connectivity=8)
    if n <= 1:
        return 0.0
    return sphere_volume_px3(stats[1:, cv2.CC_STAT_AREA])


def _fill_holes(m: np.ndarray) -> np.ndarray:
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(m)
    if cnts:
        cv2.drawContours(out, cnts, -1, 1, thickness=cv2.FILLED)
    return out | m


def _piece_volume(own: np.ndarray, fill: "np.ndarray | None" = None) -> float:
    """One connected piece (uint8 0/1, padded by >= 1 px of background). `fill`: pixels allowed to
    close the piece's holes (the droplet mask): a droplet sitting in a blob is cut out of the
    un-atomised mask, and the blob's body continues through it."""
    filled = own if fill is None else own | (_fill_holes(own) & fill)
    dist = cv2.distanceTransform(filled, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    ridge = (dist >= cv2.dilate(dist, _K3)) & (filled > 0)
    if not ridge.any():
        return float(own.sum())
    # nearest ridge pixel of every pixel: label map of the zeros of (not ridge)
    src = np.where(ridge, 0, 1).astype(np.uint8)
    _d, labels = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, cv2.DIST_MASK_PRECISE,
                                                 labelType=cv2.DIST_LABEL_PIXEL)
    lut = np.zeros(int(labels.max()) + 1, np.float32)
    lut[labels[ridge]] = np.maximum(dist[ridge] - 0.5, 0.5)
    R = lut[labels]
    e = np.clip(dist - 0.5, 0.0, None)
    e = np.minimum(e, R)
    chord = 2.0 * np.sqrt(np.maximum(R * R - (R - e) ** 2, 0.0))
    # a pixel's own depth can never be less than a pixel; tiny pieces otherwise read ~0
    chord = np.maximum(chord, 1.0)
    return float(chord[own > 0].sum())


def body_volume_px3(mask, fill=None, min_area: int = 1) -> float:
    """Liquid volume of every connected piece of `mask`, each with a round cross-section. `fill`
    (optional, same shape): pixels that may close a piece's holes, normally the droplet mask."""
    m = np.asarray(mask, np.uint8)
    fm = None if fill is None else np.asarray(fill, np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    total = 0.0
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < min_area:
            continue
        x0, y0, w, h = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH,
                                                   cv2.CC_STAT_HEIGHT))
        if a <= 2:
            total += float(a)                              # a pixel or two: one pixel deep
            continue
        crop = np.zeros((h + 2, w + 2), np.uint8)
        crop[1:-1, 1:-1] = (lab[y0:y0 + h, x0:x0 + w] == i)
        fcrop = None
        if fm is not None:
            fcrop = np.zeros_like(crop)
            fcrop[1:-1, 1:-1] = fm[y0:y0 + h, x0:x0 + w]
        total += _piece_volume(crop, fcrop)
    return total
