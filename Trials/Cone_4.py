"""
Cone angle detection using intensity profile analysis with sigmoid fitting.

WHY THIS APPROACH:
    Effervescent atomisation of silicone/n-heptane produces a spray of small,
    semi-transparent droplets with soft, diffuse edges.  The cone boundary is a
    gradual intensity transition — there is no hard step-change for a contour
    detector to latch onto.  Cone_3 (contour/PCA) is therefore unreliable.

HOW IT DIFFERS FROM Cone_3:
    No contour detection, no morphological processing, no thresholding.
    Instead, for each horizontal row we fit a logistic sigmoid to the intensity
    profile on each side of the spray centre.  The inflection point of the
    sigmoid (parameter x0) is the boundary location.  Boundary locations are
    collected across all rows, then a straight line is fitted through each set
    to give the left and right cone edges.

KNOWN LIMITATIONS:
    * Requires at least some intensity contrast across the boundary.
      Very uniform backgrounds or extremely diffuse cones give low fit quality
      (reported in the returned debug dict and via a console warning).
    * Assumes the spray is roughly centred horizontally and darker than the
      background (backlit shadowgraph geometry).  Reverse-contrast images will
      also work because the sigmoid direction is chosen per-row.
"""

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np
from scipy.optimize import curve_fit

# Allow running from repo root
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config_loader import get_imaging_config  # noqa: E402

# ---------------------------------------------------------------------------
# Algorithm parameters (module-level defaults, overridable via function args)
# ---------------------------------------------------------------------------
TOP_CROP_RATIO = 0.05       # Fraction of image height to crop from top
ROW_STEP = 1                # Process every row
MIN_R2 = 0.75               # Minimum sigmoid fit R² to accept a boundary point
MIN_CONTRAST = 10.0         # Minimum abs(U-L) to attempt / accept a fit (0-255)
MIN_BOUNDARY_POINTS = 20    # Minimum accepted points per side to compute angle
SIGMOID_WINDOW = 0.4        # Fraction of half-row width used for sigmoid fitting


# ---------------------------------------------------------------------------
# Sigmoid model
# ---------------------------------------------------------------------------

def _sigmoid(x: np.ndarray, L: float, U: float, k: float, x0: float) -> np.ndarray:
    """Logistic sigmoid: f(x) = L + (U-L) / (1 + exp(-k*(x-x0)))"""
    return L + (U - L) / (1.0 + np.exp(-k * (x - x0)))


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Coefficient of determination."""
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot < 1e-12:
        return 0.0
    return float(1.0 - ss_res / ss_tot)


# ---------------------------------------------------------------------------
# Per-row boundary detection
# ---------------------------------------------------------------------------

def _find_row_boundaries(
    row: np.ndarray,
    min_r2: float,
    min_contrast: float,
    sigmoid_window: float,
) -> tuple[float | None, float | None, float, float]:
    """
    Fit sigmoids to the left and right halves of a single intensity row.

    Returns
    -------
    (x_left, x_right, r2_left, r2_right)
        x_left / x_right : boundary x-coordinate, or None if fit rejected.
        r2_left / r2_right : R² of the accepted fit (0.0 if rejected).
    """
    n = len(row)
    if n < 16:
        return None, None, 0.0, 0.0

    row_f = row.astype(np.float64)

    # Locate spray centre as darkest region via rolling mean (window = 10% of width)
    win = max(3, n // 10)
    kernel = np.ones(win) / win
    smoothed = np.convolve(row_f, kernel, mode="same")
    centre_x = int(np.argmin(smoothed))

    results = []
    for side in ("left", "right"):
        if side == "left":
            # Left half: x in [0, centre_x], boundary is dark→bright (left to right)
            # Use a window around the expected transition
            half = row_f[: centre_x + 1]
            if len(half) < 8:
                results.append((None, 0.0))
                continue
            win_w = max(8, int(len(half) * sigmoid_window))
            seg = half[-win_w:]          # right portion of the left half
            x_coords = np.arange(len(half) - win_w, len(half), dtype=np.float64)
            # dark on the left (inside), bright on the right (background)
            L_init = float(np.min(seg))
            U_init = float(np.max(seg))
            rising = True
        else:
            # Right half: x in [centre_x, n), boundary is bright→dark (left to right)
            half = row_f[centre_x:]
            if len(half) < 8:
                results.append((None, 0.0))
                continue
            win_w = max(8, int(len(half) * sigmoid_window))
            seg = half[:win_w]           # left portion of the right half
            x_coords = np.arange(centre_x, centre_x + win_w, dtype=np.float64)
            # bright on the left (background), dark on the right (inside)
            L_init = float(np.max(seg))
            U_init = float(np.min(seg))
            rising = False

        contrast = abs(U_init - L_init)
        if contrast < min_contrast:
            results.append((None, 0.0))
            continue

        # Bounds: x0 must lie within the segment x range
        x_lo, x_hi = float(x_coords[0]), float(x_coords[-1])
        # k > 0 for rising, k < 0 for falling (we allow both signs but constrain magnitude)
        if rising:
            k_lo, k_hi = 0.01, 2.0
        else:
            k_lo, k_hi = -2.0, -0.01

        p0 = [L_init, U_init, (k_lo + k_hi) / 2.0, float(np.mean(x_coords))]
        bounds_lo = [min(L_init, U_init) - contrast, min(L_init, U_init) - contrast, k_lo, x_lo]
        bounds_hi = [max(L_init, U_init) + contrast, max(L_init, U_init) + contrast, k_hi, x_hi]

        try:
            popt, _ = curve_fit(
                _sigmoid, x_coords, seg,
                p0=p0,
                bounds=(bounds_lo, bounds_hi),
                maxfev=400,
            )
        except (RuntimeError, ValueError):
            results.append((None, 0.0))
            continue

        L_fit, U_fit, k_fit, x0_fit = popt

        # Quality checks
        if abs(U_fit - L_fit) < min_contrast:
            results.append((None, 0.0))
            continue
        if x0_fit < x_lo or x0_fit > x_hi:
            results.append((None, 0.0))
            continue

        y_pred = _sigmoid(x_coords, *popt)
        r2_val = _r2(seg, y_pred)
        if r2_val < min_r2:
            results.append((None, 0.0))
            continue

        results.append((float(x0_fit), r2_val))

    (x_left, r2_l), (x_right, r2_r) = results
    return x_left, x_right, r2_l, r2_r


# ---------------------------------------------------------------------------
# Outermost-per-bin filter
# ---------------------------------------------------------------------------

def _outermost_per_bin(
    xs: np.ndarray,
    ys: np.ndarray,
    is_left: bool,
    n_bins: int = 50,
) -> tuple[np.ndarray, np.ndarray]:
    """
    For each y-bin keep only the most extreme x (leftmost for left side,
    rightmost for right side).  This discards internal transitions and keeps
    only points that lie on the outer envelope of the cone.
    """
    if len(xs) == 0:
        return xs, ys

    y_min, y_max = ys.min(), ys.max()
    if y_max == y_min:
        return xs, ys

    bins = np.linspace(y_min, y_max, n_bins + 1)
    out_xs, out_ys = [], []

    for i in range(n_bins):
        mask = (ys >= bins[i]) & (ys < bins[i + 1])
        if not mask.any():
            continue
        bx = xs[mask]
        by = ys[mask]
        idx = int(np.argmin(bx)) if is_left else int(np.argmax(bx))
        out_xs.append(bx[idx])
        out_ys.append(by[idx])

    # include the last bin's upper edge
    mask = ys >= bins[-2]
    if mask.any():
        bx, by = xs[mask], ys[mask]
        idx = int(np.argmin(bx)) if is_left else int(np.argmax(bx))
        out_xs.append(bx[idx])
        out_ys.append(by[idx])

    return np.array(out_xs), np.array(out_ys)


# ---------------------------------------------------------------------------
# Line-fit R² helper
# ---------------------------------------------------------------------------

def _line_r2(x_vals: np.ndarray, y_vals: np.ndarray, coeffs: np.ndarray) -> float:
    """R² of x = m*y + c fit."""
    x_pred = np.polyval(coeffs, y_vals)
    return _r2(x_vals, x_pred)


def _ransac_line(
    xs: np.ndarray,
    ys: np.ndarray,
    n_iterations: int = 200,
    inlier_threshold: float = 15.0,
    min_inlier_ratio: float = 0.4,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit a line x = m*y + c using RANSAC (Random Sample Consensus).

    How it works
    ------------
    RANSAC is an iterative outlier-rejection algorithm:

    1. Randomly pick 2 points from the set.
    2. Fit a line exactly through those 2 points.
    3. Count how many of the *remaining* points lie within
       `inlier_threshold` pixels of that line — these are the "inliers".
    4. Repeat steps 1-3 for `n_iterations` random samples.
    5. Take the sample whose line had the most inliers.
    6. Refit the line using *all* inliers from that best sample
       (ordinary polyfit on the inlier subset) — this gives a more
       accurate line than the 2-point seed alone.

    The key insight: an outlier point (e.g. a rogue detection in the
    spray breakup region) has very little chance of being picked as the
    seed in two consecutive iterations, so it almost never drives the
    consensus line.  The true cone boundary, having many consistent
    points, will dominate.

    Parameters
    ----------
    inlier_threshold : float
        Maximum horizontal distance (pixels) from the line for a point
        to count as an inlier.  ~10-20px works well for this image scale.
    min_inlier_ratio : float
        If the best fit has fewer inliers than this fraction of the total
        points, fall back to plain polyfit (likely too few consistent pts).

    Returns
    -------
    coeffs : np.ndarray  — [m, c] for x = m*y + c
    inlier_mask : np.ndarray (bool) — which points were inliers
    """
    best_coeffs = np.polyfit(ys, xs, deg=1)   # fallback
    best_inliers = np.ones(len(xs), dtype=bool)
    best_n_inliers = 0

    rng = np.random.default_rng(seed=42)

    for _ in range(n_iterations):
        # 1. Pick 2 random points
        idx = rng.choice(len(xs), size=2, replace=False)
        y_s = ys[idx]
        x_s = xs[idx]

        # 2. Fit line through those 2 points
        if abs(y_s[1] - y_s[0]) < 1e-6:
            continue   # degenerate — same y, skip
        coeffs = np.polyfit(y_s, x_s, deg=1)

        # 3. Distance of all points from this line
        x_pred = np.polyval(coeffs, ys)
        dist = np.abs(xs - x_pred)
        inliers = dist < inlier_threshold
        n_inliers = int(inliers.sum())

        # 4. Keep best
        if n_inliers > best_n_inliers:
            best_n_inliers = n_inliers
            best_inliers = inliers
            best_coeffs = coeffs

    # 5. Refit on full inlier set
    if best_n_inliers >= max(2, int(min_inlier_ratio * len(xs))):
        best_coeffs = np.polyfit(ys[best_inliers], xs[best_inliers], deg=1)
    else:
        print(f"[Cone_4] RANSAC: low inlier count ({best_n_inliers}/{len(xs)}), using plain polyfit")
        best_inliers = np.ones(len(xs), dtype=bool)
        best_coeffs = np.polyfit(ys, xs, deg=1)

    return best_coeffs, best_inliers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_cone_angle(
    image_path: Path,
    nozzle_x: float | None = None,
    top_crop_ratio: float = TOP_CROP_RATIO,
    debug: bool = True,
    min_r2: float = MIN_R2,
    min_contrast: float = MIN_CONTRAST,
) -> tuple[float | None, np.ndarray, dict]:
    """
    Detect spray cone angle from a single image using sigmoid profile fitting.

    Parameters
    ----------
    image_path : Path
        Path to the input image (TIFF, PNG, …).
    nozzle_x : float, optional
        Horizontal position of the nozzle.  If None the spray centre is found
        automatically per-row (recommended).
    top_crop_ratio : float
        Fraction of image height to remove from the top before processing.
    debug : bool
        If True, overlay sigmoid fit locations (crosses) on the annotated image.
    min_r2 : float
        Minimum R² of a sigmoid fit to accept the boundary point.
    min_contrast : float
        Minimum intensity contrast |U-L| required to attempt fitting.

    Returns
    -------
    angle_degrees : float or None
        Total cone angle in degrees, or None if detection failed.
    annotated_image : np.ndarray
        BGR image with boundary lines, accepted points, and text annotations.
    debug_info : dict
        Quality metrics and intermediate arrays.
    """
    # --- load & normalise -------------------------------------------------
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img_raw = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        raise ValueError(f"Cannot load image: {image_path}")

    if len(img_raw.shape) == 3:
        gray = cv2.cvtColor(img_raw, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_raw.copy()

    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    # --- top crop ---------------------------------------------------------
    h_orig, w = gray.shape
    top_px = int(h_orig * top_crop_ratio)
    gray = gray[top_px:, :]
    h, w = gray.shape
    print(f"[Cone_4] Image {w}×{h} (cropped {top_px}px from top)")

    # --- row-by-row boundary detection ------------------------------------
    left_xs, left_ys, left_r2s = [], [], []
    right_xs, right_ys, right_r2s = [], [], []
    debug_sigmoid_pts: list[tuple[int, int, str]] = []  # (x, y, side) for debug overlay

    for row_y in range(0, h, ROW_STEP):
        row = gray[row_y, :]
        xl, xr, r2l, r2r = _find_row_boundaries(
            row, min_r2, min_contrast, SIGMOID_WINDOW
        )
        if xl is not None:
            left_xs.append(xl)
            left_ys.append(float(row_y))
            left_r2s.append(r2l)
            if debug:
                debug_sigmoid_pts.append((int(xl), row_y, "left"))
        if xr is not None:
            right_xs.append(xr)
            right_ys.append(float(row_y))
            right_r2s.append(r2r)
            if debug:
                debug_sigmoid_pts.append((int(xr), row_y, "right"))

    n_left = len(left_xs)
    n_right = len(right_xs)
    print(f"[Cone_4] Accepted boundary points — left: {n_left}, right: {n_right}")

    # --- annotated image (BGR) -------------------------------------------
    annotated = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Draw ALL accepted boundary points (small, dim)
    for x, y in zip(left_xs, left_ys):
        cv2.circle(annotated, (int(x), int(y)), 1, (120, 120, 0), -1)
    for x, y in zip(right_xs, right_ys):
        cv2.circle(annotated, (int(x), int(y)), 1, (0, 120, 120), -1)

    if debug:
        # Already drawn as part of accepted points; add small cross markers
        for xd, yd, side in debug_sigmoid_pts:
            col = (255, 255, 0) if side == "left" else (0, 255, 255)
            cv2.drawMarker(annotated, (xd, yd), col, cv2.MARKER_CROSS, 5, 1)

    # --- handle insufficient points ---------------------------------------
    fail_msg = None
    if n_left < MIN_BOUNDARY_POINTS:
        fail_msg = f"Insufficient left boundary points ({n_left} < {MIN_BOUNDARY_POINTS})"
    if n_right < MIN_BOUNDARY_POINTS:
        msg2 = f"Insufficient right boundary points ({n_right} < {MIN_BOUNDARY_POINTS})"
        fail_msg = (fail_msg + "; " + msg2) if fail_msg else msg2

    debug_info_base = {
        "gray": gray,
        "image_path": image_path,
        # All accepted points (before outermost filter)
        "left_xs_all": np.array(left_xs),
        "left_ys_all": np.array(left_ys),
        "right_xs_all": np.array(right_xs),
        "right_ys_all": np.array(right_ys),
        # Outermost-filtered points actually used for line fitting
        "left_xs": np.array(left_xs),
        "left_ys": np.array(left_ys),
        "right_xs": np.array(right_xs),
        "right_ys": np.array(right_ys),
        "left_r2s": np.array(left_r2s),
        "right_r2s": np.array(right_r2s),
        "left_points_accepted": n_left,
        "right_points_accepted": n_right,
        "left_r2_mean": float(np.mean(left_r2s)) if left_r2s else 0.0,
        "right_r2_mean": float(np.mean(right_r2s)) if right_r2s else 0.0,
    }

    if fail_msg:
        print(f"[Cone_4] Warning: {fail_msg}")
        cv2.putText(annotated, fail_msg[:60], (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        debug_info_base.update({
            "error": fail_msg,
            "left_line_r2": 0.0,
            "right_line_r2": 0.0,
            "fit_quality": 0.0,
        })
        return None, annotated, debug_info_base

    # --- line fitting: x = m*y + c  (x as function of y) -----------------
    # Filter to outermost point per y-bin first — discards internal transitions
    left_xs_outer, left_ys_outer = _outermost_per_bin(
        np.array(left_xs), np.array(left_ys), is_left=True
    )
    right_xs_outer, right_ys_outer = _outermost_per_bin(
        np.array(right_xs), np.array(right_ys), is_left=False
    )
    print(f"[Cone_4] Outermost filter — left: {len(left_xs_outer)}, right: {len(right_xs_outer)}")

    left_coeffs, left_inlier_mask = _ransac_line(left_xs_outer, left_ys_outer)
    right_coeffs, right_inlier_mask = _ransac_line(right_xs_outer, right_ys_outer)
    print(f"[Cone_4] RANSAC inliers — left: {left_inlier_mask.sum()}/{len(left_xs_outer)}, "
          f"right: {right_inlier_mask.sum()}/{len(right_xs_outer)}")

    # R² computed on inliers only (how well the consensus points fit the line)
    left_line_r2 = _line_r2(left_xs_outer[left_inlier_mask],
                             left_ys_outer[left_inlier_mask], left_coeffs)
    right_line_r2 = _line_r2(right_xs_outer[right_inlier_mask],
                              right_ys_outer[right_inlier_mask], right_coeffs)
    fit_quality = (left_line_r2 + right_line_r2) / 2.0

    if fit_quality < 0.6:
        print(f"[Cone_4] Warning: low fit quality ({fit_quality:.2f}) — cone angle may be unreliable")

    # --- cone angle -------------------------------------------------------
    # Direction vectors for x = m*y + c  →  (dx, dy) = (m, 1) normalised
    m_left, m_right = left_coeffs[0], right_coeffs[0]
    dir_left = np.array([m_left, 1.0])
    dir_right = np.array([m_right, 1.0])
    dir_left /= np.linalg.norm(dir_left)
    dir_right /= np.linalg.norm(dir_right)

    dot = float(np.clip(np.dot(dir_left, dir_right), -1.0, 1.0))
    angle_deg = float(np.degrees(np.arccos(dot)))

    # --- draw fitted boundary lines on annotated image --------------------
    y_top, y_bot = 0, h - 1
    for coeffs, color in [(left_coeffs, (0, 0, 255)), (right_coeffs, (0, 0, 255))]:
        x_top = int(np.polyval(coeffs, y_top))
        x_bot = int(np.polyval(coeffs, y_bot))
        cv2.line(annotated, (x_top, y_top), (x_bot, y_bot), color, 2)

    # Draw outermost-filtered points (bright, used for line fit)
    for x, y in zip(left_xs_outer, left_ys_outer):
        cv2.circle(annotated, (int(x), int(y)), 3, (255, 255, 0), -1)   # bright cyan
    for x, y in zip(right_xs_outer, right_ys_outer):
        cv2.circle(annotated, (int(x), int(y)), 3, (0, 255, 255), -1)   # bright yellow

    # --- text overlays ----------------------------------------------------
    angle_text = f"Angle: {angle_deg:.2f} deg"
    quality_text = f"Quality: {fit_quality:.2f}"
    ts_angle = cv2.getTextSize(angle_text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0]
    tx = w - ts_angle[0] - 15
    cv2.putText(annotated, angle_text, (tx, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(annotated, quality_text, (tx, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)

    debug_info = {
        **debug_info_base,
        # Outer-filtered points with RANSAC inlier masks
        "left_xs": left_xs_outer,
        "left_ys": left_ys_outer,
        "right_xs": right_xs_outer,
        "right_ys": right_ys_outer,
        "left_inlier_mask": left_inlier_mask,
        "right_inlier_mask": right_inlier_mask,
        "left_line_r2": left_line_r2,
        "right_line_r2": right_line_r2,
        "fit_quality": fit_quality,
        "left_coeffs": left_coeffs,
        "right_coeffs": right_coeffs,
        "left_dir": dir_left,
        "right_dir": dir_right,
        "angle_deg": angle_deg,
    }

    return angle_deg, annotated, debug_info


# ---------------------------------------------------------------------------
# 6-panel debug visualisation
# ---------------------------------------------------------------------------

def create_debug_image(debug_info: dict, image_path: Path) -> np.ndarray:
    """
    Create a 6-panel debug grid showing the full processing pipeline.

    Panels
    ------
    1. Original grayscale
    2. Row sampling visualisation
    3. Left boundary scatter (colour-coded by R²)
    4. Right boundary scatter (colour-coded by R²)
    5. Both boundary clouds + fitted lines
    6. Final annotated result
    """
    gray = debug_info["gray"]
    h, w = gray.shape

    # All accepted points (with matching R² arrays) — used for R²-coloured scatter
    left_xs_all = debug_info.get("left_xs_all", debug_info.get("left_xs", np.array([])))
    left_ys_all = debug_info.get("left_ys_all", debug_info.get("left_ys", np.array([])))
    right_xs_all = debug_info.get("right_xs_all", debug_info.get("right_xs", np.array([])))
    right_ys_all = debug_info.get("right_ys_all", debug_info.get("right_ys", np.array([])))
    left_r2s = debug_info.get("left_r2s", np.array([]))
    right_r2s = debug_info.get("right_r2s", np.array([]))
    # Outermost-filtered points — used for panel 5 + line fit
    left_xs = debug_info.get("left_xs", np.array([]))
    left_ys = debug_info.get("left_ys", np.array([]))
    right_xs = debug_info.get("right_xs", np.array([]))
    right_ys = debug_info.get("right_ys", np.array([]))
    left_coeffs = debug_info.get("left_coeffs", None)
    right_coeffs = debug_info.get("right_coeffs", None)
    left_inlier_mask = debug_info.get("left_inlier_mask", np.ones(len(left_xs), dtype=bool))
    right_inlier_mask = debug_info.get("right_inlier_mask", np.ones(len(right_xs), dtype=bool))
    angle_deg = debug_info.get("angle_deg", None)
    fit_quality = debug_info.get("fit_quality", 0.0)

    # Target cell size (each of the 6 panels)
    cell_w = max(200, w // 3)
    cell_h = max(150, h // 2)

    orig_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    text_col = (0, 255, 255)  # yellow

    def _label(img: np.ndarray, text: str) -> np.ndarray:
        out = img.copy()
        cv2.putText(out, text, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_col, 2)
        return out

    def _resize(img: np.ndarray) -> np.ndarray:
        return cv2.resize(img, (cell_w, cell_h), interpolation=cv2.INTER_AREA)

    # ---- Panel 1: original grayscale ------------------------------------
    p1 = _label(_resize(orig_bgr), "1. Original")

    # ---- Panel 2: row sampling ------------------------------------------
    p2_base = _resize(orig_bgr.copy())
    scale_x = cell_w / w
    scale_y = cell_h / h
    for row_y in range(0, h, ROW_STEP):
        py = int(row_y * scale_y)
        cv2.line(p2_base, (0, py), (cell_w, py), (60, 60, 60), 1)
    p2 = _label(p2_base, "2. Row sampling")

    # ---- Panels 3–5: matplotlib scatter or OpenCV fallback --------------
    _mpl_ok = False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm
        _mpl_ok = True
    except ImportError:
        pass

    def _scatter_panel_mpl(
        xs: np.ndarray,
        ys: np.ndarray,
        r2s: np.ndarray,
        title: str,
        coeffs: np.ndarray | None = None,
        other_xs: np.ndarray | None = None,
        other_ys: np.ndarray | None = None,
        other_coeffs: np.ndarray | None = None,
    ) -> np.ndarray:
        fig, ax = plt.subplots(figsize=(cell_w / 80, cell_h / 80), dpi=80)
        fig.patch.set_facecolor("#1a1a1a")
        ax.set_facecolor("#1a1a1a")
        if len(xs):
            sc = ax.scatter(xs, ys, c=r2s, cmap="plasma", vmin=0, vmax=1,
                            s=6, alpha=0.8)
            plt.colorbar(sc, ax=ax, label="R²")
        if coeffs is not None and len(xs):
            y_range = np.array([0.0, float(h)])
            ax.plot(np.polyval(coeffs, y_range), y_range, "r-", lw=1.5)
        if other_xs is not None and len(other_xs):
            ax.scatter(other_xs, other_ys, c="cyan", s=4, alpha=0.5)
            if other_coeffs is not None:
                y_range = np.array([0.0, float(h)])
                ax.plot(np.polyval(other_coeffs, y_range), y_range, "b-", lw=1.5)
        ax.set_xlim(0, w)
        ax.set_ylim(h, 0)
        ax.set_title(title, color="white", fontsize=8)
        ax.tick_params(colors="white", labelsize=6)
        for sp in ax.spines.values():
            sp.set_edgecolor("#555")
        fig.tight_layout(pad=0.3)
        fig.canvas.draw()
        buf = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
        buf = buf.reshape(fig.canvas.get_width_height()[::-1] + (4,))
        plt.close(fig)
        panel = cv2.cvtColor(buf, cv2.COLOR_RGBA2BGR)
        return cv2.resize(panel, (cell_w, cell_h), interpolation=cv2.INTER_AREA)

    def _scatter_panel_cv(
        xs: np.ndarray,
        ys: np.ndarray,
        r2s: np.ndarray,
        title: str,
        coeffs: np.ndarray | None = None,
        color: tuple = (255, 100, 0),
        other_xs: np.ndarray | None = None,
        other_ys: np.ndarray | None = None,
        other_color: tuple = (0, 255, 200),
        other_coeffs: np.ndarray | None = None,
    ) -> np.ndarray:
        panel = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
        sx, sy = cell_w / max(w, 1), cell_h / max(h, 1)
        for xi, yi in zip(xs, ys):
            cv2.circle(panel, (int(xi * sx), int(yi * sy)), 2, color, -1)
        if other_xs is not None:
            for xi, yi in zip(other_xs, other_ys):
                cv2.circle(panel, (int(xi * sx), int(yi * sy)), 2, other_color, -1)
        if coeffs is not None:
            x0 = int(np.polyval(coeffs, 0) * sx)
            x1 = int(np.polyval(coeffs, h) * sx)
            cv2.line(panel, (x0, 0), (x1, cell_h - 1), (0, 0, 255), 1)
        if other_coeffs is not None:
            x0 = int(np.polyval(other_coeffs, 0) * sx)
            x1 = int(np.polyval(other_coeffs, h) * sx)
            cv2.line(panel, (x0, 0), (x1, cell_h - 1), (255, 0, 0), 1)
        cv2.putText(panel, title, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_col, 1)
        return panel

    if _mpl_ok:
        # Panels 3 & 4: all accepted points coloured by R² (no line — shows raw quality)
        p3 = _scatter_panel_mpl(left_xs_all, left_ys_all, left_r2s,
                                 "3. Left: all accepted (R²)")
        p4 = _scatter_panel_mpl(right_xs_all, right_ys_all, right_r2s,
                                 "4. Right: all accepted (R²)")
        # Panel 5: outermost pts coloured by RANSAC inlier (bright) vs outlier (dim)
        # Encode inlier status as 1.0 / 0.2 so the plasma colormap shows the split
        left_inlier_c = np.where(left_inlier_mask, 1.0, 0.15)
        right_inlier_c = np.where(right_inlier_mask, 1.0, 0.15)
        p5 = _scatter_panel_mpl(
            left_xs, left_ys, left_inlier_c, "5. RANSAC inliers (bright=kept)",
            coeffs=left_coeffs,
            other_xs=right_xs, other_ys=right_ys,
            other_coeffs=right_coeffs,
        )
    else:
        p3 = _scatter_panel_cv(left_xs_all, left_ys_all, left_r2s,
                                "3. Left: all accepted", color=(255, 100, 0))
        p4 = _scatter_panel_cv(right_xs_all, right_ys_all, right_r2s,
                                "4. Right: all accepted", color=(0, 200, 255))
        left_inlier_c = np.where(left_inlier_mask, 1.0, 0.15)
        right_inlier_c = np.where(right_inlier_mask, 1.0, 0.15)
        p5 = _scatter_panel_cv(
            left_xs, left_ys, np.array([]), "5. RANSAC inliers + fit",
            coeffs=left_coeffs, color=(255, 100, 0),
            other_xs=right_xs, other_ys=right_ys,
            other_color=(0, 200, 255), other_coeffs=right_coeffs,
        )

    # ---- Panel 6: final result ------------------------------------------
    if angle_deg is not None:
        final_base = orig_bgr.copy()
        if left_coeffs is not None:
            x0 = int(np.polyval(left_coeffs, 0))
            x1 = int(np.polyval(left_coeffs, h))
            cv2.line(final_base, (x0, 0), (x1, h - 1), (0, 0, 255), 2)
        if right_coeffs is not None:
            x0 = int(np.polyval(right_coeffs, 0))
            x1 = int(np.polyval(right_coeffs, h))
            cv2.line(final_base, (x0, 0), (x1, h - 1), (0, 0, 255), 2)
        p6 = _resize(final_base)
        cv2.putText(p6, f"6. Angle: {angle_deg:.2f} deg", (8, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_col, 2)
        cv2.putText(p6, f"   Quality: {fit_quality:.2f}", (8, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_col, 1)
    else:
        p6 = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
        cv2.putText(p6, "6. Detection failed", (8, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # ---- assemble 2×3 grid ----------------------------------------------
    def _pad(img: np.ndarray) -> np.ndarray:
        ph = cell_h - img.shape[0]
        pw = cell_w - img.shape[1]
        return cv2.copyMakeBorder(img, 0, max(ph, 0), 0, max(pw, 0),
                                  cv2.BORDER_CONSTANT, value=(0, 0, 0))

    row1 = np.hstack([_pad(p1), _pad(p2), _pad(p3)])
    row2 = np.hstack([_pad(p4), _pad(p5), _pad(p6)])
    grid = np.vstack([row1, row2])

    title_h = 50
    grid = cv2.copyMakeBorder(grid, title_h, 0, 0, 0,
                               cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.putText(grid, f"Cone_4 Debug — {image_path.name}",
                (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, text_col, 2)
    return grid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_local_image(base_dir: Path, base_name: str = "Cone_Trial_Image") -> Path:
    """Find image file in directory with various extensions."""
    exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
    for ext in exts:
        candidate = base_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No image named {base_name} with extensions {exts} found in {base_dir}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def process_single_image(
    input_path: Path,
    nozzle_x: float | None,
    no_open: bool,
    top_crop: float,
    debug_mode: bool,
    min_r2: float,
    min_contrast: float,
    output_path: Path | None = None,
) -> None:
    """Process a single image and save outputs."""
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_cone4{input_path.suffix}"

    print(f"[Cone_4] Loading image: {input_path}")

    try:
        angle_deg, annotated, debug_info = detect_cone_angle(
            input_path,
            nozzle_x=nozzle_x,
            top_crop_ratio=top_crop,
            debug=debug_mode,
            min_r2=min_r2,
            min_contrast=min_contrast,
        )

        if angle_deg is None:
            raise RuntimeError(debug_info.get("error", "Detection failed"))

        print(f"[Cone_4] Detected cone angle: {angle_deg:.2f} degrees")
        print(f"[Cone_4] Left accepted: {debug_info['left_points_accepted']}  "
              f"Right accepted: {debug_info['right_points_accepted']}")
        print(f"[Cone_4] Sigmoid R² mean — left: {debug_info['left_r2_mean']:.3f}  "
              f"right: {debug_info['right_r2_mean']:.3f}")
        print(f"[Cone_4] Line R² — left: {debug_info['left_line_r2']:.3f}  "
              f"right: {debug_info['right_line_r2']:.3f}  "
              f"fit_quality: {debug_info['fit_quality']:.3f}")

        cv2.imwrite(str(output_path), annotated)
        print(f"[Cone_4] Saved annotated image: {output_path}")

        if debug_mode:
            debug_dir = CURRENT_DIR / "cone_4_debug"
            debug_dir.mkdir(exist_ok=True)
            debug_img = create_debug_image(debug_info, input_path)
            dbg_path = debug_dir / f"{input_path.stem}_debug.png"
            cv2.imwrite(str(dbg_path), debug_img)
            print(f"[Cone_4] Saved debug image: {dbg_path}")

        if not no_open:
            try:
                if sys.platform == "darwin":
                    import subprocess
                    subprocess.run(["open", str(output_path)], check=False)
                    if debug_mode:
                        dbg_path = CURRENT_DIR / "cone_4_debug" / f"{input_path.stem}_debug.png"
                        subprocess.run(["open", str(dbg_path)], check=False)
                else:
                    cv2.imshow("Cone_4 Result", annotated)
                    cv2.waitKey(0)
                    cv2.destroyAllWindows()
            except Exception as e:
                print(f"[Cone_4] Warning: could not open image: {e}")

    except Exception as e:
        print(f"[Cone_4] Error: {e}")
        raise


def main() -> None:
    """Main entry point."""
    try:
        default_input = _find_local_image(CURRENT_DIR)
    except FileNotFoundError:
        default_input = None

    parser = argparse.ArgumentParser(
        description="Sigmoid-profile cone angle detection (Cone_4)"
    )
    parser.add_argument("--input", type=Path, default=default_input,
                        help="Path to input image")
    parser.add_argument("--output", type=Path, default=None,
                        help="Path to output annotated image")
    parser.add_argument("--nozzle-x", type=float, default=None,
                        help="X-coordinate of nozzle (optional)")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not auto-open output image")
    parser.add_argument("--top-crop", type=float, default=TOP_CROP_RATIO,
                        help=f"Fraction to crop from image top (default {TOP_CROP_RATIO})")
    parser.add_argument("--no-debug", action="store_true",
                        help="Disable debug overlay and debug image")
    parser.add_argument("--min-r2", type=float, default=MIN_R2,
                        help=f"Minimum sigmoid fit R² (default {MIN_R2})")
    parser.add_argument("--min-contrast", type=float, default=MIN_CONTRAST,
                        help=f"Minimum intensity contrast (default {MIN_CONTRAST})")
    args = parser.parse_args()

    input_path = args.input
    if input_path is None:
        for ext in [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]:
            candidate = CURRENT_DIR / f"Spray_1{ext}"
            if candidate.exists():
                input_path = candidate
                break

    if input_path is None or not input_path.exists():
        raise FileNotFoundError(
            "No input image specified. Use --input or place Cone_Trial_Image.* "
            "or Spray_1.* in the script directory."
        )

    process_single_image(
        input_path=input_path,
        nozzle_x=args.nozzle_x,
        no_open=args.no_open,
        top_crop=args.top_crop,
        debug_mode=not args.no_debug,
        min_r2=args.min_r2,
        min_contrast=args.min_contrast,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
