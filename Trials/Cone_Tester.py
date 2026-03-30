# Merge term 1
"""
Cone detection script for spray angle measurement using TIFF frames.

Loads a frame, extracts the spray cone silhouette, fits left/right edges,
and overlays the measured angle onto the image.
"""
import argparse
import os
import time
from pathlib import Path

import cv2
import numpy as np

# Allow running from repo root
import sys
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config_loader import get_imaging_config  # noqa: E402


def _load_first_frame(image_path: Path) -> np.ndarray:
    """
    Load the first frame of a (possibly multi-page) TIFF.
    Falls back to cv2.imread if imreadmulti is not needed.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")

    frame = None
    if image_path.suffix.lower() in {".tif", ".tiff"}:
        # Try multi-frame read first for TIFF
        ret, frames = cv2.imreadmulti(str(image_path), [], cv2.IMREAD_COLOR)
        if ret and len(frames) > 0:
            frame = frames[0]
        else:
            frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    else:
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)

    if frame is None:
        raise FileNotFoundError(f"Unable to load image: {image_path}")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Expected 3-channel BGR image")
    return frame


def _find_local_image(base_dir: Path, base_name: str = "Nicer_Spray") -> Path:
    """
    Find an image named Cone_Trial_Image.* in the given directory.
    Supports common formats (tiff, tif, png, jpg, jpeg, bmp).
    """
    exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
    for ext in exts:
        candidate = base_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No image named {base_name} with extensions {exts} found in {base_dir}"
    )


def _preprocess(gray: np.ndarray) -> np.ndarray:
    """CLAHE + blur to stabilize thresholding (tuned for flashed white background)."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    blur = cv2.GaussianBlur(eq, (3, 3), 0)
    return blur


def _largest_contour(mask: np.ndarray):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _compute_cone_angle(hull: np.ndarray):
    """
    From a convex hull, pick apex (highest y), left/right bases, and angle.
    Returns (apex, left_base, right_base, angle_deg).
    """
    hull_points = hull[:, 0, :]  # shape (N,2)
    if len(hull_points) < 3:
        return None, None, None, None

    apex_idx = np.argmin(hull_points[:, 1])
    apex = hull_points[apex_idx]

    left_candidates = hull_points[hull_points[:, 0] < apex[0]]
    right_candidates = hull_points[hull_points[:, 0] > apex[0]]

    if len(left_candidates) == 0:
        left_candidates = hull_points[hull_points[:, 0] == hull_points[:, 0].min()]
    if len(right_candidates) == 0:
        right_candidates = hull_points[hull_points[:, 0] == hull_points[:, 0].max()]

    def farthest(pt_set):
        d2 = np.sum((pt_set - apex) ** 2, axis=1)
        return pt_set[int(np.argmax(d2))]

    left_base = farthest(left_candidates)
    right_base = farthest(right_candidates)

    vec_left = left_base - apex
    vec_right = right_base - apex

    dot = float(np.dot(vec_left, vec_right))
    denom = np.linalg.norm(vec_left) * np.linalg.norm(vec_right)
    if denom == 0:
        return apex, left_base, right_base, None
    angle_rad = np.arccos(np.clip(dot / denom, -1.0, 1.0))
    angle_deg = np.degrees(angle_rad)
    return apex, left_base, right_base, angle_deg


def _fit_edge_lines(contour: np.ndarray, apex: np.ndarray, band_frac: float = 0.35):
    """
    Fit left/right edge lines (x = m*y + b) using points near the top portion of the cone.
    band_frac: fraction of cone height (from apex downward) to use for fitting.
    Returns (m_left, b_left), (m_right, b_right), angle_deg (acute).
    """
    pts = contour[:, 0, :].astype(float)
    apex_y = float(apex[1])
    apex_x = float(apex[0])
    max_y = pts[:, 1].max()
    cone_height = max_y - apex_y
    if cone_height <= 0:
        return None, None, None

    band_limit = apex_y + cone_height * band_frac
    band_pts = pts[pts[:, 1] <= band_limit]
    if len(band_pts) < 10:
        band_pts = pts

    left_pts = band_pts[band_pts[:, 0] <= apex_x]
    right_pts = band_pts[band_pts[:, 0] > apex_x]

    def fit_line(selected):
        if selected is None or len(selected) < 2:
            return None
        y = selected[:, 1]
        x = selected[:, 0]
        A = np.vstack([y, np.ones_like(y)]).T
        m, b = np.linalg.lstsq(A, x, rcond=None)[0]
        return m, b

    left_line = fit_line(left_pts)
    right_line = fit_line(right_pts)

    if left_line is None or right_line is None:
        return None, None, None

    m1, b1 = left_line
    m2, b2 = right_line
    theta = abs(np.arctan(m1) - np.arctan(m2))
    theta_deg = np.degrees(theta)
    # Acute angle
    if theta_deg > 180:
        theta_deg = 360 - theta_deg
    if theta_deg > 90:
        theta_deg = 180 - theta_deg

    return (m1, b1), (m2, b2), theta_deg


def _fallback_angle_from_extents(contour: np.ndarray, apex: np.ndarray):
    """
    Fallback: use extreme left/right points below apex and fit lines.
    Returns (m_left, b_left), (m_right, b_right), angle_deg or (None, None, None).
    """
    pts = contour[:, 0, :].astype(float)
    below = pts[pts[:, 1] >= apex[1]]
    if len(below) < 4:
        return None, None, None
    # pick farthest left/right below apex
    left_pt = below[np.argmin(below[:, 0])]
    right_pt = below[np.argmax(below[:, 0])]

    # define simple lines apex->left, apex->right
    def line_from_two(p1, p2):
        y1, x1 = p1[1], p1[0]
        y2, x2 = p2[1], p2[0]
        if y2 == y1:
            return None
        m = (x2 - x1) / (y2 - y1)
        b = x1 - m * y1
        return m, b

    left_line = line_from_two(apex, left_pt)
    right_line = line_from_two(apex, right_pt)
    if left_line is None or right_line is None:
        return None, None, None

    m1, _ = left_line
    m2, _ = right_line
    theta = abs(np.arctan(m1) - np.arctan(m2))
    theta_deg = np.degrees(theta)
    if theta_deg > 180:
        theta_deg = 360 - theta_deg
    if theta_deg > 90:
        theta_deg = 180 - theta_deg
    return left_line, right_line, theta_deg


def _pick_contour(mask: np.ndarray, apex: np.ndarray | None):
    """
    Choose contour that contains the apex if provided; otherwise largest contour.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    if apex is None:
        return max(contours, key=cv2.contourArea)
    # Prefer contour that contains the apex
    containing = []
    for c in contours:
        if cv2.pointPolygonTest(c, (float(apex[0]), float(apex[1])), False) >= 0:
            containing.append(c)
    if containing:
        return max(containing, key=cv2.contourArea)
    return max(contours, key=cv2.contourArea)


def _get_apex_interactive(img_bgr: np.ndarray, use_matplotlib: bool = False) -> np.ndarray:
    """
    Ask user to click the apex. Returns np.array([x, y]).
    Tries OpenCV window first; falls back to matplotlib if requested or if OpenCV fails.
    """
    if not use_matplotlib:
        clicked = {"pt": None}

        def on_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                clicked["pt"] = np.array([x, y])

        win_name = "Click apex (highest point); press q to cancel"
        try:
            cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
            cv2.imshow(win_name, img_bgr)
            cv2.setMouseCallback(win_name, on_mouse)
            print("[Cone_Tester] Please click the apex (highest point) of the cone...")
            while clicked["pt"] is None:
                key = cv2.waitKey(50) & 0xFF
                if key in (ord("q"), 27):
                    break
            cv2.destroyAllWindows()
            if clicked["pt"] is not None:
                return clicked["pt"]
            print("[Cone_Tester] No click captured via OpenCV window; falling back to matplotlib...")
        except Exception as e:
            print(f"[Cone_Tester] OpenCV interactive window failed ({e}); falling back to matplotlib...")
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    # Fallback: matplotlib
    import matplotlib.pyplot as plt

    plt.figure("Click apex (matplotlib)")
    plt.imshow(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    plt.title("Click apex (highest point); close window or press Enter after click")
    pts = plt.ginput(1, timeout=0)
    plt.close()
    if not pts:
        raise RuntimeError("No apex selected; aborting.")
    x, y = pts[0]
    return np.array([x, y])


def detect_cone(img_bgr: np.ndarray, apex_override: np.ndarray | None = None, steps_dir: Path | None = None):
    """
    Detect cone envelope and measure spray angle.
    Returns dictionary with annotations and measurements.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    processed = _preprocess(gray)

    # Apply gamma brighten
    gamma = 0.45
    processed_gamma = np.clip((processed / 255.0) ** (1.0 / gamma) * 255.0, 0, 255).astype(np.uint8)

    # Top-weight the image to emphasize dense cone top
    h, w = processed_gamma.shape
    ramp = np.linspace(1.6, 1.0, h).astype(np.float32)[:, None]
    weighted = np.clip(processed_gamma.astype(np.float32) * ramp, 0, 255).astype(np.uint8)

    # Fine mask (kept for reference, but coarse used for contour)
    block = 31 if 31 % 2 == 1 else 31 + 1
    fine_mask = cv2.adaptiveThreshold(weighted, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, -8)
    fg_ratio = fine_mask.mean() / 255.0
    top_mean = fine_mask[: max(1, h // 5), :].mean()
    bot_mean = fine_mask[-max(1, h // 5) :, :].mean()
    if fg_ratio < 0.25 or top_mean < bot_mean:
        fine_mask = cv2.bitwise_not(fine_mask)
    fine_mask = cv2.morphologyEx(fine_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    fine_mask = cv2.morphologyEx(fine_mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8), iterations=1)
    # Clear borders on fine mask to avoid frame-sized components (set to background)
    border_px_f = max(5, w // 100)
    fine_mask[:, :border_px_f] = 255
    fine_mask[:, -border_px_f:] = 255
    fine_mask[:border_px_f, :] = 255
    fine_mask[-border_px_f:, :] = 255

    # Coarse mask for outline: heavier blur and close to capture outer envelope
    coarse_blur = cv2.GaussianBlur(weighted, (11, 11), 0)
    coarse_mask = cv2.adaptiveThreshold(coarse_blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 41, -8)
    fg_ratio_c = coarse_mask.mean() / 255.0
    top_mean_c = coarse_mask[: max(1, h // 5), :].mean()
    bot_mean_c = coarse_mask[-max(1, h // 5) :, :].mean()
    if fg_ratio_c < 0.25 or top_mean_c < bot_mean_c:
        coarse_mask = cv2.bitwise_not(coarse_mask)
    coarse_mask = cv2.morphologyEx(coarse_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    coarse_mask = cv2.morphologyEx(coarse_mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8), iterations=1)
    # Clear image borders to avoid selecting full-frame contour (set to background)
    border_px = max(5, w // 100)
    coarse_mask[:, :border_px] = 255
    coarse_mask[:, -border_px:] = 255
    coarse_mask[:border_px, :] = 255
    coarse_mask[-border_px:, :] = 255

    # --- Contour-based triangle fit (revert to earlier stable behavior) ---
    contour_mask = coarse_mask.copy()
    # For contour finding, set borders to 0 to avoid suppression of edge foreground
    border_px_c = max(5, w // 100)
    contour_mask[:, :border_px_c] = 0
    contour_mask[:, -border_px_c:] = 0
    contour_mask[:border_px_c, :] = 0
    contour_mask[-border_px_c:, :] = 0

    contours_fb, _ = cv2.findContours(contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours_fb:
        raise RuntimeError("No cone-like contour found")

    area_min = 0.01 * h * w
    area_max = 0.60 * h * w
    filtered = []
    for c in contours_fb:
        area = cv2.contourArea(c)
        if area < area_min or area > area_max:
            continue
        x, y, cw, ch = cv2.boundingRect(c)
        if ch / max(cw, 1) < 0.5:
            continue
        if x <= 1 or y <= 1 or x + cw >= w - 1 or y + ch >= h - 1:
            continue
        filtered.append(c)
    if filtered:
        filtered.sort(key=lambda c: c[:, 0, 1].min())
        contour_fb = filtered[0]
    else:
        # Fallback to largest contour if filters remove everything
        contour_fb = max(contours_fb, key=cv2.contourArea)

    hull_fb = cv2.convexHull(contour_fb)

    # Apex: topmost hull point or user override, clamp to top 10%
    if apex_override is not None:
        apex = apex_override.astype(float)
    else:
        apex_idx = np.argmin(hull_fb[:, 0, 1])
        apex = hull_fb[apex_idx, 0, :].astype(float)
    if apex[1] > 0.1 * h:
        apex[1] = 0.1 * h

    # Collect hull points within top 25% band relative to apex
    band_limit = apex[1] + 0.25 * h
    hull_pts = hull_fb[:, 0, :]
    band_pts = hull_pts[hull_pts[:, 1] <= band_limit]
    if len(band_pts) < 20:
        band_pts = hull_pts

    left_pts = band_pts[band_pts[:, 0] <= apex[0]]
    right_pts = band_pts[band_pts[:, 0] > apex[0]]
    # Trim outliers horizontally using percentiles
    if len(left_pts) >= 5:
        lx_max = np.percentile(left_pts[:, 0], 60)
        left_pts = left_pts[left_pts[:, 0] <= lx_max]
    if len(right_pts) >= 5:
        rx_min = np.percentile(right_pts[:, 0], 40)
        right_pts = right_pts[right_pts[:, 0] >= rx_min]

    def fit_line_xy(points):
        if len(points) < 5:
            return None
        pts = np.array(points, dtype=float)
        yv = pts[:, 1]
        xv = pts[:, 0]
        A = np.vstack([yv, np.ones_like(yv)]).T
        m, b = np.linalg.lstsq(A, xv, rcond=None)[0]
        return m, b

    left_line = fit_line_xy(left_pts)
    right_line = fit_line_xy(right_pts)
    # Ensure expected orientation: left slope negative, right slope positive
    if left_line and left_line[0] > -0.05:
        left_line = None
    if right_line and right_line[0] < 0.05:
        right_line = None

    # Fallback: use full hull if one side missing
    if (left_line is None or right_line is None) and len(hull_pts) > 10:
        left_pts = hull_pts[hull_pts[:, 0] <= apex[0]]
        right_pts = hull_pts[hull_pts[:, 0] > apex[0]]
        left_line = fit_line_xy(left_pts)
        right_line = fit_line_xy(right_pts)

    # Second fallback: use extreme points to force a triangle if lines still missing
    if left_line is None or right_line is None:
        lx = hull_pts[:, 0].min()
        rx = hull_pts[:, 0].max()
        ly = hull_pts[hull_pts[:, 0] == lx][:, 1].mean()
        ry = hull_pts[hull_pts[:, 0] == rx][:, 1].mean()
        left_line = fit_line_xy(np.array([[lx, ly], [apex[0], apex[1] + h * 0.1]]))
        right_line = fit_line_xy(np.array([[rx, ry], [apex[0], apex[1] + h * 0.1]]))

    angle_deg = None
    if left_line and right_line:
        theta = abs(np.arctan(left_line[0]) - np.arctan(right_line[0]))
        theta_deg = np.degrees(theta)
        if theta_deg > 180:
            theta_deg = 360 - theta_deg
        if theta_deg > 90:
            theta_deg = 180 - theta_deg
        angle_deg = theta_deg
    else:
        angle_deg = None

    # Use coarse mask for downstream drawing
    mask = coarse_mask

    def line_points(mb, y_start, y_end, width):
        m, b = mb
        y0 = max(0, int(y_start))
        y1 = max(0, min(int(y_end), img_bgr.shape[0] - 1))
        x0 = int(m * y0 + b)
        x1 = int(m * y1 + b)
        x0 = max(0, min(x0, width - 1))
        x1 = max(0, min(x1, width - 1))
        return (x0, y0), (x1, y1)

    h, w = mask.shape
    p1_left = p2_left = p1_right = p2_right = None
    if left_line is not None:
        p1_left, p2_left = line_points(left_line, apex[1], h - 1, w)
    if right_line is not None:
        p1_right, p2_right = line_points(right_line, apex[1], h - 1, w)

    angle_text = f"{angle_deg:.1f} deg" if angle_deg is not None else "angle unavailable"

    overlay = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    annotated = img_bgr.copy()

    # Save intermediate steps if requested
    if steps_dir:
        steps_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(steps_dir / "step1_gray.png"), gray)
        cv2.imwrite(str(steps_dir / "step2_clahe_blur.png"), processed)
        cv2.imwrite(str(steps_dir / "step3_gamma.png"), processed_gamma)
        cv2.imwrite(str(steps_dir / "step4_weighted.png"), weighted)
        cv2.imwrite(str(steps_dir / "step5_mask_fine.png"), fine_mask)
        cv2.imwrite(str(steps_dir / "step6_mask_coarse.png"), coarse_mask)
        contour_img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        if apex is not None:
            cv2.circle(contour_img, (int(apex[0]), int(apex[1])), 4, (0, 0, 255), -1)
        if left_line:
            lp1, lp2 = (int(left_line[0] * apex[1] + left_line[1]), int(apex[1])), (int(left_line[0] * (h - 1) + left_line[1]), h - 1)
            cv2.line(contour_img, lp1, lp2, (0, 255, 0), 1)
        if right_line:
            rp1, rp2 = (int(right_line[0] * apex[1] + right_line[1]), int(apex[1])), (int(right_line[0] * (h - 1) + right_line[1]), h - 1)
            cv2.line(contour_img, rp1, rp2, (0, 255, 0), 1)
        cv2.imwrite(str(steps_dir / "step7_lines.png"), contour_img)

    for img in (overlay, annotated):
        if left_line:
            lp1, lp2 = (int(left_line[0] * apex[1] + left_line[1]), int(apex[1])), (int(left_line[0] * (h - 1) + left_line[1]), h - 1)
            cv2.line(img, lp1, lp2, (0, 0, 255), 2)
        if right_line:
            rp1, rp2 = (int(right_line[0] * apex[1] + right_line[1]), int(apex[1])), (int(right_line[0] * (h - 1) + right_line[1]), h - 1)
            cv2.line(img, rp1, rp2, (0, 0, 255), 2)
        cv2.circle(img, (int(apex[0]), int(apex[1])), 6, (0, 0, 255), -1)
        # label near apex
        label_pos = (int(apex[0]) + 10, max(20, int(apex[1]) - 10))
        cv2.putText(
            img,
            angle_text,
            label_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )

    return {
        "mask": mask,
        "overlay": overlay,
        "annotated": annotated,
        "angle_deg": angle_deg,
        "angle_text": angle_text,
        "apex": apex,
        "left_line": left_line,
        "right_line": right_line,
        "p1_left": p1_left,
        "p2_left": p2_left,
        "p1_right": p1_right,
        "p2_right": p2_right,
    }


def build_output_dir(base_dir: Path) -> Path:
    """
    For this tool we keep outputs in the provided directory (no subfolder) to
    match the user's request to keep results alongside the script.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def main():
    # Default: image lives alongside this script, named Dense_Cone (or other supported extensions)
    default_input_path = _find_local_image(CURRENT_DIR)
    parser = argparse.ArgumentParser(description="Spray cone detection and angle measurement")
    parser.add_argument("--input", type=Path, default=default_input_path, help="Path to image (auto-detected by default)")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=CURRENT_DIR,
        help="Directory to store results (defaults to Trials folder; no subfolder)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not auto-open the annotated image after saving",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Click to select apex instead of automatic apex selection",
    )
    parser.add_argument(
        "--use-matplotlib",
        action="store_true",
        help="Force matplotlib click window instead of OpenCV window",
    )
    args = parser.parse_args()

    input_path = args.input
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"[Cone_Tester] Loading image: {input_path}")
    frame = _load_first_frame(input_path)

    apex_override = None
    if args.interactive:
        apex_override = _get_apex_interactive(frame, use_matplotlib=args.use_matplotlib)

    print("[Cone_Tester] Detecting cone...")
    steps_dir = output_root / "cone_steps"
    result = detect_cone(frame, apex_override=apex_override, steps_dir=steps_dir)

    # Save into the same folder (or user-provided output_root) with stable names.
    save_dir = build_output_dir(output_root)
    annotated_path = save_dir / "Cone_Tester_annotated.png"
    overlay_path = save_dir / "Cone_Tester_mask_overlay.png"
    mask_path = save_dir / "Cone_Tester_mask.png"

    cv2.imwrite(str(annotated_path), result["annotated"])
    cv2.imwrite(str(overlay_path), result["overlay"])
    cv2.imwrite(str(mask_path), result["mask"])

    if result["angle_deg"] is not None:
        print(f"[Cone_Tester] Angle: {result['angle_deg']:.2f} degrees")
    else:
        print(f"[Cone_Tester] Angle unavailable (see annotated output)")
    print(f"[Cone_Tester] Saved annotated image to: {annotated_path}")
    print(f"[Cone_Tester] Saved overlay to: {overlay_path}")
    print(f"[Cone_Tester] Saved mask to: {mask_path}")

    if not args.no_open:
        try:
            # On macOS, use `open`; fallback to cv2.imshow if needed.
            if sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", str(annotated_path)], check=False)
            else:
                # fallback preview using OpenCV window
                cv2.imshow("Annotated Cone", result["annotated"])
                cv2.waitKey(0)
                cv2.destroyAllWindows()
        except Exception as e:
            print(f"[Cone_Tester] Warning: could not open image automatically: {e}")


if __name__ == "__main__":
    main()

