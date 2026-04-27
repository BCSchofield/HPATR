"""
Cone angle detection — blur-envelope edge finding + RANSAC line fitting.

WHY THIS APPROACH:
    Effervescent atomisation produces a complex spray of ligaments and droplets.
    The previous sigmoid-per-row approach was fragile: a sigmoid inflection point
    can land anywhere along the intensity gradient and cannot distinguish the outer
    cone edge from interior spray transitions.

    Instead:
    1. Heavy Gaussian blur (σ ≈ 15 px) merges individual ligaments into a smooth
       intensity envelope.  The spray body becomes a single connected dark blob.
    2. Per row, scan from the image edge inward — the first pixel that falls below
       a threshold IS the outer boundary of that blob, by definition.
    3. RANSAC fits a line to those boundary points, robustly discarding the small
       number of outlier rows caused by stray droplets, nozzle hardware, or
       background noise.

OUTPUT:
    Annotated image + 6-panel debug grid.
    Bright yellow/cyan dots = RANSAC inliers used for the final fit.
    Dim dots = RANSAC outliers (rejected).
    Red lines = fitted cone edges.
"""

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np

CURRENT_DIR  = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config_loader import get_imaging_config  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Algorithm parameters
# ─────────────────────────────────────────────────────────────────────────────
TOP_CROP_RATIO   = 0.30    # fraction of image height to remove from the top
BLUR_SIGMA       = 7.5     # Gaussian σ (px) — merges ligaments into an envelope
THRESHOLD_FRAC   = 0.85    # spray threshold = bg_level × this value
RANSAC_THRESHOLD = 10.0    # max horizontal distance (px) to count as inlier
MIN_PTS          = 20      # minimum edge points per side to attempt a line fit
ROW_STEP         = 1       # process every Nth row (1 = every row)


# ─────────────────────────────────────────────────────────────────────────────
# Edge detection
# ─────────────────────────────────────────────────────────────────────────────

def _find_outer_edge_points(
    gray: np.ndarray,
    blur_sigma: float = BLUR_SIGMA,
    threshold_frac: float = THRESHOLD_FRAC,
    row_step: int = ROW_STEP,
    center_x: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
    """
    Find the outermost spray boundary point in each image row.

    Scans from the image edges inward after blurring, so the result is
    always the outer envelope of the spray, never an interior transition.

    Returns
    -------
    left_xs, left_ys, right_xs, right_ys : np.ndarray  (px coords)
    blurred  : np.ndarray (float32) — smoothed image used for detection
    bg_level : float — estimated background intensity (0–255)
    threshold: float — dark/light cutoff used
    """
    h, w = gray.shape

    # Large blur merges gaps between ligaments → continuous spray blob
    blurred = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), sigmaX=blur_sigma)

    # Background level: 80th percentile of corner pixels (always background
    # in backlit shadowgraph images)
    cs = max(20, min(w, h) // 8)
    corners = np.concatenate([
        blurred[:cs,   :cs  ].ravel(),
        blurred[:cs,   w-cs:].ravel(),
        blurred[h-cs:, :cs  ].ravel(),
        blurred[h-cs:, w-cs:].ravel(),
    ])
    bg_level  = float(np.percentile(corners, 80))
    threshold = bg_level * threshold_frac

    # Per-row spray centre: smooth each row with a wide moving average then
    # take the darkest column.  This adapts to the spray being very narrow near
    # the nozzle — a single global centre_x can end up on the WRONG SIDE of the
    # spray edge in those upper rows, causing the left scan to miss the boundary.
    if center_x is not None:
        # Caller-supplied override: use it for every row
        row_centers = np.full(h, float(center_x))
    else:
        win = max(3, w // 10)
        kernel = np.ones(win, dtype=np.float32) / win
        # Smooth each row to suppress single stray-dark pixels driving the argmin
        blurred_smooth = np.apply_along_axis(
            lambda r: np.convolve(r, kernel, mode="same"), axis=1, arr=blurred
        )
        raw_centers = np.argmin(blurred_smooth, axis=1).astype(np.float32)  # (h,)
        # Smooth per-row centres across rows so the divider doesn't jitter
        smooth_win = max(3, min(31, h // 15))
        row_centers = np.convolve(
            raw_centers, np.ones(smooth_win) / smooth_win, mode="same"
        )

    row_centers = np.clip(row_centers, w // 4, 3 * w // 4)

    # Per-row edge scan: first dark pixel from each image edge toward the centre
    left_xs:  list[float] = []
    left_ys:  list[float] = []
    right_xs: list[float] = []
    right_ys: list[float] = []

    for y in range(0, h, row_step):
        cx  = int(row_centers[y])
        row = blurred[y]

        # Left edge: scan x = 0 → cx (outermost dark pixel on left side)
        for x in range(cx):
            if row[x] < threshold:
                left_xs.append(float(x))
                left_ys.append(float(y))
                break

        # Right edge: scan x = w-1 → cx (outermost dark pixel on right side)
        for x in range(w - 1, cx, -1):
            if row[x] < threshold:
                right_xs.append(float(x))
                right_ys.append(float(y))
                break

    return (np.array(left_xs, dtype=np.float32),
            np.array(left_ys,  dtype=np.float32),
            np.array(right_xs, dtype=np.float32),
            np.array(right_ys, dtype=np.float32),
            blurred, bg_level, threshold)


# ─────────────────────────────────────────────────────────────────────────────
# RANSAC line fit  (x = m·y + c)
# ─────────────────────────────────────────────────────────────────────────────

def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 0.0 if ss_tot < 1e-12 else float(1.0 - ss_res / ss_tot)


def _line_r2(x_vals: np.ndarray, y_vals: np.ndarray, coeffs: np.ndarray) -> float:
    return _r2(x_vals, np.polyval(coeffs, y_vals))


def _ransac_line(
    xs: np.ndarray,
    ys: np.ndarray,
    n_iterations: int = 300,
    inlier_threshold: float = RANSAC_THRESHOLD,
    min_inlier_ratio: float = 0.3,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit x = m·y + c using RANSAC.

    1. Randomly sample 2 points → fit a candidate line.
    2. Count all points within inlier_threshold px — these are the inliers.
    3. Repeat n_iterations times, keep the sample with the most inliers.
    4. Refit using all inliers of the best sample.

    Returns coeffs [m, c] and boolean inlier_mask over xs/ys.
    """
    if len(xs) < 2:
        c = float(np.mean(xs)) if len(xs) else 0.0
        return np.array([0.0, c]), np.ones(len(xs), dtype=bool)

    best_coeffs  = np.polyfit(ys, xs, deg=1)
    best_inliers = np.ones(len(xs), dtype=bool)
    best_n       = 0
    rng          = np.random.default_rng(seed=42)

    for _ in range(n_iterations):
        idx = rng.choice(len(xs), size=2, replace=False)
        if abs(ys[idx[1]] - ys[idx[0]]) < 1e-6:
            continue
        coeffs  = np.polyfit(ys[idx], xs[idx], deg=1)
        dist    = np.abs(xs - np.polyval(coeffs, ys))
        inliers = dist < inlier_threshold
        n       = int(inliers.sum())
        if n > best_n:
            best_n       = n
            best_inliers = inliers
            best_coeffs  = coeffs

    if best_n >= max(2, int(min_inlier_ratio * len(xs))):
        best_coeffs = np.polyfit(ys[best_inliers], xs[best_inliers], deg=1)
    else:
        print(f"[Cone_4] RANSAC: low inlier count ({best_n}/{len(xs)}), using plain polyfit")
        best_inliers = np.ones(len(xs), dtype=bool)

    return best_coeffs, best_inliers


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def detect_cone_angle(
    image_path: Path,
    nozzle_x: float | None = None,
    top_crop_ratio: float = TOP_CROP_RATIO,
    debug: bool = True,
    blur_sigma: float = BLUR_SIGMA,
    threshold_frac: float = THRESHOLD_FRAC,
    ransac_threshold: float = RANSAC_THRESHOLD,
    # legacy kwargs — accepted but ignored
    min_r2: float = 0.0,
    min_contrast: float = 0.0,
) -> tuple[float | None, np.ndarray, dict]:
    """
    Detect spray cone angle from a single image.

    Parameters
    ----------
    image_path : Path
    nozzle_x : float, optional
        Horizontal spray centre column.  Detected automatically if None.
    top_crop_ratio : float
        Fraction of image height to remove from the top before processing.
    blur_sigma : float
        Gaussian blur σ.  10–20 px works for typical shadowgraph images.
        Larger values merge more features but soften the edge estimate.
    threshold_frac : float
        Pixels below bg_level × threshold_frac are counted as spray.
        0.85 means "15% darker than background = spray".
    ransac_threshold : float
        RANSAC inlier distance in pixels.

    Returns
    -------
    angle_degrees : float or None
    annotated_image : np.ndarray (BGR)
    debug_info : dict
    """
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img_raw = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        raise ValueError(f"Cannot load image: {image_path}")

    gray = (cv2.cvtColor(img_raw, cv2.COLOR_BGR2GRAY)
            if len(img_raw.shape) == 3 else img_raw.copy())
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    h_orig, w = gray.shape
    top_px = int(h_orig * top_crop_ratio)
    gray   = gray[top_px:, :]
    h, w   = gray.shape
    print(f"[Cone_4] Image {w}×{h_orig} → cropped {w}×{h} (removed top {top_px}px)")

    cx = int(nozzle_x) if nozzle_x is not None else None
    left_xs, left_ys, right_xs, right_ys, blurred, bg_level, threshold = \
        _find_outer_edge_points(gray, blur_sigma, threshold_frac, ROW_STEP, cx)

    n_left, n_right = len(left_xs), len(right_xs)
    print(f"[Cone_4] Edge points — left: {n_left}, right: {n_right}")
    print(f"[Cone_4] Background: {bg_level:.1f}   threshold: {threshold:.1f}")

    annotated = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    debug_info_base = {
        "gray": gray, "blurred": blurred, "image_path": image_path,
        "bg_level": bg_level, "threshold": threshold,
        "left_xs": left_xs, "left_ys": left_ys,
        "right_xs": right_xs, "right_ys": right_ys,
        # legacy aliases so existing callers don't break
        "left_xs_all": left_xs, "left_ys_all": left_ys,
        "right_xs_all": right_xs, "right_ys_all": right_ys,
        "left_r2s":  np.ones(n_left),  "right_r2s":  np.ones(n_right),
        "left_r2_mean": 1.0, "right_r2_mean": 1.0,
        "left_points_accepted": n_left, "right_points_accepted": n_right,
        "top_px": top_px, "orig_h": h_orig,
    }

    fail_msg = None
    if n_left < MIN_PTS:
        fail_msg = f"Insufficient left points ({n_left} < {MIN_PTS})"
    if n_right < MIN_PTS:
        m2 = f"Insufficient right points ({n_right} < {MIN_PTS})"
        fail_msg = (fail_msg + "; " + m2) if fail_msg else m2

    if fail_msg:
        print(f"[Cone_4] Warning: {fail_msg}")
        cv2.putText(annotated, fail_msg[:60], (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        debug_info_base.update({"error": fail_msg, "fit_quality": 0.0,
                                 "left_line_r2": 0.0, "right_line_r2": 0.0})
        return None, annotated, debug_info_base

    left_coeffs,  left_mask  = _ransac_line(left_xs,  left_ys,
                                             inlier_threshold=ransac_threshold)
    right_coeffs, right_mask = _ransac_line(right_xs, right_ys,
                                             inlier_threshold=ransac_threshold)
    print(f"[Cone_4] RANSAC inliers — left: {left_mask.sum()}/{n_left}, "
          f"right: {right_mask.sum()}/{n_right}")

    left_r2  = _line_r2(left_xs[left_mask],   left_ys[left_mask],   left_coeffs)
    right_r2 = _line_r2(right_xs[right_mask], right_ys[right_mask], right_coeffs)
    quality  = (left_r2 + right_r2) / 2.0
    if quality < 0.6:
        print(f"[Cone_4] Warning: low fit quality ({quality:.2f})")

    m_l, m_r = left_coeffs[0], right_coeffs[0]
    dl = np.array([m_l, 1.0]); dl /= np.linalg.norm(dl)
    dr = np.array([m_r, 1.0]); dr /= np.linalg.norm(dr)
    angle_deg = float(np.degrees(np.arccos(float(np.clip(np.dot(dl, dr), -1.0, 1.0)))))

    # Draw boundary points (bright = inlier, dim = outlier)
    for x, y, ok in zip(left_xs,  left_ys,  left_mask):
        cv2.circle(annotated, (int(x), int(y)), 2, (255, 255, 0) if ok else (70, 70, 0), -1)
    for x, y, ok in zip(right_xs, right_ys, right_mask):
        cv2.circle(annotated, (int(x), int(y)), 2, (0, 255, 255) if ok else (0, 70, 70), -1)

    # Draw fitted lines
    for coeffs in (left_coeffs, right_coeffs):
        cv2.line(annotated,
                 (int(np.polyval(coeffs, 0)),   0),
                 (int(np.polyval(coeffs, h-1)), h-1),
                 (0, 0, 255), 2)

    angle_text = f"Angle: {angle_deg:.2f} deg"
    ts = cv2.getTextSize(angle_text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0]
    tx = w - ts[0] - 15
    cv2.putText(annotated, angle_text,
                (tx, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(annotated, f"Quality: {quality:.2f}",
                (tx, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)

    debug_info = {
        **debug_info_base,
        "left_inlier_mask":  left_mask,  "right_inlier_mask": right_mask,
        "left_line_r2":  left_r2, "right_line_r2": right_r2, "fit_quality": quality,
        "left_coeffs":   left_coeffs,  "right_coeffs":  right_coeffs,
        "left_dir": dl, "right_dir": dr, "angle_deg": angle_deg,
    }
    return angle_deg, annotated, debug_info


# ─────────────────────────────────────────────────────────────────────────────
# 6-panel debug visualisation
# ─────────────────────────────────────────────────────────────────────────────

def create_debug_image(debug_info: dict, image_path: Path) -> np.ndarray:
    """
    6-panel debug grid.

    1. Original grayscale
    2. Blurred image with threshold contour (shows what the detector sees)
    3. Left boundary scatter  (bright = RANSAC inlier, dim = outlier)
    4. Right boundary scatter
    5. Both sides + RANSAC lines
    6. Final annotated result
    """
    gray     = debug_info["gray"]
    blurred  = debug_info.get("blurred")
    h, w     = gray.shape
    threshold = debug_info.get("threshold", None)

    left_xs  = debug_info.get("left_xs",  np.array([]))
    left_ys  = debug_info.get("left_ys",  np.array([]))
    right_xs = debug_info.get("right_xs", np.array([]))
    right_ys = debug_info.get("right_ys", np.array([]))
    left_mask  = debug_info.get("left_inlier_mask",  np.ones(len(left_xs),  dtype=bool))
    right_mask = debug_info.get("right_inlier_mask", np.ones(len(right_xs), dtype=bool))
    left_coeffs  = debug_info.get("left_coeffs",  None)
    right_coeffs = debug_info.get("right_coeffs", None)
    angle_deg    = debug_info.get("angle_deg",    None)
    fit_quality  = debug_info.get("fit_quality",  0.0)

    cell_w = max(200, w // 3)
    cell_h = max(150, h // 2)
    orig_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    text_col = (0, 255, 255)

    def _label(img: np.ndarray, text: str) -> np.ndarray:
        out = img.copy()
        cv2.putText(out, text, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_col, 2)
        return out

    def _resize(img: np.ndarray) -> np.ndarray:
        return cv2.resize(img, (cell_w, cell_h), interpolation=cv2.INTER_AREA)

    # ── Panel 1: full original with crop line ────────────────────────────────
    top_px  = debug_info.get("top_px", 0)
    orig_h  = debug_info.get("orig_h", h)
    full_img = cv2.imread(str(image_path))
    if full_img is None:
        full_img = cv2.copyMakeBorder(orig_bgr, top_px, 0, 0, 0,
                                       cv2.BORDER_CONSTANT, value=0)
    if full_img.ndim == 2:
        full_img = cv2.cvtColor(full_img, cv2.COLOR_GRAY2BGR)
    if top_px > 0:
        overlay = full_img.copy()
        cv2.rectangle(overlay, (0, 0), (full_img.shape[1] - 1, top_px - 1),
                      (0, 0, 200), -1)
        cv2.addWeighted(overlay, 0.45, full_img, 0.55, 0, full_img)
        cv2.line(full_img, (0, top_px), (full_img.shape[1] - 1, top_px),
                 (0, 0, 255), 2)
    p1 = _label(_resize(full_img), "1. Original (red = cropped)")

    # ── Panel 2: blurred image + threshold contour ───────────────────────────
    if blurred is not None:
        blur_u8 = cv2.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
        p2_base = cv2.cvtColor(blur_u8, cv2.COLOR_GRAY2BGR)
        if threshold is not None:
            _, tmask = cv2.threshold(blur_u8, int(threshold), 255, cv2.THRESH_BINARY_INV)
            cnts, _ = cv2.findContours(tmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(p2_base, cnts, -1, (0, 0, 255), 1)
        p2 = _label(_resize(p2_base), "2. Blurred + threshold")
    else:
        p2 = _label(_resize(orig_bgr.copy()), "2. (no blur data)")

    # ── Panels 3–5: scatter plots ─────────────────────────────────────────────
    _mpl_ok = False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        _mpl_ok = True
    except ImportError:
        pass

    def _scatter_mpl(
        xs: np.ndarray, ys: np.ndarray, colors: np.ndarray, title: str,
        left_c: np.ndarray | None = None, left_cy: np.ndarray | None = None,
        right_c: np.ndarray | None = None, right_cy: np.ndarray | None = None,
        l_coeffs: np.ndarray | None = None, r_coeffs: np.ndarray | None = None,
    ) -> np.ndarray:
        fig, ax = plt.subplots(figsize=(cell_w / 80, cell_h / 80), dpi=80)
        fig.patch.set_facecolor("#1a1a1a")
        ax.set_facecolor("#1a1a1a")
        if len(xs):
            sc = ax.scatter(xs, ys, c=colors, cmap="plasma", vmin=0, vmax=1, s=5, alpha=0.85)
            plt.colorbar(sc, ax=ax)
        if left_c is not None and len(left_c):
            ax.scatter(left_c, left_cy, c="yellow", s=5, alpha=0.7, marker="x")
        if right_c is not None and len(right_c):
            ax.scatter(right_c, right_cy, c="cyan", s=5, alpha=0.7, marker="x")
        for coeffs, col in [(l_coeffs, "red"), (r_coeffs, "blue")]:
            if coeffs is not None:
                yr = np.array([0.0, float(h)])
                ax.plot(np.polyval(coeffs, yr), yr, color=col, lw=1.5)
        ax.set_xlim(0, w); ax.set_ylim(h, 0)
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

    # Inlier/outlier as plasma colour: 1.0 = inlier (bright), 0.15 = outlier (dim)
    left_c  = np.where(left_mask,  1.0, 0.15)
    right_c = np.where(right_mask, 1.0, 0.15)

    if _mpl_ok:
        p3 = _scatter_mpl(left_xs,  left_ys,  left_c,
                          "3. Left boundary (bright=inlier)")
        p4 = _scatter_mpl(right_xs, right_ys, right_c,
                          "4. Right boundary (bright=inlier)")
        # Panel 5: both sides together with lines
        combined_c = np.concatenate([left_c, right_c])
        combined_x = np.concatenate([left_xs, right_xs])
        combined_y = np.concatenate([left_ys, right_ys])
        p5 = _scatter_mpl(combined_x, combined_y, combined_c,
                          "5. Both sides + RANSAC lines",
                          l_coeffs=left_coeffs, r_coeffs=right_coeffs)
    else:
        def _scatter_cv(xs, ys, mask, title, color_in, color_out,
                        l_coeffs=None, r_coeffs=None):
            panel = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
            sx, sy = cell_w / max(w, 1), cell_h / max(h, 1)
            for xi, yi, ok in zip(xs, ys, mask):
                cv2.circle(panel, (int(xi*sx), int(yi*sy)), 2,
                           color_in if ok else color_out, -1)
            for c, col in [(l_coeffs, (255, 0, 0)), (r_coeffs, (0, 0, 255))]:
                if c is not None:
                    cv2.line(panel,
                             (int(np.polyval(c, 0)*sx), 0),
                             (int(np.polyval(c, h)*sx), cell_h-1), col, 1)
            cv2.putText(panel, title, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_col, 1)
            return panel
        p3 = _scatter_cv(left_xs,  left_ys,  left_mask,  "3. Left",
                         (255,255,0), (70,70,0))
        p4 = _scatter_cv(right_xs, right_ys, right_mask, "4. Right",
                         (0,255,255), (0,70,70))
        all_xs = np.concatenate([left_xs, right_xs])
        all_ys = np.concatenate([left_ys, right_ys])
        all_mask = np.concatenate([left_mask, right_mask])
        p5 = _scatter_cv(all_xs, all_ys, all_mask, "5. Both + lines",
                         (200,200,0), (60,60,0),
                         l_coeffs=left_coeffs, r_coeffs=right_coeffs)

    # ── Panel 6: final result ─────────────────────────────────────────────────
    if angle_deg is not None:
        p6_base = orig_bgr.copy()
        for coeffs in (left_coeffs, right_coeffs):
            if coeffs is not None:
                cv2.line(p6_base,
                         (int(np.polyval(coeffs, 0)),   0),
                         (int(np.polyval(coeffs, h-1)), h-1),
                         (0, 0, 255), 2)
        p6 = _resize(p6_base)
        cv2.putText(p6, f"6. Angle: {angle_deg:.2f} deg",
                    (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_col, 2)
        cv2.putText(p6, f"   Quality: {fit_quality:.2f}",
                    (8, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_col, 1)
    else:
        p6 = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
        cv2.putText(p6, "6. Detection failed",
                    (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # ── Assemble 2×3 grid ────────────────────────────────────────────────────
    def _pad(img: np.ndarray) -> np.ndarray:
        ph = cell_h - img.shape[0]
        pw = cell_w - img.shape[1]
        return cv2.copyMakeBorder(img, 0, max(ph, 0), 0, max(pw, 0),
                                  cv2.BORDER_CONSTANT, value=(0, 0, 0))

    grid = np.vstack([
        np.hstack([_pad(p1), _pad(p2), _pad(p3)]),
        np.hstack([_pad(p4), _pad(p5), _pad(p6)]),
    ])

    title_h = 50
    grid = cv2.copyMakeBorder(grid, title_h, 0, 0, 0,
                               cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.putText(grid, f"Cone_4 Debug — {image_path.name}",
                (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, text_col, 2)
    return grid


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_local_image(base_dir: Path, base_name: str = "Cone_Trial_Image") -> Path:
    for ext in [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]:
        candidate = base_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No image named '{base_name}' with known extensions found in {base_dir}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def process_single_image(
    input_path: Path,
    nozzle_x: float | None,
    no_open: bool,
    top_crop: float,
    debug_mode: bool,
    blur_sigma: float,
    threshold_frac: float,
    ransac_threshold: float,
    output_path: Path | None = None,
) -> None:
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_cone4{input_path.suffix}"

    print(f"[Cone_4] Loading: {input_path}")

    angle_deg, annotated, debug_info = detect_cone_angle(
        input_path,
        nozzle_x=nozzle_x,
        top_crop_ratio=top_crop,
        debug=debug_mode,
        blur_sigma=blur_sigma,
        threshold_frac=threshold_frac,
        ransac_threshold=ransac_threshold,
    )

    if angle_deg is None:
        raise RuntimeError(debug_info.get("error", "Detection failed"))

    print(f"[Cone_4] Cone angle: {angle_deg:.2f}°")
    print(f"[Cone_4] Left / right points: "
          f"{debug_info['left_points_accepted']} / {debug_info['right_points_accepted']}")
    print(f"[Cone_4] Line R² — left: {debug_info['left_line_r2']:.3f}  "
          f"right: {debug_info['right_line_r2']:.3f}  "
          f"quality: {debug_info['fit_quality']:.3f}")

    cv2.imwrite(str(output_path), annotated)
    print(f"[Cone_4] Saved: {output_path}")

    if debug_mode:
        debug_dir = CURRENT_DIR / "cone_4_debug"
        debug_dir.mkdir(exist_ok=True)
        dbg_img  = create_debug_image(debug_info, input_path)
        dbg_path = debug_dir / f"{input_path.stem}_debug.png"
        cv2.imwrite(str(dbg_path), dbg_img)
        print(f"[Cone_4] Debug image: {dbg_path}")

    if not no_open:
        try:
            if sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", str(output_path)], check=False)
                if debug_mode:
                    subprocess.run(["open", str(dbg_path)], check=False)
            else:
                cv2.imshow("Cone_4 Result", annotated)
                cv2.waitKey(0)
                cv2.destroyAllWindows()
        except Exception as e:
            print(f"[Cone_4] Warning: could not open image: {e}")


def main() -> None:
    try:
        default_input = _find_local_image(CURRENT_DIR, "Spray_1")
    except FileNotFoundError:
        default_input = None

    parser = argparse.ArgumentParser(
        description="Blur-envelope cone angle detection (Cone_4)"
    )
    parser.add_argument("--input",      type=Path,  default=default_input)
    parser.add_argument("--output",     type=Path,  default=None)
    parser.add_argument("--nozzle-x",  type=float, default=None)
    parser.add_argument("--no-open",   action="store_true")
    parser.add_argument("--top-crop",  type=float, default=TOP_CROP_RATIO,
                        help=f"Top crop fraction (default {TOP_CROP_RATIO})")
    parser.add_argument("--no-debug",  action="store_true")
    parser.add_argument("--blur-sigma", type=float, default=BLUR_SIGMA,
                        help=f"Gaussian blur σ in px (default {BLUR_SIGMA})")
    parser.add_argument("--threshold-frac", type=float, default=THRESHOLD_FRAC,
                        help=f"Spray threshold fraction (default {THRESHOLD_FRAC})")
    parser.add_argument("--ransac-threshold", type=float, default=RANSAC_THRESHOLD,
                        help=f"RANSAC inlier distance in px (default {RANSAC_THRESHOLD})")
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
            "No input image found. Use --input or place Spray_1.* in the script directory."
        )

    process_single_image(
        input_path=input_path,
        nozzle_x=args.nozzle_x,
        no_open=args.no_open,
        top_crop=args.top_crop,
        debug_mode=not args.no_debug,
        blur_sigma=args.blur_sigma,
        threshold_frac=args.threshold_frac,
        ransac_threshold=args.ransac_threshold,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
