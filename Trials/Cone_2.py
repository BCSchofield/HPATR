'''
Steps:
- Get input image from folder
- Preprocess (CLAHE + blur + gamma + top weighting)
- Mask (adaptive mean)
- Row-based fit (scanning bands for left/right pixels)
- Fit lines from point to bottom using row extents
- Compute angle
- Save outputs
'''

import argparse
from pathlib import Path
import sys
import cv2
import numpy as np

# Allow running from repo root
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config_loader import get_imaging_config  # noqa: E402

# Tunable parameters (edit here)
CLAHE_CLIP = 2.0          # CLAHE clip limit. Higher = more contrast.   
CLAHE_TILE = 8            # CLAHE tile grid (will use square tileGridSize: tile x tile). 
BLUR_KSIZE = 3            # Gaussian blur kernel (odd). Higher = more blur.
GAMMA = 0.45              # Gamma brighten (<1 brightens). Higher = more bright.
TOP_RAMP_START = 1.5      # Top weighting multiplier at top row. Higher = more weight.
WEIGHT_TOP = 1.8          # Piecewise weight for top third. Higher = more emphasis on top.
WEIGHT_MID = 1.3          # Piecewise weight for middle third. Higher = more emphasis on middle.
WEIGHT_BOT = 1.0          # Piecewise weight for bottom third. Usually kept at 1.0.
ADAPT_BLOCK = 31          # Adaptive threshold block size (odd). 
ADAPT_C = -6              # Adaptive threshold C. Higher = more threshold.
FG_MIN_RATIO = 0.35       # Foreground ratio to skip auto-invert. Higher = more threshold.
OPEN_K = 3                # Morph open kernel. Higher = more open.
CLOSE_K = 7               # Morph close kernel. Higher = more close.
TOP_BAND_FRAC = 0.30      # Fraction of image height for row scan. Higher = more row scan.
MIN_FG_PER_ROW = 8        # Minimum fg pixels per row to keep row. Higher = more row scan.
LINE_FIT_START_FRAC = 0.0 # Use points from this fraction of the band (0.0 = use all, 0.3 = skip top 30%).
APEX_CLAMP_FRAC = 0.10    # Clamp apex to top X of image height. Higher = more apex clamp.
LEFT_SLOPE_MAX = -0.05    # Left slope must be <= this. Lower = more left slope.
RIGHT_SLOPE_MIN = 0.05    # Right slope must be >= this. Lower = more right slope.


def _find_local_image(base_dir: Path, base_name: str = "Nicer_Spray") -> Path:
    exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
    for ext in exts:
        candidate = base_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No image named {base_name} with extensions {exts} found in {base_dir}")


def _preprocess(gray: np.ndarray) -> np.ndarray:
    """CLAHE + blur."""
    clahe = cv2.createCLAHE(
        clipLimit=float(CLAHE_CLIP),
        tileGridSize=(int(CLAHE_TILE), int(CLAHE_TILE))
    )
    eq = clahe.apply(gray)
    k = max(3, int(BLUR_KSIZE) | 1)
    blur = cv2.GaussianBlur(eq, (k, k), 0)
    return blur


def _row_based_fit(mask: np.ndarray, top_frac: float = 0.3, min_fg_per_row: int = 8):
    h, w = mask.shape
    fg = mask < 128
    band_end = int(h * top_frac)
    left_pts = []
    right_pts = []
    apex = None
    for y in range(band_end):
        xs = np.where(fg[y])[0]
        if xs.size < min_fg_per_row:
            continue
        if apex is None:
            apex = np.array([xs.mean(), y], dtype=float)
        left_pts.append([xs.min(), y])
        right_pts.append([xs.max(), y])
    return apex, left_pts, right_pts


def _fit_line(points):
    if len(points) < 5:
        return None
    pts = np.array(points, dtype=float)
    yv = pts[:, 1]
    xv = pts[:, 0]
    A = np.vstack([yv, np.ones_like(yv)]).T
    m, b = np.linalg.lstsq(A, xv, rcond=None)[0]
    return m, b


def detect_cone(img_bgr: np.ndarray, steps_dir: Path | None = None):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    processed = _preprocess(gray)

    # Gamma + three-band weighting + ramp
    gamma = float(GAMMA)
    processed_gamma = np.clip((processed / 255.0) ** (1.0 / gamma) * 255.0, 0, 255).astype(np.uint8)
    h, w = processed_gamma.shape
    # Piecewise weight mask (top, mid, bot thirds)
    wt = float(WEIGHT_TOP)
    wm = float(WEIGHT_MID)
    wb = float(WEIGHT_BOT)
    weights = np.ones((h, 1), dtype=np.float32)
    t_third = h // 3
    m_third = 2 * h // 3
    weights[:t_third] = wt
    weights[t_third:m_third] = wm
    weights[m_third:] = wb
    # Combine with optional linear ramp
    ramp = np.linspace(float(TOP_RAMP_START), 1.0, h).astype(np.float32)[:, None]
    weight_mask = weights * ramp
    weighted = np.clip(processed_gamma.astype(np.float32) * weight_mask, 0, 255).astype(np.uint8)

    # Mask (adaptive mean)
    block = int(ADAPT_BLOCK) if int(ADAPT_BLOCK) % 2 == 1 else int(ADAPT_BLOCK) + 1
    adapt_c = float(ADAPT_C)
    mask = cv2.adaptiveThreshold(weighted, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, adapt_c)
    fg_ratio = mask.mean() / 255.0
    top_mean = mask[: max(1, h // 5), :].mean()
    bot_mean = mask[-max(1, h // 5) :, :].mean()
    if fg_ratio < float(FG_MIN_RATIO) or top_mean < bot_mean:
        mask = cv2.bitwise_not(mask)
    open_k = max(3, int(OPEN_K) | 1)
    close_k = max(3, int(CLOSE_K) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((open_k, open_k), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((close_k, close_k), np.uint8), iterations=1)
    # Clear borders
    border_px = max(5, w // 100)
    mask[:, :border_px] = 255
    mask[:, -border_px:] = 255
    mask[:border_px, :] = 255
    mask[-border_px:, :] = 255

    apex, left_pts, right_pts = _row_based_fit(mask, top_frac=TOP_BAND_FRAC, min_fg_per_row=MIN_FG_PER_ROW)
    if apex is None:
        raise RuntimeError("No apex found in top band")
    apex_clamp = float(APEX_CLAMP_FRAC)
    if apex[1] > apex_clamp * h:
        apex[1] = apex_clamp * h

    # Optionally skip top portion of points to emphasize wider base
    line_fit_start = float(LINE_FIT_START_FRAC)
    if line_fit_start > 0 and len(left_pts) > 5:
        skip_n = int(len(left_pts) * line_fit_start)
        left_pts = left_pts[skip_n:]
        right_pts = right_pts[skip_n:]

    left_line = _fit_line(left_pts)
    right_line = _fit_line(right_pts)

    # Orientation checks
    if left_line and left_line[0] > float(LEFT_SLOPE_MAX):
        left_line = None
    if right_line and right_line[0] < float(RIGHT_SLOPE_MIN):
        right_line = None

    # Force lines if missing
    if left_line is None and left_pts:
        lx = min(p[0] for p in left_pts)
        left_line = _fit_line([[lx, apex[1]], [apex[0], apex[1] + h * 0.1]])
    if right_line is None and right_pts:
        rx = max(p[0] for p in right_pts)
        right_line = _fit_line([[rx, apex[1]], [apex[0], apex[1] + h * 0.1]])

    angle_deg = None
    if left_line and right_line:
        theta = abs(np.arctan(left_line[0]) - np.arctan(right_line[0]))
        theta_deg = np.degrees(theta)
        if theta_deg > 180:
            theta_deg = 360 - theta_deg
        if theta_deg > 90:
            theta_deg = 180 - theta_deg
        angle_deg = theta_deg

    def line_points(mb):
        m, b = mb
        y0 = int(apex[1])
        y1 = h - 1
        x0 = int(m * y0 + b)
        x1 = int(m * y1 + b)
        x0 = max(0, min(x0, w - 1))
        x1 = max(0, min(x1, w - 1))
        return (x0, y0), (x1, y1)

    p1_left, p2_left = line_points(left_line) if left_line else (None, None)
    p1_right, p2_right = line_points(right_line) if right_line else (None, None)

    overlay = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    annotated = img_bgr.copy()
    if left_line:
        cv2.line(annotated, p1_left, p2_left, (0, 0, 255), 2)
    if right_line:
        cv2.line(annotated, p1_right, p2_right, (0, 0, 255), 2)
    cv2.circle(annotated, (int(apex[0]), int(apex[1])), 6, (0, 0, 255), -1)
    angle_text = f"{angle_deg:.1f} deg" if angle_deg is not None else "angle unavailable"
    cv2.putText(annotated, angle_text, (int(apex[0]) + 10, max(20, int(apex[1]) - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2, cv2.LINE_AA)

    if steps_dir:
        steps_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(steps_dir / "step1_gray.png"), gray)
        cv2.imwrite(str(steps_dir / "step2_clahe_blur.png"), processed)
        cv2.imwrite(str(steps_dir / "step3_gamma.png"), processed_gamma)
        cv2.imwrite(str(steps_dir / "step4_weighted.png"), weighted)
        cv2.imwrite(str(steps_dir / "step5_mask.png"), mask)
        lines_img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        if left_line:
            cv2.line(lines_img, p1_left, p2_left, (0, 255, 0), 1)
        if right_line:
            cv2.line(lines_img, p1_right, p2_right, (0, 255, 0), 1)
        cv2.circle(lines_img, (int(apex[0]), int(apex[1])), 4, (0, 0, 255), -1)
        cv2.imwrite(str(steps_dir / "step6_lines.png"), lines_img)

    return {
        "mask": mask,
        "overlay": overlay,
        "annotated": annotated,
        "angle_deg": angle_deg,
        "angle_text": angle_text,
        "apex": apex,
        "left_line": left_line,
        "right_line": right_line,
    }


def load_params_from_csv(csv_path: Path) -> dict:
    """Load parameters from CSV file (same format as GUI saves)."""
    import csv
    params = {}
    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # Skip header
        for row in reader:
            if len(row) >= 2:
                params[row[0]] = row[1]
    return params


def apply_params_to_constants(params: dict):
    """Apply loaded parameters to module-level constants."""
    global CLAHE_CLIP, CLAHE_TILE, BLUR_KSIZE, GAMMA, TOP_RAMP_START
    global WEIGHT_TOP, WEIGHT_MID, WEIGHT_BOT
    global ADAPT_BLOCK, ADAPT_C, FG_MIN_RATIO
    global OPEN_K, CLOSE_K, TOP_BAND_FRAC, MIN_FG_PER_ROW
    global LINE_FIT_START_FRAC, APEX_CLAMP_FRAC, LEFT_SLOPE_MAX, RIGHT_SLOPE_MIN
    
    if "CLAHE_CLIP" in params:
        CLAHE_CLIP = float(params["CLAHE_CLIP"])
    if "CLAHE_TILE" in params:
        CLAHE_TILE = int(params["CLAHE_TILE"])
    if "BLUR_KSIZE" in params:
        BLUR_KSIZE = int(params["BLUR_KSIZE"])
    if "GAMMA" in params:
        GAMMA = float(params["GAMMA"])
    if "TOP_RAMP_START" in params:
        TOP_RAMP_START = float(params["TOP_RAMP_START"])
    if "WEIGHT_TOP" in params:
        WEIGHT_TOP = float(params["WEIGHT_TOP"])
    if "WEIGHT_MID" in params:
        WEIGHT_MID = float(params["WEIGHT_MID"])
    if "WEIGHT_BOT" in params:
        WEIGHT_BOT = float(params["WEIGHT_BOT"])
    if "ADAPT_BLOCK" in params:
        ADAPT_BLOCK = int(params["ADAPT_BLOCK"])
    if "ADAPT_C" in params:
        ADAPT_C = float(params["ADAPT_C"])
    if "FG_MIN_RATIO" in params:
        FG_MIN_RATIO = float(params["FG_MIN_RATIO"])
    if "OPEN_K" in params:
        OPEN_K = int(params["OPEN_K"])
    if "CLOSE_K" in params:
        CLOSE_K = int(params["CLOSE_K"])
    if "TOP_BAND_FRAC" in params:
        TOP_BAND_FRAC = float(params["TOP_BAND_FRAC"])
    if "MIN_FG_PER_ROW" in params:
        MIN_FG_PER_ROW = int(params["MIN_FG_PER_ROW"])
    if "LINE_FIT_START_FRAC" in params:
        LINE_FIT_START_FRAC = float(params["LINE_FIT_START_FRAC"])
    if "APEX_CLAMP_FRAC" in params:
        APEX_CLAMP_FRAC = float(params["APEX_CLAMP_FRAC"])
    if "LEFT_SLOPE_MAX" in params:
        LEFT_SLOPE_MAX = float(params["LEFT_SLOPE_MAX"])
    if "RIGHT_SLOPE_MIN" in params:
        RIGHT_SLOPE_MIN = float(params["RIGHT_SLOPE_MIN"])


def main():
    default_input_path = _find_local_image(CURRENT_DIR)
    parser = argparse.ArgumentParser(description="Simple row-based cone angle detector")
    parser.add_argument("--input", type=Path, default=default_input_path, help="Path to image")
    parser.add_argument("--output-root", type=Path, default=CURRENT_DIR, help="Output directory")
    parser.add_argument("--params", type=Path, help="Path to CSV file with parameters (from GUI)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open annotated image")
    args = parser.parse_args()
    
    # Automatically load params_1.csv if it exists (unless --params is specified)
    params_csv_path = args.params
    if params_csv_path is None:
        # Look for params_1.csv in the same directory as this script
        params_csv_path = CURRENT_DIR / "params_1.csv"
        if not params_csv_path.exists():
            params_csv_path = None
    
    # Load parameters from CSV if found
    if params_csv_path:
        print(f"[Cone_2] Loading parameters from: {params_csv_path}")
        params = load_params_from_csv(params_csv_path)
        apply_params_to_constants(params)
        print(f"[Cone_2] Parameters loaded from CSV")
    else:
        print(f"[Cone_2] Using default parameters (no params_1.csv found)")

    input_path = args.input
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    print(f"[Cone_2] Loading image: {input_path}")
    frame = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if frame is None:
        raise FileNotFoundError(f"Cannot load image: {input_path}")

    steps_dir = output_root / "cone_steps_2"
    result = detect_cone(frame, steps_dir=steps_dir)

    annotated_path = output_root / "Cone_2_annotated.png"
    overlay_path = output_root / "Cone_2_mask_overlay.png"
    mask_path = output_root / "Cone_2_mask.png"

    cv2.imwrite(str(annotated_path), result["annotated"])
    cv2.imwrite(str(overlay_path), result["overlay"])
    cv2.imwrite(str(mask_path), result["mask"])

    if result["angle_deg"] is not None:
        print(f"[Cone_2] Angle: {result['angle_deg']:.2f} degrees")
    else:
        print("[Cone_2] Angle unavailable")
    print(f"[Cone_2] Saved annotated image to: {annotated_path}")
    print(f"[Cone_2] Saved overlay to: {overlay_path}")
    print(f"[Cone_2] Saved mask to: {mask_path}")

    if not args.no_open:
        try:
            if sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", str(annotated_path)], check=False)
            else:
                cv2.imshow("Annotated Cone", result["annotated"])
                cv2.waitKey(0)
                cv2.destroyAllWindows()
        except Exception as e:
            print(f"[Cone_2] Warning: could not open image automatically: {e}")


if __name__ == "__main__":
    main()

