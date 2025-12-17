"""
Cone angle detection using contour-based method with PCA (directional statistics).

This module computes the spray cone angle from a single TIFF image by:
1. Finding the largest contour representing the spray
2. Splitting the contour into left and right edges
3. Using PCA to find the dominant direction of each edge
4. Computing the angle between the two PCA directions
"""

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np

# Debug mode: set to True to overlay contour and PCA vectors on output image
DEBUG_MODE = True

# Allow running from repo root
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config_loader import get_imaging_config  # noqa: E402

# Processing parameters
GAUSSIAN_BLUR_KSIZE = 5  # Must be odd
GAUSSIAN_BLUR_SIGMA = 0  # 0 = auto
MORPH_CLOSE_KSIZE = 7  # Must be odd
MIN_CONTOUR_AREA_RATIO = 0.01  # Minimum contour area as fraction of image area


def load_image(image_path: Path) -> np.ndarray:
    """
    Load a TIFF image and convert to grayscale.
    
    Args:
        image_path: Path to the TIFF image file
        
    Returns:
        Grayscale image as numpy array (uint8)
        
    Raises:
        FileNotFoundError: If image file doesn't exist
        ValueError: If image cannot be loaded
    """
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Cannot load image: {image_path}")
    
    # Convert to grayscale if needed
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    elif len(img.shape) == 2:
        gray = img.copy()
    else:
        raise ValueError(f"Unexpected image shape: {img.shape}")
    
    # Normalize to 8-bit if needed
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    
    return gray


def preprocess_image(gray: np.ndarray) -> np.ndarray:
    """
    Preprocess the grayscale image: blur and threshold.
    
    Args:
        gray: Input grayscale image
        
    Returns:
        Binary mask (foreground = 0, background = 255)
    """
    # Apply Gaussian blur
    ksize = GAUSSIAN_BLUR_KSIZE if GAUSSIAN_BLUR_KSIZE % 2 == 1 else GAUSSIAN_BLUR_KSIZE + 1
    blurred = cv2.GaussianBlur(gray, (ksize, ksize), GAUSSIAN_BLUR_SIGMA)
    
    # Otsu's thresholding
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Check if we need to invert (if most of image is foreground, likely inverted)
    fg_ratio = (binary < 128).sum() / binary.size
    if fg_ratio > 0.5:
        binary = cv2.bitwise_not(binary)
    
    # Apply morphological closing to clean noise and fill gaps
    close_k = MORPH_CLOSE_KSIZE if MORPH_CLOSE_KSIZE % 2 == 1 else MORPH_CLOSE_KSIZE + 1
    kernel = np.ones((close_k, close_k), np.uint8)
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    
    # Clear image borders to prevent detecting frame as contour
    # Set border pixels to background (255 = white background)
    h, w = closed.shape
    border_px = max(5, min(w, h) // 100)  # At least 5 pixels, or 1% of smaller dimension
    closed[:border_px, :] = 255  # Top border
    closed[-border_px:, :] = 255  # Bottom border
    closed[:, :border_px] = 255  # Left border
    closed[:, -border_px:] = 255  # Right border
    
    return closed


def find_spray_contour(binary: np.ndarray, border_px: int = 5) -> np.ndarray:
    """
    Find the largest external contour representing the spray.
    
    Args:
        binary: Binary mask image
        border_px: Number of pixels cleared from borders in preprocessing
        
    Returns:
        Contour points as numpy array (N, 1, 2)
        
    Raises:
        RuntimeError: If no suitable contour is found
    """
    # cv2.findContours requires foreground to be white (255) and background black (0)
    # The binary image from preprocessing has background=255 (white), foreground=0 (black)
    # So we need to invert it for findContours to work
    binary_for_contours = cv2.bitwise_not(binary)
    
    # Find external contours
    contours, _ = cv2.findContours(binary_for_contours, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    
    if not contours:
        raise RuntimeError("No contours found in image")
    
    print(f"[Cone_3] Found {len(contours)} contours")
    
    h, w = binary.shape
    min_area = MIN_CONTOUR_AREA_RATIO * h * w
    max_area = 0.8 * h * w  # Reject contours that are too large (likely frame)
    
    filtered_contours = []
    for c in contours:
        area = cv2.contourArea(c)
        
        # Filter by area
        if area < min_area or area > max_area:
            continue
        
        # Get bounding box to check if contour touches edges
        x, y, cw, ch = cv2.boundingRect(c)
        
        # Reject contours that touch image borders (likely frame artifacts)
        # Use margin based on border_px used in preprocessing
        margin = max(5, border_px + 2)  # Small margin
        touches_border = (x <= margin or y <= margin or 
                         x + cw >= w - margin or y + ch >= h - margin)
        
        if touches_border:
            continue
        
        # Filter by aspect ratio - spray should be taller than wide (relaxed)
        aspect_ratio = ch / max(cw, 1)
        if aspect_ratio < 0.15:  # Relaxed - allow wider sprays
            continue
        
        filtered_contours.append(c)
    
    # If no contours pass strict filtering, try relaxed filtering
    if not filtered_contours:
        print(f"[Cone_3] Warning: No contours passed strict filtering, trying relaxed criteria...")
        # Relaxed filtering: allow contours that are near but not exactly on border
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area * 0.3 or area > max_area:  # Even lower min area
                continue
            
            x, y, cw, ch = cv2.boundingRect(c)
            
            # More relaxed border check - only reject if clearly on border
            margin = 2
            touches_border = (x <= margin or y <= margin or 
                             x + cw >= w - margin or y + ch >= h - margin)
            
            if touches_border:
                continue
            
            # Very relaxed aspect ratio
            aspect_ratio = ch / max(cw, 1)
            if aspect_ratio < 0.05:  # Very relaxed - almost any shape
                continue
            
            filtered_contours.append(c)
    
    # Final fallback: accept any contour that's not the full frame
    if not filtered_contours:
        print(f"[Cone_3] Warning: No contours passed relaxed filtering, using final fallback...")
        print(f"[Cone_3] Total contours available: {len(contours)}")
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            x, y, cw, ch = cv2.boundingRect(c)
            aspect = ch / max(cw, 1)
            
            # Only reject if it's clearly the full frame (very large)
            if area > max_area * 0.98:  # Reject if >98% of max area (almost entire frame)
                print(f"[Cone_3]   Contour {i}: REJECTED - too large (area={area:.0f} > {max_area*0.98:.0f})")
                continue
            
            # Accept any contour that's not tiny
            if area < 100:  # Absolute minimum - at least 100 pixels
                print(f"[Cone_3]   Contour {i}: REJECTED - too small (area={area:.0f} < 100)")
                continue
            
            # Don't check borders or aspect ratio in final fallback
            print(f"[Cone_3]   Contour {i}: ACCEPTED in fallback (area={area:.0f}, bbox=({x},{y},{cw},{ch}), aspect={aspect:.2f})")
            filtered_contours.append(c)
    
    if not filtered_contours:
        # Print diagnostic info
        print(f"[Cone_3] Diagnostic: Image size {w}x{h}, min_area={min_area:.0f}, max_area={max_area:.0f}")
        print(f"[Cone_3] All {len(contours)} contours were rejected")
        raise RuntimeError(f"No suitable contours found after all filtering attempts (area: {min_area:.0f}-{max_area:.0f}, not touching borders)")
    
    # Select the largest contour from filtered set
    largest_contour = max(filtered_contours, key=cv2.contourArea)
    
    return largest_contour


def split_contour_edges(contour: np.ndarray, nozzle_x: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """
    Split contour points into left and right edges.
    
    Args:
        contour: Contour points (N, 1, 2) or (N, 2)
        nozzle_x: X-coordinate of nozzle. If None, uses mean x of all points.
        
    Returns:
        Tuple of (left_edge_points, right_edge_points), each as (M, 2) array
    """
    # Reshape contour to (N, 2) if needed
    if contour.ndim == 3:
        points = contour.reshape(-1, 2)
    else:
        points = contour
    
    if len(points) == 0:
        raise ValueError("Contour has no points")
    
    # Determine split x-coordinate
    if nozzle_x is None:
        split_x = np.mean(points[:, 0])
    else:
        split_x = float(nozzle_x)
    
    # Split into left and right edges
    left_mask = points[:, 0] < split_x
    right_mask = points[:, 0] >= split_x
    
    left_points = points[left_mask]
    right_points = points[right_mask]
    
    if len(left_points) < 3:
        raise ValueError(f"Left edge has too few points: {len(left_points)}")
    if len(right_points) < 3:
        raise ValueError(f"Right edge has too few points: {len(right_points)}")
    
    return left_points, right_points


def compute_pca_direction(points: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Compute the dominant direction of a set of points using PCA (SVD).
    
    Args:
        points: Array of points (N, 2)
        
    Returns:
        Tuple of (direction_vector, variance_explained)
        direction_vector: Unit vector (2,) pointing in dominant direction
        variance_explained: Fraction of variance explained by first principal component
    """
    if len(points) < 2:
        raise ValueError("Need at least 2 points for PCA")
    
    # Center the points
    mean = np.mean(points, axis=0)
    centered = points - mean
    
    # Compute SVD
    # For 2D points, we can use the covariance matrix
    cov = np.cov(centered.T)
    
    # Eigenvalue decomposition (more numerically stable for 2x2)
    eigenvals, eigenvecs = np.linalg.eigh(cov)
    
    # Sort by eigenvalue (largest first)
    idx = np.argsort(eigenvals)[::-1]
    eigenvals = eigenvals[idx]
    eigenvecs = eigenvecs[:, idx]
    
    # First principal component (dominant direction)
    direction = eigenvecs[:, 0]
    
    # Ensure direction points downward (positive y in image coordinates)
    if direction[1] < 0:
        direction = -direction
    
    # Normalize to unit vector
    norm = np.linalg.norm(direction)
    if norm > 1e-10:
        direction = direction / norm
    else:
        # Fallback: vertical direction
        direction = np.array([0.0, 1.0])
    
    # Variance explained by first component
    total_var = np.sum(eigenvals)
    if total_var > 1e-10:
        variance_explained = eigenvals[0] / total_var
    else:
        variance_explained = 1.0
    
    return direction, variance_explained


def compute_cone_angle(left_dir: np.ndarray, right_dir: np.ndarray) -> float:
    """
    Compute the cone angle between two direction vectors.
    
    Args:
        left_dir: Unit direction vector for left edge (2,)
        right_dir: Unit direction vector for right edge (2,)
        
    Returns:
        Cone angle in degrees (acute angle between the two directions)
    """
    # Compute angle between vectors using dot product
    dot_product = np.clip(np.dot(left_dir, right_dir), -1.0, 1.0)
    angle_rad = np.arccos(dot_product)
    angle_deg = np.degrees(angle_rad)
    
    return angle_deg


def detect_cone_angle(image_path: Path, nozzle_x: float | None = None) -> tuple[float, np.ndarray, dict]:
    """
    Main function to detect spray cone angle from a TIFF image.
    
    Args:
        image_path: Path to input TIFF image
        nozzle_x: Optional x-coordinate of nozzle
        
    Returns:
        Tuple of (angle_degrees, annotated_image, debug_info)
        angle_degrees: Detected cone angle in degrees
        annotated_image: BGR image with annotations
        debug_info: Dictionary with debug information
    """
    # Load and preprocess
    gray = load_image(image_path)
    binary = preprocess_image(gray)
    
    # Store early debug info (always available)
    early_debug_info = {
        "gray": gray,
        "binary": binary,
        "image_path": image_path,
    }
    
    # Find spray contour (pass border_px used in preprocessing)
    h, w = binary.shape
    border_px_used = max(5, min(w, h) // 100)
    
    try:
        contour = find_spray_contour(binary, border_px_used)
    except RuntimeError as e:
        # If contour finding fails, return partial info
        early_debug_info["error"] = str(e)
        annotated = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        cv2.putText(annotated, "Contour detection failed", (20, 40),
                   cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        return None, annotated, early_debug_info
    
    # Split into edges
    left_points, right_points = split_contour_edges(contour, nozzle_x)
    
    # Compute PCA directions
    left_dir, left_var = compute_pca_direction(left_points)
    right_dir, right_var = compute_pca_direction(right_points)
    
    # Compute cone angle
    angle_deg = compute_cone_angle(left_dir, right_dir)
    
    # Create annotated image
    annotated = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    
    h, w = gray.shape
    
    # Draw lines along the actual contour edges
    # Find the topmost point (apex) for each edge
    left_top_idx = np.argmin(left_points[:, 1])  # Minimum y = top
    right_top_idx = np.argmin(right_points[:, 1])
    
    # Get topmost points (apex)
    left_top = left_points[left_top_idx]
    right_top = right_points[right_top_idx]
    
    # Calculate line positions for middle 80% of image (top 10% and bottom 10% free)
    top_y = h * 0.10  # Start at 10% from top
    bottom_y = h * 0.90  # End at 90% from top (10% from bottom)
    
    # Project lines from apex along PCA direction to the desired y positions
    # left_dir and right_dir are normalized direction vectors pointing downward
    # We need to find x positions at top_y and bottom_y along each direction
    
    # For left edge: find x at top_y and bottom_y
    # Line equation: x = left_top[0] + left_dir[0] * t, y = left_top[1] + left_dir[1] * t
    # Solve for t when y = top_y: t = (top_y - left_top[1]) / left_dir[1]
    left_t_top = (top_y - left_top[1]) / left_dir[1] if left_dir[1] != 0 else 0
    left_t_bottom = (bottom_y - left_top[1]) / left_dir[1] if left_dir[1] != 0 else 0
    left_start = left_top + left_dir * left_t_top
    left_end = left_top + left_dir * left_t_bottom
    
    # For right edge: find x at top_y and bottom_y
    right_t_top = (top_y - right_top[1]) / right_dir[1] if right_dir[1] != 0 else 0
    right_t_bottom = (bottom_y - right_top[1]) / right_dir[1] if right_dir[1] != 0 else 0
    right_start = right_top + right_dir * right_t_top
    right_end = right_top + right_dir * right_t_bottom
    
    # Draw left edge line
    cv2.line(annotated,
              (int(left_start[0]), int(left_start[1])),
              (int(left_end[0]), int(left_end[1])),
              (0, 0, 255), 3)
    
    # Draw right edge line
    cv2.line(annotated,
              (int(right_start[0]), int(right_start[1])),
              (int(right_end[0]), int(right_end[1])),
              (0, 0, 255), 3)
    
    # Store centers for debug overlays (using mean of edge points)
    left_center = np.array([np.mean(left_points[:, 0]), np.mean(left_points[:, 1])])
    right_center = np.array([np.mean(right_points[:, 0]), np.mean(right_points[:, 1])])
    
    # Draw debug overlays if debug mode
    if DEBUG_MODE:
        # Draw contour (green)
        cv2.drawContours(annotated, [contour], -1, (0, 255, 0), 2)
        
        # Draw left edge points (cyan dots)
        for pt in left_points[::max(1, len(left_points)//100)]:  # Sample points for visibility
            cv2.circle(annotated, (int(pt[0]), int(pt[1])), 2, (255, 255, 0), -1)
        
        # Draw right edge points (magenta dots)
        for pt in right_points[::max(1, len(right_points)//100)]:  # Sample points for visibility
            cv2.circle(annotated, (int(pt[0]), int(pt[1])), 2, (255, 0, 255), -1)
        
        # Draw PCA vectors (longer arrows)
        vec_length = min(w, h) * 0.15
        # Left PCA vector (bright green)
        left_vec_end = left_center + left_dir * vec_length
        cv2.arrowedLine(annotated,
                       (int(left_center[0]), int(left_center[1])),
                       (int(left_vec_end[0]), int(left_vec_end[1])),
                       (0, 255, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)
        
        # Right PCA vector (bright blue)
        right_vec_end = right_center + right_dir * vec_length
        cv2.arrowedLine(annotated,
                       (int(right_center[0]), int(right_center[1])),
                       (int(right_vec_end[0]), int(right_vec_end[1])),
                       (255, 0, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)
        
        # Draw center points
        cv2.circle(annotated, (int(left_center[0]), int(left_center[1])), 5, (0, 255, 0), -1)
        cv2.circle(annotated, (int(right_center[0]), int(right_center[1])), 5, (255, 0, 0), -1)
    
    # Add angle text in top right
    angle_text = f"Angle: {angle_deg:.2f} deg"
    text_size = cv2.getTextSize(angle_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
    text_x = w - text_size[0] - 20
    text_y = 40
    cv2.putText(annotated, angle_text, (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 0), 2, cv2.LINE_AA)
    
    # Debug info
    debug_info = {
        "contour_area": cv2.contourArea(contour),
        "left_points_count": len(left_points),
        "right_points_count": len(right_points),
        "left_variance_explained": left_var,
        "right_variance_explained": right_var,
        "left_direction": left_dir.tolist(),
        "right_direction": right_dir.tolist(),
        "gray": gray,
        "binary": binary,
        "contour": contour,
        "left_points": left_points,
        "right_points": right_points,
        "left_center": left_center,
        "right_center": right_center,
        "left_dir": left_dir,
        "right_dir": right_dir,
    }
    
    return angle_deg, annotated, debug_info


def create_debug_image(debug_info: dict, image_path: Path) -> np.ndarray:
    """
    Create a debug image showing all processing steps with annotations.
    
    Args:
        debug_info: Dictionary containing all debug information
        image_path: Path to original image (for naming)
        
    Returns:
        Debug visualization image
    """
    gray = debug_info["gray"]
    binary = debug_info["binary"]
    contour = debug_info["contour"]
    left_points = debug_info["left_points"]
    right_points = debug_info["right_points"]
    left_center = debug_info["left_center"]
    right_center = debug_info["right_center"]
    left_dir = debug_info["left_dir"]
    right_dir = debug_info["right_dir"]
    angle_deg = debug_info.get("angle_deg", 0.0)
    
    h, w = gray.shape
    
    # Create a 2x3 grid of images
    # Row 1: Original, Binary, Contour
    # Row 2: Left/Right edges, PCA vectors, Final result
    
    # Resize images to fit in grid (make them smaller)
    grid_h, grid_w = h // 2, w // 3
    scale = min(grid_w / w, grid_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    
    def resize_img(img, target_w, target_h):
        return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
    
    # Step 1: Original grayscale
    orig_colored = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    step1 = resize_img(orig_colored, new_w, new_h)
    # Use yellow text (0, 255, 255 in BGR) for better visibility
    text_color = (0, 255, 255)  # Yellow in BGR
    cv2.putText(step1, "1. Original", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 2: Binary (thresholded)
    binary_colored = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    step2 = resize_img(binary_colored, new_w, new_h)
    cv2.putText(step2, "2. Binary (Otsu)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 3: Contour overlay
    step3 = resize_img(orig_colored.copy(), new_w, new_h)
    # Scale contour points
    contour_scaled = (contour * scale).astype(np.int32)
    cv2.drawContours(step3, [contour_scaled], -1, (0, 255, 0), 2)
    cv2.putText(step3, "3. Detected Contour", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 4: Left/Right edges
    step4 = resize_img(orig_colored.copy(), new_w, new_h)
    # Draw left points (cyan)
    for pt in left_points[::max(1, len(left_points)//50)]:
        pt_scaled = (pt * scale).astype(int)
        if 0 <= pt_scaled[0] < new_w and 0 <= pt_scaled[1] < new_h:
            cv2.circle(step4, tuple(pt_scaled), 2, (255, 255, 0), -1)
    # Draw right points (magenta)
    for pt in right_points[::max(1, len(right_points)//50)]:
        pt_scaled = (pt * scale).astype(int)
        if 0 <= pt_scaled[0] < new_w and 0 <= pt_scaled[1] < new_h:
            cv2.circle(step4, tuple(pt_scaled), 2, (255, 0, 255), -1)
    cv2.putText(step4, "4. Left (cyan) / Right (magenta)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
    
    # Step 5: PCA vectors
    step5 = resize_img(orig_colored.copy(), new_w, new_h)
    left_center_scaled = (left_center * scale).astype(int)
    right_center_scaled = (right_center * scale).astype(int)
    vec_length = min(new_w, new_h) * 0.3
    
    # Left PCA vector (green)
    left_vec_end_scaled = (left_center_scaled + (left_dir * vec_length)).astype(int)
    cv2.arrowedLine(step5, tuple(left_center_scaled), tuple(left_vec_end_scaled),
                   (0, 255, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)
    cv2.circle(step5, tuple(left_center_scaled), 4, (0, 255, 0), -1)
    
    # Right PCA vector (blue)
    right_vec_end_scaled = (right_center_scaled + (right_dir * vec_length)).astype(int)
    cv2.arrowedLine(step5, tuple(right_center_scaled), tuple(right_vec_end_scaled),
                   (255, 0, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)
    cv2.circle(step5, tuple(right_center_scaled), 4, (255, 0, 0), -1)
    
    cv2.putText(step5, "5. PCA Directions", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 6: Final result
    step6 = resize_img(orig_colored.copy(), new_w, new_h)
    # Draw angle lines
    left_end_scaled = (left_center_scaled + (left_dir * vec_length)).astype(int)
    right_end_scaled = (right_center_scaled + (right_dir * vec_length)).astype(int)
    cv2.line(step6, tuple(left_center_scaled), tuple(left_end_scaled), (0, 0, 255), 2)
    cv2.line(step6, tuple(right_center_scaled), tuple(right_end_scaled), (0, 0, 255), 2)
    cv2.putText(step6, f"6. Angle: {angle_deg:.2f} deg", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Combine into grid
    # Pad images to same size
    def pad_to_size(img, target_w, target_h):
        h_img, w_img = img.shape[:2]
        pad_h = target_h - h_img
        pad_w = target_w - w_img
        return cv2.copyMakeBorder(img, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    
    target_w, target_h = new_w, new_h
    step1_pad = pad_to_size(step1, target_w, target_h)
    step2_pad = pad_to_size(step2, target_w, target_h)
    step3_pad = pad_to_size(step3, target_w, target_h)
    step4_pad = pad_to_size(step4, target_w, target_h)
    step5_pad = pad_to_size(step5, target_w, target_h)
    step6_pad = pad_to_size(step6, target_w, target_h)
    
    # Create 2x3 grid
    row1 = np.hstack([step1_pad, step2_pad, step3_pad])
    row2 = np.hstack([step4_pad, step5_pad, step6_pad])
    debug_img = np.vstack([row1, row2])
    
    # Add title at top
    title_height = 50
    debug_img = cv2.copyMakeBorder(debug_img, title_height, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.putText(debug_img, f"Debug Visualization - {image_path.name}", 
                (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)  # Yellow text
    
    return debug_img


def create_partial_debug_image(debug_info: dict, error_msg: str) -> np.ndarray:
    """
    Create a partial debug image when processing fails.
    
    Args:
        debug_info: Dictionary containing available debug information (must have 'gray' and 'binary')
        error_msg: Error message to display
        
    Returns:
        Partial debug visualization image
    """
    gray = debug_info.get("gray")
    binary = debug_info.get("binary")
    image_path = debug_info.get("image_path", Path("unknown"))
    
    if gray is None:
        return np.zeros((100, 100, 3), dtype=np.uint8)
    
    h, w = gray.shape
    grid_h, grid_w = h // 2, w // 2
    scale = min(grid_w / w, grid_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    
    def resize_img(img, target_w, target_h):
        return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
    
    text_color = (0, 255, 255)  # Yellow
    
    orig_colored = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    step1 = resize_img(orig_colored, new_w, new_h)
    cv2.putText(step1, "1. Original", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    if binary is not None:
        binary_colored = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        step2 = resize_img(binary_colored, new_w, new_h)
        cv2.putText(step2, "2. Binary (Otsu)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
        
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        step3 = resize_img(orig_colored.copy(), new_w, new_h)
        if contours:
            for i, c in enumerate(contours[:10]):
                color = ((i * 50) % 255, (i * 100) % 255, (i * 150) % 255)
                contour_scaled = (c * scale).astype(np.int32)
                cv2.drawContours(step3, [contour_scaled], -1, color, 2)
            cv2.putText(step3, f"3. All Contours ({len(contours)})", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
        else:
            cv2.putText(step3, "3. No Contours", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    else:
        step2 = np.zeros((new_h, new_w, 3), dtype=np.uint8)
        cv2.putText(step2, "2. Binary (N/A)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
        step3 = np.zeros((new_h, new_w, 3), dtype=np.uint8)
        cv2.putText(step3, "3. Contours (N/A)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    step4 = np.zeros((new_h, new_w, 3), dtype=np.uint8)
    error_lines = error_msg.split('\n')[:4]
    y_pos = 30
    for line in error_lines:
        if len(line) > 40:
            line = line[:37] + "..."
        cv2.putText(step4, line, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        y_pos += 25
    
    def pad_to_size(img, target_w, target_h):
        h_img, w_img = img.shape[:2]
        pad_h = target_h - h_img
        pad_w = target_w - w_img
        return cv2.copyMakeBorder(img, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    
    target_w, target_h = new_w, new_h
    step1_pad = pad_to_size(step1, target_w, target_h)
    step2_pad = pad_to_size(step2, target_w, target_h)
    step3_pad = pad_to_size(step3, target_w, target_h)
    step4_pad = pad_to_size(step4, target_w, target_h)
    
    row1 = np.hstack([step1_pad, step2_pad])
    row2 = np.hstack([step3_pad, step4_pad])
    debug_img = np.vstack([row1, row2])
    
    title_height = 50
    debug_img = cv2.copyMakeBorder(debug_img, title_height, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    title_text = f"Partial Debug - {Path(image_path).name if isinstance(image_path, (Path, str)) else 'unknown'}"
    cv2.putText(debug_img, title_text, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
    
    return debug_img


def _find_local_image(base_dir: Path, base_name: str = "Cone_Trial_Image") -> Path:
    """Find image file in directory with various extensions."""
    exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
    for ext in exts:
        candidate = base_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No image named {base_name} with extensions {exts} found in {base_dir}")


def main():
    """Main entry point."""
    # Try to find a default image, but don't fail if none exists
    try:
        default_input_path = _find_local_image(CURRENT_DIR)
    except FileNotFoundError:
        default_input_path = None
    
    parser = argparse.ArgumentParser(description="Contour-based cone angle detection with PCA")
    parser.add_argument("--input", type=Path, default=default_input_path, help="Path to input TIFF image (default: searches for Cone_Trial_Image.* in script directory)")
    parser.add_argument("--output", type=Path, default=None, help="Path to output annotated image (default: input_name_cone3.tiff)")
    parser.add_argument("--nozzle-x", type=float, default=None, help="X-coordinate of nozzle (optional)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open annotated image")
    args = parser.parse_args()
    
    # Single image processing
    input_path = args.input
    
    # If no input specified and no default found, try to find Spray_1
    if input_path is None or (input_path == default_input_path and default_input_path is None):
        # Try to find Spray_1 as fallback
        exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
        for ext in exts:
            candidate = CURRENT_DIR / f"Spray_1{ext}"
            if candidate.exists():
                input_path = candidate
                break
        
        if input_path is None or not input_path.exists():
            raise FileNotFoundError("No input image specified. Use --input or place Cone_Trial_Image.* or Spray_1.* in script directory")
    
    if not input_path.exists():
        raise FileNotFoundError(f"Input image not found: {input_path}")
    
    process_single_image(input_path, args.nozzle_x, args.no_open)


def process_single_image(input_path: Path, nozzle_x: float | None, no_open: bool):
    """Process a single image and save outputs."""
    
    # Auto-generate output name based on input name
    output_path = input_path.parent / f"{input_path.stem}_cone3{input_path.suffix}"
    
    print(f"[Cone_3] Loading image: {input_path}")
    print(f"[Cone_3] Debug mode: {DEBUG_MODE}")
    
    try:
        angle_deg, annotated, debug_info = detect_cone_angle(input_path, nozzle_x)
        
        # Check if detection failed (angle_deg is None)
        if angle_deg is None:
            raise RuntimeError(debug_info.get("error", "Contour detection failed"))
        
        # Add angle to debug_info for debug image
        debug_info["angle_deg"] = angle_deg
        
        print(f"[Cone_3] Detected cone angle: {angle_deg:.2f} degrees")
        print(f"[Cone_3] Contour area: {debug_info['contour_area']:.0f} pixels")
        print(f"[Cone_3] Left points: {debug_info['left_points_count']}, Right points: {debug_info['right_points_count']}")
        print(f"[Cone_3] Left variance explained: {debug_info['left_variance_explained']:.3f}")
        print(f"[Cone_3] Right variance explained: {debug_info['right_variance_explained']:.3f}")
        
        # Save annotated image
        cv2.imwrite(str(output_path), annotated)
        print(f"[Cone_3] Saved annotated image to: {output_path}")
        
        # Create and save debug image if debug mode is enabled
        if DEBUG_MODE:
            debug_dir = CURRENT_DIR / "cone_3_debug"
            debug_dir.mkdir(exist_ok=True)
            debug_img = create_debug_image(debug_info, input_path)
            debug_output_path = debug_dir / f"{input_path.stem}_debug.png"
            cv2.imwrite(str(debug_output_path), debug_img)
            print(f"[Cone_3] Saved debug visualization to: {debug_output_path}")
        
        # Auto-open on macOS (only for single image, not batch)
        if not no_open and not DEBUG_MODE:
            try:
                if sys.platform == "darwin":
                    import subprocess
                    subprocess.run(["open", str(output_path)], check=False)
                else:
                    cv2.imshow("Annotated Cone", annotated)
                    cv2.waitKey(0)
                    cv2.destroyAllWindows()
            except Exception as e:
                print(f"[Cone_3] Warning: could not open image automatically: {e}")
                
    except Exception as e:
        print(f"[Cone_3] Error: {e}")
        
        # Try to get partial debug info from the error
        partial_debug_info = {"error": str(e), "image_path": input_path}
        try:
            # Try to load image to get at least gray/binary for debug
            gray = load_image(input_path)
            binary = preprocess_image(gray)
            partial_debug_info["gray"] = gray
            partial_debug_info["binary"] = binary
        except Exception as load_err:
            print(f"[Cone_3] Could not load image for partial debug: {load_err}")
        
        # Save partial debug output if we have at least gray and binary
        if DEBUG_MODE and "gray" in partial_debug_info:
            try:
                debug_dir = CURRENT_DIR / "cone_3_debug"
                debug_dir.mkdir(exist_ok=True)
                debug_img = create_partial_debug_image(partial_debug_info, str(e))
                debug_output_path = debug_dir / f"{input_path.stem}_debug_partial.png"
                cv2.imwrite(str(debug_output_path), debug_img)
                print(f"[Cone_3] Saved partial debug visualization to: {debug_output_path}")
            except Exception as debug_err:
                print(f"[Cone_3] Could not save partial debug: {debug_err}")
        
        raise


if __name__ == "__main__":
    main()

