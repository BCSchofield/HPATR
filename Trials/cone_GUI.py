# Merge term 1
"""
Interactive GUI to tune cone detection parameters and visualize each step.

Layout:
- Original (left)
- Steps (center): gray, clahe_blur, gamma, weighted, mask, lines
- Annotated result (right)

Controls (top panel):
- Editable parameter fields for the processing pipeline
- Apply button re-runs the pipeline and updates all images
- Load Image button to pick a different input image
"""

import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path
import sys
import matplotlib
matplotlib.use('TkAgg')  # Use TkAgg backend for Tkinter compatibility
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import cv2
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFont

# Allow running from repo root
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config_loader import get_imaging_config  # noqa: E402

# Default tunable parameters
DEFAULTS = {
    "CLAHE_CLIP": 2.0,
    "CLAHE_TILE": 8,            # will use square tileGridSize (tile x tile)
    "BLUR_KSIZE": 3,
    "GAMMA": 0.45,
    "TOP_RAMP_START": 1.5,
    "WEIGHT_TOP": 1.8,          # piecewise weight for top third
    "WEIGHT_MID": 1.3,          # piecewise weight for middle third
    "WEIGHT_BOT": 1.0,          # piecewise weight for bottom third
    "ADAPT_BLOCK": 31,
    "ADAPT_C": -6,
    "FG_MIN_RATIO": 0.35,
    "OPEN_K": 3,
    "CLOSE_K": 7,
    "TOP_BAND_FRAC": 0.30,
    "MIN_FG_PER_ROW": 8,
    "LINE_FIT_START_FRAC": 0.0,  # Use points from this fraction of the band (0.0 = use all, 0.3 = skip top 30%)
    "APEX_CLAMP_FRAC": 0.10,
    "LEFT_SLOPE_MAX": -0.05,
    "RIGHT_SLOPE_MIN": 0.05,
}

# Parameter ranges for sliders (min, max, step)
PARAM_RANGES = {
    "CLAHE_CLIP": (0.5, 5.0, 0.1),
    "CLAHE_TILE": (4, 16, 1),
    "BLUR_KSIZE": (1, 15, 2),  # Odd numbers only
    "GAMMA": (0.2, 1.5, 0.05),
    "TOP_RAMP_START": (1.0, 3.0, 0.1),
    "WEIGHT_TOP": (1.0, 3.0, 0.1),
    "WEIGHT_MID": (0.5, 2.5, 0.1),
    "WEIGHT_BOT": (0.5, 2.0, 0.1),
    "ADAPT_BLOCK": (15, 51, 2),  # Odd numbers only
    "ADAPT_C": (-15, 5, 1),
    "FG_MIN_RATIO": (0.1, 0.6, 0.05),
    "OPEN_K": (3, 15, 2),  # Odd numbers only
    "CLOSE_K": (3, 21, 2),  # Odd numbers only
    "TOP_BAND_FRAC": (0.1, 0.8, 0.05),
    "MIN_FG_PER_ROW": (2, 20, 1),
    "LINE_FIT_START_FRAC": (0.0, 0.5, 0.05),
    "APEX_CLAMP_FRAC": (0.05, 0.25, 0.01),
    "LEFT_SLOPE_MAX": (-0.15, 0.0, 0.01),
    "RIGHT_SLOPE_MIN": (0.0, 0.15, 0.01),
}


def _find_local_image(base_dir: Path, base_name: str = "Nicer_Spray") -> Path:
    exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
    for ext in exts:
        candidate = base_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No image named {base_name} with extensions {exts} found in {base_dir}")


def _preprocess(gray: np.ndarray, params: dict) -> np.ndarray:
    clahe = cv2.createCLAHE(
        clipLimit=float(params["CLAHE_CLIP"]),
        tileGridSize=(int(params["CLAHE_TILE"]), int(params["CLAHE_TILE"]))
    )
    eq = clahe.apply(gray)
    k = max(3, int(params["BLUR_KSIZE"]) | 1)
    blur = cv2.GaussianBlur(eq, (k, k), 0)
    return blur


def _row_based_fit(mask: np.ndarray, params: dict):
    h, w = mask.shape
    fg = mask < 128
    band_end = int(h * float(params["TOP_BAND_FRAC"]))
    left_pts = []
    right_pts = []
    apex = None
    min_fg_per_row = int(params["MIN_FG_PER_ROW"])
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


def process_image(img_bgr: np.ndarray, params: dict):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    clahe_blur = _preprocess(gray, params)

    gamma = float(params["GAMMA"])
    processed_gamma = np.clip((clahe_blur / 255.0) ** (1.0 / gamma) * 255.0, 0, 255).astype(np.uint8)

    h, w = processed_gamma.shape
    # Piecewise weight mask (top, mid, bot thirds)
    wt = float(params.get("WEIGHT_TOP", DEFAULTS["WEIGHT_TOP"]))
    wm = float(params.get("WEIGHT_MID", DEFAULTS["WEIGHT_MID"]))
    wb = float(params.get("WEIGHT_BOT", DEFAULTS["WEIGHT_BOT"]))
    weights = np.ones((h, 1), dtype=np.float32)
    t_third = h // 3
    m_third = 2 * h // 3
    weights[:t_third] = wt
    weights[t_third:m_third] = wm
    weights[m_third:] = wb
    # Combine with optional linear ramp
    ramp = np.linspace(float(params["TOP_RAMP_START"]), 1.0, h).astype(np.float32)[:, None]
    weight_mask = weights * ramp
    weighted = np.clip(processed_gamma.astype(np.float32) * weight_mask, 0, 255).astype(np.uint8)

    block = int(params["ADAPT_BLOCK"]) if int(params["ADAPT_BLOCK"]) % 2 == 1 else int(params["ADAPT_BLOCK"]) + 1
    adapt_c = float(params["ADAPT_C"])
    mask = cv2.adaptiveThreshold(weighted, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, adapt_c)

    fg_ratio = mask.mean() / 255.0
    top_mean = mask[: max(1, h // 5), :].mean()
    bot_mean = mask[-max(1, h // 5) :, :].mean()
    if fg_ratio < float(params["FG_MIN_RATIO"]) or top_mean < bot_mean:
        mask = cv2.bitwise_not(mask)

    open_k = max(3, int(params["OPEN_K"]) | 1)
    close_k = max(3, int(params["CLOSE_K"]) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((open_k, open_k), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((close_k, close_k), np.uint8), iterations=1)

    border_px = max(5, w // 100)
    mask[:, :border_px] = 255
    mask[:, -border_px:] = 255
    mask[:border_px, :] = 255
    mask[-border_px:, :] = 255

    apex, left_pts, right_pts = _row_based_fit(mask, params)
    if apex is None:
        raise RuntimeError("No apex found in top band")
    apex_clamp = float(params["APEX_CLAMP_FRAC"])
    if apex[1] > apex_clamp * h:
        apex[1] = apex_clamp * h

    # Optionally skip top portion of points to emphasize wider base
    line_fit_start = float(params.get("LINE_FIT_START_FRAC", 0.0))
    if line_fit_start > 0 and len(left_pts) > 5:
        skip_n = int(len(left_pts) * line_fit_start)
        left_pts = left_pts[skip_n:]
        right_pts = right_pts[skip_n:]

    left_line = _fit_line(left_pts)
    right_line = _fit_line(right_pts)

    # Orientation checks
    if left_line and left_line[0] > float(params["LEFT_SLOPE_MAX"]):
        left_line = None
    if right_line and right_line[0] < float(params["RIGHT_SLOPE_MIN"]):
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

    p1_left = p2_left = p1_right = p2_right = None
    if left_line:
        p1_left, p2_left = line_points(left_line)
    if right_line:
        p1_right, p2_right = line_points(right_line)

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

    lines_img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    if left_line:
        cv2.line(lines_img, p1_left, p2_left, (0, 255, 0), 1)
    if right_line:
        cv2.line(lines_img, p1_right, p2_right, (0, 255, 0), 1)
    cv2.circle(lines_img, (int(apex[0]), int(apex[1])), 4, (0, 0, 255), -1)

    # Create original image with scan band overlay
    original_with_band = img_bgr.copy()
    band_end = int(h * float(params["TOP_BAND_FRAC"]))
    # Draw orange semi-transparent rectangle for scan band
    overlay_band = original_with_band.copy()
    cv2.rectangle(overlay_band, (0, 0), (w, band_end), (0, 165, 255), -1)  # Orange in BGR
    cv2.addWeighted(overlay_band, 0.3, original_with_band, 0.7, 0, original_with_band)
    # Draw orange border line at band end
    cv2.line(original_with_band, (0, band_end), (w, band_end), (0, 165, 255), 2)

    steps = {
        "gray": gray,
        "clahe_blur": clahe_blur,
        "gamma": processed_gamma,
        "weighted": weighted,
        "mask": mask,
        "lines": lines_img,
    }

    return {
        "steps": steps,
        "overlay": overlay,
        "annotated": annotated,
        "angle_deg": angle_deg,
        "original_with_band": original_with_band,
    }


def np_to_tk(img: np.ndarray, max_w: int = 400, max_h: int = 400):
    if img.ndim == 2:
        img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    pil_img.thumbnail((max_w, max_h))
    return ImageTk.PhotoImage(pil_img)


# Parameter descriptions and visual generators
PARAM_DESCRIPTIONS = {
    "CLAHE_CLIP": {
        "desc": "CLAHE (Contrast Limited Adaptive Histogram Equalization) clip limit.\n\nHigher values = more contrast enhancement.\nTypical range: 1.0-4.0",
        "visual": "contrast_curve"
    },
    "CLAHE_TILE": {
        "desc": "CLAHE tile grid size (square tiles).\n\nLarger tiles = more global contrast, smaller = more local.\nMust be odd number. Typical: 4-16",
        "visual": "tile_grid"
    },
    "BLUR_KSIZE": {
        "desc": "Gaussian blur kernel size (must be odd).\n\nHigher = more smoothing, reduces noise.\nTypical: 3, 5, 7, 9",
        "visual": "blur_effect"
    },
    "GAMMA": {
        "desc": "Gamma correction for brightness adjustment.\n\n< 1.0 = brightens image (e.g., 0.45)\n> 1.0 = darkens image\nTypical: 0.3-0.7 for brightening",
        "visual": "gamma_curve"
    },
    "TOP_RAMP_START": {
        "desc": "Top weighting multiplier at the top row.\n\nHigher = more emphasis on top region.\nCreates a linear ramp from top to bottom.\nTypical: 1.0-2.5",
        "visual": "ramp_gradient"
    },
    "WEIGHT_TOP": {
        "desc": "Piecewise weight for top third of image.\n\nHigher = more emphasis on top region for line fitting.\nWorks with WEIGHT_MID and WEIGHT_BOT.\nTypical: 1.5-2.5",
        "visual": "three_band_weights"
    },
    "WEIGHT_MID": {
        "desc": "Piecewise weight for middle third of image.\n\nHigher = more emphasis on middle region.\nTypical: 1.0-1.6",
        "visual": "three_band_weights"
    },
    "WEIGHT_BOT": {
        "desc": "Piecewise weight for bottom third of image.\n\nUsually kept at 1.0 (baseline).\nLower = less emphasis on bottom region.\nTypical: 0.8-1.2",
        "visual": "three_band_weights"
    },
    "ADAPT_BLOCK": {
        "desc": "Adaptive threshold block size (must be odd).\n\nLarger = more global thresholding.\nSmaller = more local thresholding.\nTypical: 15-51",
        "visual": "threshold_blocks"
    },
    "ADAPT_C": {
        "desc": "Adaptive threshold constant (subtracted from mean).\n\nNegative values = lower threshold (more foreground).\nPositive values = higher threshold (less foreground).\nTypical: -10 to 0",
        "visual": "threshold_effect"
    },
    "FG_MIN_RATIO": {
        "desc": "Minimum foreground ratio to skip auto-invert.\n\nIf foreground ratio < this, image is inverted.\nTypical: 0.3-0.5",
        "visual": "fg_ratio"
    },
    "OPEN_K": {
        "desc": "Morphological opening kernel size (must be odd).\n\nRemoves small noise/artifacts.\nLarger = removes larger objects.\nTypical: 3-7",
        "visual": "morph_open"
    },
    "CLOSE_K": {
        "desc": "Morphological closing kernel size (must be odd).\n\nFills small holes/gaps.\nLarger = fills larger gaps.\nTypical: 5-15",
        "visual": "morph_close"
    },
    "TOP_BAND_FRAC": {
        "desc": "Fraction of image height to scan for row-based fitting.\n\n0.30 = top 30% of image.\nHigher = scans more rows (wider cone detection).\nTypical: 0.25-0.40",
        "visual": "scan_band"
    },
    "MIN_FG_PER_ROW": {
        "desc": "Minimum foreground pixels per row to include in fitting.\n\nHigher = requires more pixels per row (stricter).\nLower = includes more rows (wider detection).\nTypical: 5-15",
        "visual": "row_threshold"
    },
    "LINE_FIT_START_FRAC": {
        "desc": "Fraction of collected points to skip from top.\n\n0.0 = use all points.\n0.2 = skip top 20%, use wider lower 80%.\nHigher = emphasizes wider base of cone.\nTypical: 0.0-0.3",
        "visual": "line_fit_skip"
    },
    "APEX_CLAMP_FRAC": {
        "desc": "Clamp apex to top X fraction of image height.\n\n0.10 = apex must be in top 10%.\nPrevents apex from being too low.\nTypical: 0.05-0.15",
        "visual": "apex_clamp"
    },
    "LEFT_SLOPE_MAX": {
        "desc": "Maximum allowed slope for left line (must be negative).\n\n-0.05 = left line slopes left (negative slope).\nMore negative = allows steeper left slope.\nTypical: -0.1 to -0.02",
        "visual": "slope_constraints"
    },
    "RIGHT_SLOPE_MIN": {
        "desc": "Minimum allowed slope for right line (must be positive).\n\n0.05 = right line slopes right (positive slope).\nMore positive = allows steeper right slope.\nTypical: 0.02 to 0.1",
        "visual": "slope_constraints"
    },
}


def create_visual_diagram(param_name: str, width=400, height=300):
    """Create a visual diagram showing how a parameter affects the image."""
    fig = Figure(figsize=(width/100, height/100), dpi=100)
    
    if param_name == "GAMMA":
        # Before/after image example with different gamma values
        fig.clear()
        ax1 = fig.add_subplot(1, 3, 1)
        ax2 = fig.add_subplot(1, 3, 2)
        ax3 = fig.add_subplot(1, 3, 3)
        
        # Create a sample gradient image (simulating a cone-like pattern)
        h, w = 150, 200
        test_img = np.zeros((h, w), dtype=np.uint8)
        center_x = w // 2
        for y in range(h):
            for x in range(w):
                dist_from_center = abs(x - center_x)
                # Create a cone-like pattern (dense at top, sparse at bottom)
                intensity = max(0, 255 - (dist_from_center * 2) - (y * 0.5))
                test_img[y, x] = np.clip(intensity, 0, 255)
        
        # Original (gamma=1.0)
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title('Original\n(γ=1.0)', fontsize=9)
        ax1.axis('off')
        
        # Low gamma (brightens)
        gamma_low = 0.45
        brightened = np.clip((test_img / 255.0) ** (1.0 / gamma_low) * 255.0, 0, 255).astype(np.uint8)
        ax2.imshow(brightened, cmap='gray')
        ax2.set_title(f'Brightened\n(γ={gamma_low})', fontsize=9)
        ax2.axis('off')
        
        # High gamma (darkens)
        gamma_high = 1.5
        darkened = np.clip((test_img / 255.0) ** (1.0 / gamma_high) * 255.0, 0, 255).astype(np.uint8)
        ax3.imshow(darkened, cmap='gray')
        ax3.set_title(f'Darkened\n(γ={gamma_high})', fontsize=9)
        ax3.axis('off')
        
        fig.suptitle('Gamma Correction Effect on Image Brightness', fontsize=11, fontweight='bold')
        
    elif param_name == "CLAHE_CLIP":
        # Before/after CLAHE examples
        fig.clear()
        ax1 = fig.add_subplot(1, 3, 1)
        ax2 = fig.add_subplot(1, 3, 2)
        ax3 = fig.add_subplot(1, 3, 3)
        
        # Create test image with varying contrast
        h, w = 150, 200
        test_img = np.zeros((h, w), dtype=np.uint8)
        for y in range(h):
            for x in range(w):
                # Create regions with different intensities
                if x < w//3:
                    test_img[y, x] = 50 + (y % 20) * 5  # Low contrast region
                elif x < 2*w//3:
                    test_img[y, x] = 128  # Mid intensity
                else:
                    test_img[y, x] = 200 - (y % 20) * 5  # High contrast region
        
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title('Original\n(Low Contrast)', fontsize=9)
        ax1.axis('off')
        
        # CLAHE with low clip
        clahe_low = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(8, 8))
        enhanced_low = clahe_low.apply(test_img)
        ax2.imshow(enhanced_low, cmap='gray')
        ax2.set_title('CLAHE Clip=1.0\n(Subtle)', fontsize=9)
        ax2.axis('off')
        
        # CLAHE with high clip
        clahe_high = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced_high = clahe_high.apply(test_img)
        ax3.imshow(enhanced_high, cmap='gray')
        ax3.set_title('CLAHE Clip=4.0\n(Strong)', fontsize=9)
        ax3.axis('off')
        
        fig.suptitle('CLAHE Contrast Enhancement', fontsize=11, fontweight='bold')
        
    elif param_name in ["WEIGHT_TOP", "WEIGHT_MID", "WEIGHT_BOT"]:
        # Show how weighting affects the image
        fig.clear()
        ax1 = fig.add_subplot(1, 2, 1)
        ax2 = fig.add_subplot(1, 2, 2)
        
        # Create a cone-like test image
        h, w = 200, 150
        test_img = np.zeros((h, w), dtype=np.uint8)
        center_x = w // 2
        for y in range(h):
            width_at_y = 20 + (y * 0.8)  # Cone widens downward
            for x in range(w):
                dist = abs(x - center_x)
                if dist < width_at_y:
                    intensity = 255 - (dist * 3) - (y * 0.3)
                    test_img[y, x] = np.clip(intensity, 0, 255)
        
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title('Original Image', fontsize=10)
        ax1.axis('off')
        
        # Apply three-band weighting
        weights = np.ones((h, 1), dtype=np.float32)
        t_third = h // 3
        m_third = 2 * h // 3
        weights[:t_third] = 1.8
        weights[t_third:m_third] = 1.3
        weights[m_third:] = 1.0
        weighted = np.clip(test_img.astype(np.float32) * weights, 0, 255).astype(np.uint8)
        
        ax2.imshow(weighted, cmap='gray')
        ax2.set_title('With Three-Band Weighting\n(Top:1.8, Mid:1.3, Bot:1.0)', fontsize=9)
        ax2.axis('off')
        
        # Add colored bands to show regions
        for ax in [ax1, ax2]:
            ax.axhline(y=t_third, color='red', linestyle='--', linewidth=1, alpha=0.5)
            ax.axhline(y=m_third, color='blue', linestyle='--', linewidth=1, alpha=0.5)
        
        fig.suptitle('Three-Band Weighting Effect', fontsize=11, fontweight='bold')
        
    elif param_name == "TOP_BAND_FRAC":
        # Show the scanning band on a cone image
        fig.clear()
        ax = fig.add_subplot(111)
        
        # Create cone-like pattern
        h, w = 250, 200
        test_img = np.ones((h, w, 3))
        center_x = w // 2
        for y in range(h):
            width_at_y = 15 + (y * 0.6)
            for x in range(w):
                dist = abs(x - center_x)
                if dist < width_at_y:
                    intensity = 0.3 + (1.0 - dist/width_at_y) * 0.7
                    test_img[y, x] = [intensity, intensity, intensity]
        
        ax.imshow(test_img)
        band_frac = 0.30
        band_end = int(h * band_frac)
        # Highlight the scan band
        overlay = test_img.copy()
        overlay[:band_end, :] = overlay[:band_end, :] * 0.5 + np.array([1.0, 0.8, 0.8]) * 0.5
        ax.imshow(overlay, alpha=0.6)
        ax.axhline(y=band_end, color='red', linestyle='--', linewidth=3, label=f'Scan band: top {int(band_frac*100)}%')
        ax.set_title(f'Row Scanning Band (TOP_BAND_FRAC={band_frac})\nOnly rows in highlighted region are scanned', fontsize=10)
        ax.axis('off')
        ax.legend(loc='lower right', fontsize=9)
        
    elif param_name == "LINE_FIT_START_FRAC":
        # Show which points are used for line fitting
        fig.clear()
        ax = fig.add_subplot(111)
        
        # Simulate collected edge points
        h = 200
        skip_frac = 0.2
        skip_n = int(h * skip_frac)
        
        # Draw cone outline with points
        center_x = 100
        for y in range(h):
            width = 10 + (y * 0.5)
            if y >= skip_n:  # Points used for fitting
                ax.plot([center_x - width, center_x + width], [y, y], 'go', markersize=2, alpha=0.6)
            else:  # Skipped points
                ax.plot([center_x - width, center_x + width], [y, y], 'ro', markersize=2, alpha=0.3)
        
        ax.axhline(y=skip_n, color='red', linestyle='--', linewidth=2, label=f'Skip top {int(skip_frac*100)}%')
        ax.set_xlabel('X Position', fontsize=9)
        ax.set_ylabel('Y Position (Top to Bottom)', fontsize=9)
        ax.set_title(f'Line Fit Point Selection (LINE_FIT_START_FRAC={skip_frac})\nGreen=used, Red=skipped', fontsize=10)
        ax.set_ylim(0, h)
        ax.invert_yaxis()
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        
    elif param_name in ["LEFT_SLOPE_MAX", "RIGHT_SLOPE_MIN"]:
        # Show slope constraints on a cone
        fig.clear()
        ax = fig.add_subplot(111)
        
        # Draw a cone shape
        h, w = 250, 200
        center_x = w // 2
        apex_y = 20
        apex_x = center_x
        
        # Draw cone outline
        for y in range(apex_y, h):
            width = (y - apex_y) * 0.6
            ax.plot([apex_x - width, apex_x + width], [y, y], 'k-', linewidth=1, alpha=0.3)
        
        if param_name == "LEFT_SLOPE_MAX":
            # Left line constraint
            slope = -0.05
            x_points = []
            y_points = []
            for y in range(apex_y, h):
                x = slope * (y - apex_y) + apex_x
                x_points.append(x)
                y_points.append(y)
            ax.plot(x_points, y_points, 'r-', linewidth=3, label='Left line (max slope)')
            ax.fill_between(x_points, y_points, [w]*len(y_points), alpha=0.2, color='red')
        else:
            # Right line constraint
            slope = 0.05
            x_points = []
            y_points = []
            for y in range(apex_y, h):
                x = slope * (y - apex_y) + apex_x
                x_points.append(x)
                y_points.append(y)
            ax.plot(x_points, y_points, 'b-', linewidth=3, label='Right line (min slope)')
            ax.fill_between(x_points, y_points, [0]*len(y_points), alpha=0.2, color='blue')
        
        ax.plot(apex_x, apex_y, 'ko', markersize=8, label='Apex')
        ax.set_xlabel('X Position', fontsize=9)
        ax.set_ylabel('Y Position (Top to Bottom)', fontsize=9)
        ax.set_title(f'Slope Constraint: {param_name}', fontsize=10)
        ax.set_ylim(0, h)
        ax.invert_yaxis()
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        
    elif param_name == "TOP_RAMP_START":
        # Show ramp weighting effect
        fig.clear()
        ax1 = fig.add_subplot(1, 2, 1)
        ax2 = fig.add_subplot(1, 2, 2)
        
        # Create test image
        h, w = 200, 150
        test_img = np.zeros((h, w), dtype=np.uint8)
        center_x = w // 2
        for y in range(h):
            width = 10 + (y * 0.5)
            for x in range(w):
                dist = abs(x - center_x)
                if dist < width:
                    test_img[y, x] = 255 - (dist * 4) - (y * 0.4)
        
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title('Original', fontsize=10)
        ax1.axis('off')
        
        # Apply ramp
        ramp_start = 1.5
        ramp = np.linspace(ramp_start, 1.0, h).astype(np.float32)[:, None]
        weighted = np.clip(test_img.astype(np.float32) * ramp, 0, 255).astype(np.uint8)
        ax2.imshow(weighted, cmap='gray')
        ax2.set_title(f'With Ramp (start={ramp_start})\nTop brighter, bottom dimmer', fontsize=9)
        ax2.axis('off')
        
        fig.suptitle('Linear Ramp Weighting Effect', fontsize=11, fontweight='bold')
        
    elif param_name == "ADAPT_BLOCK":
        # Show adaptive threshold blocks
        fig.clear()
        ax1 = fig.add_subplot(1, 2, 1)
        ax2 = fig.add_subplot(1, 2, 2)
        
        # Create test image with varying intensity
        h, w = 200, 200
        test_img = np.zeros((h, w), dtype=np.uint8)
        for y in range(h):
            for x in range(w):
                # Varying intensity pattern
                test_img[y, x] = 128 + int(50 * np.sin(x * 0.1) * np.cos(y * 0.1))
        
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title('Original Image\n(Varying Intensity)', fontsize=9)
        ax1.axis('off')
        
        # Show block grid
        block = 31
        ax2.imshow(test_img, cmap='gray')
        for i in range(0, h, block):
            ax2.axhline(y=i, color='red', linewidth=1, alpha=0.7)
        for j in range(0, w, block):
            ax2.axvline(x=j, color='red', linewidth=1, alpha=0.7)
        ax2.set_title(f'Block Grid ({block}x{block})\nEach block thresholded separately', fontsize=9)
        ax2.axis('off')
        
        fig.suptitle('Adaptive Threshold Block Size', fontsize=11, fontweight='bold')
        
    elif param_name == "ADAPT_C":
        # Show effect of C constant
        fig.clear()
        ax1 = fig.add_subplot(1, 3, 1)
        ax2 = fig.add_subplot(1, 3, 2)
        ax3 = fig.add_subplot(1, 3, 3)
        
        # Create test image
        h, w = 150, 200
        test_img = np.zeros((h, w), dtype=np.uint8)
        center_x = w // 2
        for y in range(h):
            width = 10 + (y * 0.6)
            for x in range(w):
                dist = abs(x - center_x)
                if dist < width:
                    test_img[y, x] = 200 - (dist * 3) - (y * 0.3)
        
        # Different C values
        for idx, (c_val, ax) in enumerate([(-10, ax1), (-6, ax2), (0, ax3)]):
            block = 31
            thresholded = cv2.adaptiveThreshold(
                test_img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 
                cv2.THRESH_BINARY, block, c_val
            )
            ax.imshow(thresholded, cmap='gray')
            ax.set_title(f'C = {c_val}\n{"More FG" if c_val < 0 else "Less FG"}', fontsize=9)
            ax.axis('off')
        
        fig.suptitle('Adaptive Threshold C Constant Effect', fontsize=11, fontweight='bold')
        
    elif param_name == "BLUR_KSIZE":
        # Show blur effect on test image
        fig.clear()
        ax1 = fig.add_subplot(1, 3, 1)
        ax2 = fig.add_subplot(1, 3, 2)
        ax3 = fig.add_subplot(1, 3, 3)
        
        # Create test image with fine details
        h, w = 150, 200
        test_img = np.zeros((h, w), dtype=np.uint8)
        for y in range(h):
            for x in range(w):
                # Create pattern with fine details
                test_img[y, x] = 128 + int(50 * np.sin(x * 0.2) * np.sin(y * 0.2))
        
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title('Original\n(Sharp)', fontsize=9)
        ax1.axis('off')
        
        blurred_3 = cv2.GaussianBlur(test_img, (3, 3), 0)
        ax2.imshow(blurred_3, cmap='gray')
        ax2.set_title('Blur k=3\n(Light)', fontsize=9)
        ax2.axis('off')
        
        blurred_9 = cv2.GaussianBlur(test_img, (9, 9), 0)
        ax3.imshow(blurred_9, cmap='gray')
        ax3.set_title('Blur k=9\n(Strong)', fontsize=9)
        ax3.axis('off')
        
        fig.suptitle('Gaussian Blur Effect', fontsize=11, fontweight='bold')
        
    elif param_name in ["OPEN_K", "CLOSE_K"]:
        # Show morphological operations
        fig.clear()
        ax1 = fig.add_subplot(1, 3, 1)
        ax2 = fig.add_subplot(1, 3, 2)
        ax3 = fig.add_subplot(1, 3, 3)
        
        # Create test image with noise
        h, w = 150, 200
        test_img = np.zeros((h, w), dtype=np.uint8)
        center_x = w // 2
        for y in range(h):
            width = 10 + (y * 0.5)
            for x in range(w):
                dist = abs(x - center_x)
                if dist < width:
                    test_img[y, x] = 255
        
        # Add noise
        noise = np.random.randint(0, 256, (h, w))
        test_img = np.where(noise < 30, 255, test_img)  # Small noise spots
        test_img = np.where(noise > 240, 0, test_img)  # Small holes
        
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title('Original\n(With Noise)', fontsize=9)
        ax1.axis('off')
        
        if param_name == "OPEN_K":
            k = 3
            opened = cv2.morphologyEx(test_img, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
            ax2.imshow(opened, cmap='gray')
            ax2.set_title(f'Opening k={k}\n(Removes small noise)', fontsize=9)
            ax2.axis('off')
            
            k = 7
            opened = cv2.morphologyEx(test_img, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
            ax3.imshow(opened, cmap='gray')
            ax3.set_title(f'Opening k={k}\n(Removes more noise)', fontsize=9)
            ax3.axis('off')
            fig.suptitle('Morphological Opening (Removes Noise)', fontsize=11, fontweight='bold')
        else:
            k = 3
            closed = cv2.morphologyEx(test_img, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
            ax2.imshow(closed, cmap='gray')
            ax2.set_title(f'Closing k={k}\n(Fills small holes)', fontsize=9)
            ax2.axis('off')
            
            k = 7
            closed = cv2.morphologyEx(test_img, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
            ax3.imshow(closed, cmap='gray')
            ax3.set_title(f'Closing k={k}\n(Fills larger holes)', fontsize=9)
            ax3.axis('off')
            fig.suptitle('Morphological Closing (Fills Holes)', fontsize=11, fontweight='bold')
        
    elif param_name == "MIN_FG_PER_ROW":
        # Show row threshold effect
        fig.clear()
        ax = fig.add_subplot(111)
        
        # Simulate rows with different numbers of foreground pixels
        h = 200
        center_x = 100
        
        for y in range(h):
            width = 5 + (y * 0.4)
            num_pixels = int(width * 2)
            if num_pixels >= 8:  # MIN_FG_PER_ROW threshold
                ax.plot([center_x - width, center_x + width], [y, y], 'g-', linewidth=2, alpha=0.7, label='Included' if y == 50 else '')
            else:
                ax.plot([center_x - width, center_x + width], [y, y], 'r-', linewidth=1, alpha=0.3, label='Excluded' if y == 10 else '')
        
        ax.axhline(y=20, color='orange', linestyle='--', linewidth=2, label='Threshold: 8 pixels/row')
        ax.set_xlabel('X Position', fontsize=9)
        ax.set_ylabel('Y Position (Top to Bottom)', fontsize=9)
        ax.set_title('MIN_FG_PER_ROW Effect\nGreen=included, Red=excluded', fontsize=10)
        ax.set_ylim(0, h)
        ax.invert_yaxis()
        ax.legend(fontsize=8, loc='lower right')
        ax.grid(True, alpha=0.3)
        
    elif param_name == "APEX_CLAMP_FRAC":
        # Show apex clamping
        fig.clear()
        ax = fig.add_subplot(111)
        
        h, w = 250, 200
        center_x = w // 2
        clamp_frac = 0.10
        clamp_y = int(h * clamp_frac)
        
        # Draw cone
        for y in range(clamp_y, h):
            width = (y - clamp_y) * 0.6
            ax.plot([center_x - width, center_x + width], [y, y], 'k-', linewidth=1, alpha=0.3)
        
        # Show original apex (too low) and clamped apex
        original_apex_y = int(h * 0.15)
        ax.plot(center_x, original_apex_y, 'ro', markersize=10, label='Original apex (too low)')
        ax.plot(center_x, clamp_y, 'go', markersize=10, label=f'Clamped apex (top {int(clamp_frac*100)}%)')
        ax.axhline(y=clamp_y, color='green', linestyle='--', linewidth=2, alpha=0.7)
        
        ax.set_xlabel('X Position', fontsize=9)
        ax.set_ylabel('Y Position (Top to Bottom)', fontsize=9)
        ax.set_title(f'Apex Clamping (APEX_CLAMP_FRAC={clamp_frac})', fontsize=10)
        ax.set_ylim(0, h)
        ax.invert_yaxis()
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        
    elif param_name == "FG_MIN_RATIO":
        # Show foreground ratio effect
        fig.clear()
        ax1 = fig.add_subplot(1, 2, 1)
        ax2 = fig.add_subplot(1, 2, 2)
        
        # Create test image (mostly dark with bright cone)
        h, w = 200, 150
        test_img = np.zeros((h, w), dtype=np.uint8)
        center_x = w // 2
        for y in range(h):
            width = 10 + (y * 0.5)
            for x in range(w):
                dist = abs(x - center_x)
                if dist < width:
                    test_img[y, x] = 255
        
        # Low FG ratio (will be inverted)
        fg_ratio = test_img.mean() / 255.0
        ax1.imshow(test_img, cmap='gray')
        ax1.set_title(f'Original\n(FG ratio: {fg_ratio:.2f})', fontsize=9)
        ax1.axis('off')
        
        # Inverted (if ratio < threshold)
        threshold = 0.35
        if fg_ratio < threshold:
            inverted = cv2.bitwise_not(test_img)
            ax2.imshow(inverted, cmap='gray')
            ax2.set_title(f'Inverted\n(ratio < {threshold})', fontsize=9)
        else:
            ax2.imshow(test_img, cmap='gray')
            ax2.set_title(f'Not Inverted\n(ratio >= {threshold})', fontsize=9)
        ax2.axis('off')
        
        fig.suptitle('Foreground Ratio Auto-Invert', fontsize=11, fontweight='bold')
        
    else:
        # Default: simple text
        ax = fig.add_subplot(111)
        ax.axis('off')
        ax.text(0.5, 0.5, f'Visual diagram for\n{param_name}\n\nSee description text', 
                ha='center', va='center', fontsize=12)
    
    fig.tight_layout()
    return fig


def show_param_info(param_name: str, parent):
    """Show a popup window with parameter description and visual diagram."""
    popup = tk.Toplevel(parent)
    popup.title(f"Parameter Info: {param_name}")
    popup.geometry("600x500")
    
    # Description text
    desc_frame = tk.Frame(popup)
    desc_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    info = PARAM_DESCRIPTIONS.get(param_name, {"desc": "No description available.", "visual": None})
    desc_text = tk.Text(desc_frame, wrap=tk.WORD, height=6, font=("Arial", 11))
    desc_text.pack(fill=tk.BOTH, expand=True)
    desc_text.insert("1.0", info["desc"])
    desc_text.config(state=tk.DISABLED)
    
    # Visual diagram
    if info.get("visual"):
        visual_frame = tk.Frame(popup)
        visual_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        fig = create_visual_diagram(param_name, width=550, height=300)
        canvas = FigureCanvasTkAgg(fig, visual_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    
    # Close button
    close_btn = tk.Button(popup, text="Close", command=popup.destroy)
    close_btn.pack(pady=10)


def build_gui(default_image: Path):
    root = tk.Tk()
    root.title("Cone GUI - row-based fit")

    # Main layout: controls on the left, then a 3-row grid:
    # row 0: 3 images (original + first two steps)
    # row 1: 4 images (remaining steps)
    # row 2: 2 images (previous annotated, latest annotated)
    main = tk.Frame(root)
    main.pack(fill=tk.BOTH, expand=True)
    main.grid_columnconfigure(0, weight=0)
    main.grid_columnconfigure(1, weight=1)
    for r in range(3):
        main.grid_rowconfigure(r, weight=1)

    # Control panel (column 0) - make it scrollable
    control_container = tk.Frame(main)
    control_container.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=8, pady=8)
    
    # Canvas for scrolling
    canvas = tk.Canvas(control_container, width=350)
    scrollbar = tk.Scrollbar(control_container, orient="vertical", command=canvas.yview)
    control = tk.Frame(canvas)
    
    control.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=control, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    entries = {}
    sliders = {}
    value_labels = {}
    row = 0
    
    # Debounce timer for auto-apply
    apply_timer = None
    
    def schedule_apply():
        """Schedule an apply with debouncing to avoid excessive processing."""
        nonlocal apply_timer
        if apply_timer:
            root.after_cancel(apply_timer)
        apply_timer = root.after(200, apply_params)  # 200ms debounce for smooth updates
    
    for name, val in DEFAULTS.items():
        # Parameter name label
        tk.Label(control, text=name, font=("Arial", 8)).grid(row=row, column=0, sticky="w", padx=2)
        
        # Info button
        info_btn = tk.Button(control, text="ℹ️", width=2, height=1,
                            command=lambda n=name: show_param_info(n, root),
                            font=("Arial", 7), cursor="hand2")
        info_btn.grid(row=row, column=1, padx=1, sticky="w")
        
        # Get range for this parameter
        if name in PARAM_RANGES:
            min_val, max_val, step = PARAM_RANGES[name]
        else:
            # Default ranges if not specified
            if isinstance(val, int):
                min_val, max_val, step = 0, 100, 1
            else:
                min_val, max_val, step = 0.0, 10.0, 0.1
        
        # Create slider
        slider_frame = tk.Frame(control)
        slider_frame.grid(row=row, column=2, sticky="ew", padx=2)
        control.columnconfigure(2, weight=1)
        
        slider = tk.Scale(slider_frame, from_=min_val, to=max_val, 
                         resolution=step, orient=tk.HORIZONTAL,
                         length=150, showvalue=False)
        slider.set(float(val))
        slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sliders[name] = slider
        
        # Value display label
        value_label = tk.Label(control, text=f"{val:.3f}" if isinstance(val, float) else str(val),
                              width=8, font=("Arial", 8), anchor="e")
        value_label.grid(row=row, column=3, padx=2, sticky="e")
        value_labels[name] = value_label
        
        # Update value label when slider moves
        def update_label(n=name, lbl=value_label, s=slider):
            val = s.get()
            # For odd-only parameters, ensure value is odd
            if n in ["BLUR_KSIZE", "ADAPT_BLOCK", "OPEN_K", "CLOSE_K"]:
                val = int(val)
                if val % 2 == 0:
                    val = max(3, val - 1)  # Make odd, minimum 3
                    s.set(val)
            
            if n in PARAM_RANGES:
                _, _, step = PARAM_RANGES[n]
                if step >= 1:
                    lbl.config(text=f"{int(val)}")
                else:
                    lbl.config(text=f"{val:.3f}")
            else:
                lbl.config(text=f"{val:.3f}")
            # Always schedule apply when slider moves
            schedule_apply()
        
        slider.config(command=lambda v, n=name: update_label(n))
        
        # Also create hidden entry for compatibility with existing code
        ent = tk.Entry(control, width=0)
        ent.insert(0, str(val))
        entries[name] = ent
        
        row += 1

    # Separator
    tk.Frame(control, height=2, bg="gray").grid(row=row, column=0, columnspan=4, sticky="ew", pady=4)
    row += 1
    
    status_var = tk.StringVar(value="Ready")
    tk.Label(control, textvariable=status_var, fg="blue", wraplength=250, font=("Arial", 8)).grid(row=row, column=0, columnspan=4, sticky="w", padx=2, pady=2)
    row += 1
    angle_var = tk.StringVar(value="Angle: --")

    img_path_var = tk.StringVar(value=str(default_image))

    def load_image():
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"), ("All files", "*.*")],
        )
        if path:
            img_path_var.set(path)
            apply_params()

    # Button row
    button_frame = tk.Frame(control)
    button_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=4)
    tk.Button(button_frame, text="Load Image", command=load_image).pack(side=tk.LEFT, padx=2)
    tk.Button(button_frame, text="Apply", command=lambda: apply_params()).pack(side=tk.LEFT, padx=2)
    tk.Button(button_frame, text="Reset", command=lambda: reset_to_defaults()).pack(side=tk.LEFT, padx=2)
    row += 1
    
    button_frame2 = tk.Frame(control)
    button_frame2.grid(row=row, column=0, columnspan=4, sticky="ew", pady=2)
    tk.Button(button_frame2, text="Save Params", command=lambda: save_params()).pack(side=tk.LEFT, padx=2)
    tk.Button(button_frame2, text="Load Params", command=lambda: load_params()).pack(side=tk.LEFT, padx=2)
    tk.Button(button_frame2, text="Export Image", command=lambda: export_image()).pack(side=tk.LEFT, padx=2)
    row += 1
    tk.Label(control, textvariable=angle_var, font=("Helvetica", 18, "bold"), fg="dark green").grid(
        row=row, column=0, columnspan=4, sticky="w", pady=6
    )

    # Row 0: 3 images (original + first two steps)
    row0 = tk.Frame(main)
    row0.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
    lbl_top = []
    top_keys = ["original", "gray", "clahe_blur"]
    for key in top_keys:
        sub = tk.Frame(row0)
        sub.pack(side=tk.LEFT, padx=4, pady=2)
        tk.Label(sub, text=key).pack()
        lbl = tk.Label(sub)
        lbl.pack()
        lbl_top.append((key, lbl))

    # Row 1: 4 images (remaining steps)
    row1 = tk.Frame(main)
    row1.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
    lbl_steps = {}
    mid_keys = ["gamma", "weighted", "mask", "lines"]
    for key in mid_keys:
        sub = tk.Frame(row1)
        sub.pack(side=tk.LEFT, padx=4, pady=2)
        tk.Label(sub, text=key).pack()
        lbl = tk.Label(sub)
        lbl.pack()
        lbl_steps[key] = lbl

    # Row 2: previous annotated (left) and current annotated (right)
    row2 = tk.Frame(main)
    row2.grid(row=2, column=1, sticky="nsew", padx=8, pady=8)
    tk.Label(row2, text="Previous Annotated").pack(side=tk.LEFT, padx=4)
    lbl_prev = tk.Label(row2)
    lbl_prev.pack(side=tk.LEFT, padx=4)
    tk.Label(row2, text="Latest Annotated").pack(side=tk.LEFT, padx=4)
    lbl_annotated = tk.Label(row2)
    lbl_annotated.pack(side=tk.LEFT, padx=4)

    # Keep references to PhotoImages to avoid GC
    images_cache = {}

    def get_params_from_sliders():
        """Get current parameter values from sliders."""
        params = {}
        for name, slider in sliders.items():
            val = slider.get()
            # Round to appropriate precision
            if name in PARAM_RANGES:
                _, _, step = PARAM_RANGES[name]
                if step >= 1:
                    params[name] = int(round(val))
                else:
                    params[name] = round(val, 3)
            else:
                params[name] = val
        return params
    
    def reset_to_defaults():
        """Reset all sliders to default values."""
        for name, default_val in DEFAULTS.items():
            if name in sliders:
                sliders[name].set(float(default_val))
        apply_params()
        status_var.set("Reset to defaults")
    
    def export_image():
        """Export the current annotated image."""
        if "annotated" not in images_cache:
            status_var.set("No image to export")
            return
        try:
            export_path = filedialog.asksaveasfilename(
                title="Export annotated image",
                defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("All files", "*.*")],
            )
            if not export_path:
                return
            # Get the original annotated image from result
            img_path = Path(img_path_var.get())
            frame = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
            if frame is None:
                status_var.set("Cannot load image for export")
                return
            params = get_params_from_sliders()
            result = process_image(frame, params)
            cv2.imwrite(str(export_path), result["annotated"])
            status_var.set(f"Exported to {Path(export_path).name}")
        except Exception as e:
            status_var.set(f"Export error: {e}")
    
    def save_params():
        try:
            import csv
            params = get_params_from_sliders()
            save_path = filedialog.asksaveasfilename(
                title="Save parameters",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
            )
            if not save_path:
                return
            with open(save_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "value"])
                for k, v in params.items():
                    writer.writerow([k, v])
            status_var.set(f"Saved params to {Path(save_path).name}")
        except Exception as e:
            status_var.set(f"Save error: {e}")

    def load_params():
        try:
            import csv
            load_path = filedialog.askopenfilename(
                title="Load parameters",
                filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
            )
            if not load_path:
                return
            loaded = {}
            with open(load_path, "r", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for rowcsv in reader:
                    if len(rowcsv) >= 2:
                        loaded[rowcsv[0]] = rowcsv[1]
            for k, v in loaded.items():
                if k in sliders:
                    try:
                        sliders[k].set(float(v))
                    except ValueError:
                        continue
            status_var.set(f"Loaded params from {Path(load_path).name}")
            apply_params()  # Apply loaded parameters immediately
        except Exception as e:
            status_var.set(f"Load error: {e}")

    def apply_params():
        try:
            params = get_params_from_sliders()
            # For integer params ensure proper type
            for k in ["CLAHE_TILE", "BLUR_KSIZE", "ADAPT_BLOCK", "OPEN_K", "CLOSE_K", "MIN_FG_PER_ROW"]:
                params[k] = int(params[k])
            img_path = Path(img_path_var.get())
            frame = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
            if frame is None:
                status_var.set(f"Cannot load image: {img_path}")
                return
            result = process_image(frame, params)

            # shift annotated to previous
            if "annotated" in images_cache:
                images_cache["prev"] = images_cache["annotated"]
                lbl_prev.configure(image=images_cache["prev"])
                lbl_prev.image = images_cache["prev"]

            # Use original_with_band if available, otherwise use raw frame
            original_display = result.get("original_with_band", frame)
            images_cache["original"] = np_to_tk(original_display, max_w=320, max_h=320)
            for key, lbl in lbl_top:
                if key == "original":
                    lbl.configure(image=images_cache["original"])
                    lbl.image = images_cache["original"]
                else:
                    images_cache[key] = np_to_tk(result["steps"][key], max_w=320, max_h=320)
                    lbl.configure(image=images_cache[key])
                    lbl.image = images_cache[key]

            for key in mid_keys:
                images_cache[key] = np_to_tk(result["steps"][key], max_w=220, max_h=220)
                lbl_steps[key].configure(image=images_cache[key])
                lbl_steps[key].image = images_cache[key]

            images_cache["annotated"] = np_to_tk(result["annotated"], max_w=320, max_h=320)
            lbl_annotated.configure(image=images_cache["annotated"])
            lbl_annotated.image = images_cache["annotated"]

            angle = result["angle_deg"]
            angle_text = f"Angle: {angle:.2f} deg" if angle is not None else "Angle unavailable"
            status_var.set(angle_text)
            angle_var.set(angle_text)
        except Exception as e:
            status_var.set(f"Error: {e}")

    apply_params()
    root.mainloop()


def main():
    try:
        default_input_path = _find_local_image(CURRENT_DIR)
    except FileNotFoundError:
        cfg = get_imaging_config()
        default_input_dir = Path(cfg.get("default_input_dir", CURRENT_DIR))
        default_input_file = cfg.get("default_input_file", "")
        default_input_path = default_input_dir / default_input_file
    build_gui(default_input_path)


if __name__ == "__main__":
    main()

