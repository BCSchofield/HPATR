"""The liquid map: every piece of liquid in a frame, found classically (no AI), each at its own half-max edge.

Moved out of classical_liquid.py (sizer 3.1.0 plan, 2026-10-17) so measure_run can use the same map. 3.1.0 measures
a droplet on its own profile with EVERY other piece of liquid blanked, not only the other AI detections: dark liquid
the AI did not detect (a jet edge, a ligament, a drop on the window) made 3.0.0's sizes run away to 200-430 um.
numpy + OpenCV only (the lab PC has no scipy).
"""
import cv2
import numpy as np

SEED_THR = 0.70      # strict: definitely liquid. Same value as the focus gate.
CEILING_THR = 0.95   # bounds region growing only -- never an edge itself
MIN_AREA = 20        # px; below this nothing can carry a measurement


def hysteresis(T, seed_thr=SEED_THR, ceiling=CEILING_THR, min_area=MIN_AREA):
    """Liquid mask: seed on dark cores, grow each seed to ITS OWN half-max edge.

    Two thresholds are needed because one cannot work. T<0.95 (what
    extract_candidates.py uses to generate CANDIDATES, before curation) gives
    36,695 components per frame, 89% of the area sitting at transmission
    0.90-0.95 -- sensor and illumination noise. T<0.70 alone loses the faint
    edges of real objects.

    The grow threshold is PER COMPONENT, at that component's own half-maximum
    (t_min + 1) / 2, not a fixed value. This matters and a fixed grow is wrong:

      * It is the edge definition the rest of the project already uses. Hand
        labels, extract_candidates.py and therefore the model's own training
        targets all put an object's edge at its own half-max. Measuring droplets
        at half-max (via the model) and un-atomised liquid at some other
        threshold would mix two edge definitions inside one ratio.

      * A fixed grow over-segments dark objects. A thread with t_min 0.06 has its
        true edge at 0.53; growing it to 0.90 inflated it by ~1.5x, visible as an
        orange halo wider than the thread itself.

      * It was double-counting droplets. Growing a droplet past its half-max left
        a rim outside the model's mask, which then scored as un-atomised liquid.
        On frame_0099_n989 that rim was 85.5% of all "un-atomised" area, dragging
        a genuinely ~97% atomised frame down to 74%. At half-max it is 5.9%.

    Growing from the seed rather than refining an existing mask also keeps
    regions connected: measured on Trial_1, post-hoc refinement of a fixed-grow
    mask SPLIT components (76 -> 81), while growing to the same edge from the
    seed merges them (76 -> 51) for the same final area.

    `ceiling` only bounds the region growing; it is never an edge itself.
    """
    grow = (T < ceiling).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(grow, 8)
    seeded = {i for i in np.unique(lab[T < seed_thr]) if i != 0}
    if not seeded:
        return np.zeros(T.shape, bool), 0

    # Work inside each component's BOUNDING BOX, which
    # connectedComponentsWithStats already gives us. `lab == i` over the whole
    # frame builds a 2.4 M-element boolean per component, and there are hundreds
    # of components per frame -- that one line was 56% of the classical pass
    # (0.30 s/frame). A component lies entirely within its own bbox by
    # definition, so this is the same computation on a smaller array and the
    # result is bit-identical.
    out = np.zeros(T.shape, bool)
    for i in seeded:
        x0 = stats[i, cv2.CC_STAT_LEFT]
        y0 = stats[i, cv2.CC_STAT_TOP]
        sl = (slice(y0, y0 + stats[i, cv2.CC_STAT_HEIGHT]),
              slice(x0, x0 + stats[i, cv2.CC_STAT_WIDTH]))
        comp = lab[sl] == i
        Tc = T[sl]
        out[sl] |= comp & (Tc < (Tc[comp].min() + 1.0) / 2.0)

    n2, lab2, stats2, _ = cv2.connectedComponentsWithStats(out.astype(np.uint8), 8)
    big = [j for j in range(1, n2) if stats2[j, cv2.CC_STAT_AREA] >= min_area]
    return np.isin(lab2, big), len(big)
