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


def _find_local_image(base_dir: Path, base_name: str = "Dense_Cone") -> Path:
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
    """CLAHE + blur to stabilize thresholding."""
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    blur = cv2.GaussianBlur(eq, (5, 5), 0)
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


def detect_cone(img_bgr: np.ndarray, apex_override: np.ndarray | None = None):
    """
    Detect cone envelope and measure spray angle.
    Returns dictionary with annotations and measurements.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    processed = _preprocess(gray)

    # Binary mask via Otsu; invert if background dominates
    _, mask = cv2.threshold(processed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if mask.mean() > 127:
        mask = cv2.bitwise_not(mask)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)

    contour = _pick_contour(mask, apex_override)
    if contour is None or cv2.contourArea(contour) < 500:
        raise RuntimeError("No cone-like contour found")

    hull = cv2.convexHull(contour)
    if apex_override is not None:
        apex = apex_override
    else:
        apex = None

    apex, left_base, right_base, angle_deg = _compute_cone_angle(hull) if apex is None else _compute_cone_angle(np.vstack([hull, [[apex]]]))
    # If we forced apex but angle calc used hull+apex may still pick hull apex; override final apex to user click
    if apex_override is not None:
        apex = apex_override
    if angle_deg is None:
        raise RuntimeError("Could not compute cone angle from detected hull")

    overlay = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    annotated = img_bgr.copy()

    for img in (overlay, annotated):
        cv2.drawContours(img, [hull], -1, (0, 255, 0), 2)
        cv2.circle(img, tuple(apex.astype(int)), 6, (0, 0, 255), -1)
        cv2.line(img, tuple(apex.astype(int)), tuple(left_base.astype(int)), (255, 0, 0), 2)
        cv2.line(img, tuple(apex.astype(int)), tuple(right_base.astype(int)), (255, 0, 0), 2)
        mid_point = ((left_base + right_base) / 2).astype(int)
        cv2.putText(
            img,
            f"{angle_deg:.1f} deg",
            tuple(mid_point),
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
        "apex": apex,
        "left_base": left_base,
        "right_base": right_base,
    }


def build_output_dir(base_dir: Path) -> Path:
    """
    For this tool we keep outputs in the provided directory (no subfolder) to
    match the user's request to keep results alongside the script.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def main():
    # Default: image lives alongside this script, named Cone_Trial_Image.[tiff|png|jpg...]
    default_input_path = _find_local_image(CURRENT_DIR)
    parser = argparse.ArgumentParser(description="Spray cone detection and angle measurement")
    parser.add_argument("--input", type=Path, default=default_input_path, help="Path to image (Cone_Trial_Image.* by default)")
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
    result = detect_cone(frame, apex_override=apex_override)

    # Save into the same folder (or user-provided output_root) with stable names.
    save_dir = build_output_dir(output_root)
    annotated_path = save_dir / "Cone_Tester_annotated.png"
    overlay_path = save_dir / "Cone_Tester_mask_overlay.png"
    mask_path = save_dir / "Cone_Tester_mask.png"

    cv2.imwrite(str(annotated_path), result["annotated"])
    cv2.imwrite(str(overlay_path), result["overlay"])
    cv2.imwrite(str(mask_path), result["mask"])

    print(f"[Cone_Tester] Angle: {result['angle_deg']:.2f} degrees")
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

