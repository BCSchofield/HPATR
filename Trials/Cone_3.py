"""
Cone angle detection using contour-based method with PCA (directional statistics)

This module computes the spray cone angle from a single image by:
1. Finding the largest contour representing the spray
2. Splitting the contour into left and right edges
3. Using PCA to find the dominant direction of each edge
4. Computing the angle between the two PCA directions
"""

# Library Imports
import argparse  # For parsing command-line arguments
from pathlib import Path  # For cross-platform file path handling
import sys  # For system-specific operations and path manipulation
import cv2  # OpenCV for image processing (loading, thresholding, contour detection, drawing)
import numpy as np  # NumPy for numerical array operations and linear algebra

# Debug mode: True for output of overlay contour and PCA vectors, false for just the annotated image
DEBUG_MODE = True

# Setup path to allow importing from src directory
# Get the directory where this script is located
CURRENT_DIR = Path(__file__).resolve().parent
# Get the project root
PROJECT_ROOT = CURRENT_DIR.parent
# Add src directory to Python path if not already there (allows importing config_loader)
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config_loader import get_imaging_config  # noqa: E402

# Processing Parameters
GAUSSIAN_BLUR_KSIZE = 5  # Kernel size for Gaussian blur (must be odd: 3, 5, 7, etc.)
                          # Larger values = more smoothing, removes noise but softens edges

GAUSSIAN_BLUR_SIGMA = 0  # Standard deviation for Gaussian blur (0 = auto-calculate from kernel size)
                          # Higher values = more blur in all directions

MORPH_CLOSE_KSIZE = 7  # Kernel size for morphological closing operation (must be odd)
                        # Closing fills small gaps and holes in the binary image
                        # Larger values = fill larger gaps but may merge separate objects

MIN_CONTOUR_AREA_RATIO = 0.01  # Minimum contour area as fraction of total image area
                                # Contours smaller than this are rejected as noise
                                # 0.01 = 1% of image area


def load_image(image_path: Path) -> np.ndarray:
    """
    Function handles various image formats and bit depths, ensuring we always
    get a standard 8-bit grayscale image for processing.
    
    Args:
        image_path: Path to the TIFF image file
    Returns:
        Grayscale image as numpy array (uint8) with values 0-255
    Raises:
        FileNotFoundError: If image file doesn't exist
        ValueError: If image cannot be loaded or has unexpected format
    """
    # Check if file exists before attempting to load
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    # Load image with cv2.imread
    # IMREAD_UNCHANGED preserves original bit depth and color channels
    img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Cannot load image: {image_path}")
    
    # Convert to grayscale based on image dimensions
    # shape[2] exists for color images (BGR), shape is (height, width) for grayscale
    if len(img.shape) == 3:
        # Color image (BGR format) - convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    elif len(img.shape) == 2:
        # Already grayscale - just copy it
        gray = img.copy()
    else:
        # Unexpected format (shouldn't happen with standard images)
        raise ValueError(f"Unexpected image shape: {img.shape}")
    
    # Normalize to 8-bit (0-255) if image is in different bit depth
    # Some TIFF images are 16-bit or float - we need uint8 for thresholding
    if gray.dtype != np.uint8:
        # Normalize: scale min->0, max->255, convert to uint8
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    
    return gray


def preprocess_image(gray: np.ndarray) -> np.ndarray:
    """
    Preprocess the grayscale image: blur, threshold, and clean up.
    
    This function converts the grayscale image into a clean binary mask where:
    - Foreground (spray) = 0 (black)
    - Background = 255 (white)
    
    Steps:
    1. Apply Gaussian blur to reduce noise
    2. Use Otsu's automatic thresholding to separate spray from background
    3. Invert if needed (spray should be darker than background)
    4. Apply morphological closing to fill small gaps
    5. Clear borders to avoid detecting image frame as part of spray
    
    Args:
        gray: Input grayscale image (uint8, 0-255)
        
    Returns:
        Binary mask (foreground = 0, background = 255)
    """
    # Step 1: Apply Gaussian blur to reduce noise
    # Ensure kernel size is odd (required by OpenCV)
    ksize = GAUSSIAN_BLUR_KSIZE if GAUSSIAN_BLUR_KSIZE % 2 == 1 else GAUSSIAN_BLUR_KSIZE + 1
    # Blur with specified kernel size and sigma (0 = auto-calculate)
    blurred = cv2.GaussianBlur(gray, (ksize, ksize), GAUSSIAN_BLUR_SIGMA)
    
    # Step 2: Otsu's automatic thresholding
    # Otsu's method automatically finds the optimal threshold value
    # by maximizing the variance between foreground and background classes
    # Returns: (threshold_value, binary_image)
    # THRESH_BINARY: values > threshold become 255, values <= threshold become 0
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Step 3: Check if we need to invert the binary image
    # In shadowgraph images, spray might be darker (foreground) or lighter than background
    # If most pixels are foreground (< 128), the image is likely inverted
    fg_ratio = (binary < 128).sum() / binary.size  # Count pixels < 128 (foreground)
    if fg_ratio > 0.5:  # If more than 50% are foreground
        binary = cv2.bitwise_not(binary)  # Invert: 0<->255
    
    # Step 4: Apply morphological closing to clean noise and fill gaps
    # Closing = dilation followed by erosion: fills small holes and gaps
    # Ensure kernel size is odd
    close_k = MORPH_CLOSE_KSIZE if MORPH_CLOSE_KSIZE % 2 == 1 else MORPH_CLOSE_KSIZE + 1
    # Create square kernel of ones
    kernel = np.ones((close_k, close_k), np.uint8)
    # Apply closing operation
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    
    # Step 5: Clear image borders to prevent detecting frame as contour
    # Set border pixels to background (255 = white background)
    # Note: Don't clear top border - cone should start at the top of image
    h, w = closed.shape
    # Calculate border width: at least 5 pixels, or 1% of smaller dimension
    border_px = max(5, min(w, h) // 100)
    # Top border - DISABLED to allow cone to start at top
    # closed[:border_px, :] = 255
    closed[-border_px:, :] = 255  # Bottom border: set last border_px rows to white
    closed[:, :border_px] = 255  # Left border: set first border_px columns to white
    closed[:, -border_px:] = 255  # Right border: set last border_px columns to white
    
    return closed


def find_spray_contour(binary: np.ndarray, border_px: int = 5) -> np.ndarray:
    """
    Find the largest external contour representing the spray.
    
    This function uses a multi-stage filtering approach:
    1. Strict filtering: area, border touching, aspect ratio
    2. Relaxed filtering: if strict fails, use looser criteria
    3. Final fallback: accept any reasonable contour
    4. Handle multiple contours: combine vertically-aligned ones
    
    Args:
        binary: Binary mask image (foreground=0, background=255)
        border_px: Number of pixels cleared from borders in preprocessing
        
    Returns:
        Contour points as numpy array (N, 1, 2) where N is number of points
        
    Raises:
        RuntimeError: If no suitable contour is found after all filtering attempts
    """
    # cv2.findContours requires foreground to be white (255) and background black (0)
    # The binary image from preprocessing has background=255 (white), foreground=0 (black)
    # So we need to invert it for findContours to work correctly
    binary_for_contours = cv2.bitwise_not(binary)
    
    # Find external contours (outermost boundaries only, not nested contours)
    # RETR_EXTERNAL: only retrieves external contours (ignores holes)
    # CHAIN_APPROX_NONE: stores all contour points (no approximation)
    contours, _ = cv2.findContours(binary_for_contours, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    
    if not contours:
        raise RuntimeError("No contours found in image")
    
    print(f"[Cone_3] Found {len(contours)} contours")
    
    # Calculate area thresholds for filtering
    h, w = binary.shape
    min_area = MIN_CONTOUR_AREA_RATIO * h * w  # Minimum: 1% of image area
    max_area = 0.8 * h * w  # Maximum: 80% of image area (reject if too large, likely frame)
    
    # STAGE 1: Strict filtering - apply all criteria
    filtered_contours = []
    for c in contours:
        # Calculate contour area
        area = cv2.contourArea(c)
        
        # Filter by area: reject too small (noise) or too large (frame)
        if area < min_area or area > max_area:
            continue
        
        # Get bounding box (x, y, width, height) to check border proximity
        x, y, cw, ch = cv2.boundingRect(c)
        
        # Reject contours that touch image borders (likely frame artifacts)
        # Use margin based on border_px used in preprocessing
        # Note: Allow touching top border - cone should start at top
        margin = max(5, border_px + 2)  # Small margin around borders
        touches_border = (x <= margin or  # Left border: too close to left edge
                         x + cw >= w - margin or  # Right border: too close to right edge
                         y + ch >= h - margin)  # Bottom border: too close to bottom edge
        # Don't check top border (y <= margin) - cone can start at top
        
        if touches_border:
            continue
        
        # Filter by aspect ratio - spray should be taller than wide (relaxed)
        # Aspect ratio = height / width
        aspect_ratio = ch / max(cw, 1)
        if aspect_ratio < 0.15:  # Relaxed threshold - allow wider sprays
            continue
        
        # Contour passed all strict filters
        filtered_contours.append(c)
    
    # STAGE 2: If no contours pass strict filtering, try relaxed filtering
    if not filtered_contours:
        print(f"[Cone_3] Warning: No contours passed strict filtering, trying relaxed criteria...")
        # Relaxed filtering: use looser criteria to catch edge cases
        for c in contours:
            area = cv2.contourArea(c)
            # Lower minimum area threshold (30% of original) - accept smaller contours
            if area < min_area * 0.3 or area > max_area:
                continue
            
            x, y, cw, ch = cv2.boundingRect(c)
            
            # More relaxed border check - only reject if clearly on border (margin=2)
            # Note: Allow touching top border - cone should start at top
            margin = 2  # Very small margin
            touches_border = (x <= margin or  # Left border
                             x + cw >= w - margin or  # Right border
                             y + ch >= h - margin)  # Bottom border
            # Don't check top border (y <= margin) - cone can start at top
            
            if touches_border:
                continue
            
            # Very relaxed aspect ratio - accept almost any shape
            aspect_ratio = ch / max(cw, 1)
            if aspect_ratio < 0.05:  # Very relaxed - almost any shape
                continue
            
            filtered_contours.append(c)
    
    # STAGE 3: Final fallback - accept any contour that's not obviously wrong
    if not filtered_contours:
        print(f"[Cone_3] Warning: No contours passed relaxed filtering, using final fallback...")
        print(f"[Cone_3] Total contours available: {len(contours)}")
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            x, y, cw, ch = cv2.boundingRect(c)
            aspect = ch / max(cw, 1)
            
            # Only reject if it's clearly the full frame (very large)
            # This catches cases where the entire image is detected as one contour
            if area > max_area * 0.98:  # Reject if >98% of max area (almost entire frame)
                print(f"[Cone_3]   Contour {i}: REJECTED - too large (area={area:.0f} > {max_area*0.98:.0f})")
                continue
            
            # Accept any contour that's not tiny (absolute minimum: 100 pixels)
            if area < 100:
                print(f"[Cone_3]   Contour {i}: REJECTED - too small (area={area:.0f} < 100)")
                continue
            
            # Don't check borders or aspect ratio in final fallback - accept it
            print(f"[Cone_3]   Contour {i}: ACCEPTED in fallback (area={area:.0f}, bbox=({x},{y},{cw},{ch}), aspect={aspect:.2f})")
            filtered_contours.append(c)
    
    if not filtered_contours:
        # Print diagnostic info
        print(f"[Cone_3] Diagnostic: Image size {w}x{h}, min_area={min_area:.0f}, max_area={max_area:.0f}")
        print(f"[Cone_3] All {len(contours)} contours were rejected")
        raise RuntimeError(f"No suitable contours found after all filtering attempts (area: {min_area:.0f}-{max_area:.0f}, not touching borders)")
    
    # Handle disconnected contours (e.g., void in middle of cone)
    # If multiple contours, try to combine vertically-aligned ones or select topmost
    if len(filtered_contours) > 1:
        print(f"[Cone_3] Found {len(filtered_contours)} filtered contours - checking for vertical alignment...")
        
        # Sort contours by topmost Y coordinate (top of bounding box)
        contours_with_tops = []
        for c in filtered_contours:
            x, y, cw, ch = cv2.boundingRect(c)
            top_y = y
            contours_with_tops.append((top_y, c))
        
        # Sort by top Y (ascending - topmost first)
        contours_with_tops.sort(key=lambda x: x[0])
        
        # Check if contours are vertically aligned (likely top and bottom parts of same cone)
        # Two contours are aligned if their X ranges overlap significantly
        def x_overlap(rect1, rect2):
            x1, y1, w1, h1 = rect1
            x2, y2, w2, h2 = rect2
            x1_end = x1 + w1
            x2_end = x2 + w2
            overlap_start = max(x1, x2)
            overlap_end = min(x1_end, x2_end)
            if overlap_end <= overlap_start:
                return 0
            overlap_width = overlap_end - overlap_start
            min_width = min(w1, w2)
            return overlap_width / min_width if min_width > 0 else 0
        
        # Try to combine vertically-aligned contours
        combined_contours = []
        used = set()
        
        for i, (top_y1, c1) in enumerate(contours_with_tops):
            if i in used:
                continue
            
            rect1 = cv2.boundingRect(c1)
            combined = [c1]
            used.add(i)
            
            # Look for other contours that are vertically aligned
            for j, (top_y2, c2) in enumerate(contours_with_tops[i+1:], start=i+1):
                if j in used:
                    continue
                
                rect2 = cv2.boundingRect(c2)
                overlap_ratio = x_overlap(rect1, rect2)
                
                # If X ranges overlap significantly (>50%) and vertically separated, combine
                if overlap_ratio > 0.5:
                    # Check vertical separation - should have gap but not too far
                    y1_bottom = rect1[1] + rect1[3]
                    y2_top = rect2[1]
                    gap = y2_top - y1_bottom
                    max_gap = h * 0.3  # Allow gap up to 30% of image height
                    
                    if 0 <= gap <= max_gap:
                        print(f"[Cone_3]   Combining contours {i} and {j} (X overlap: {overlap_ratio:.2f}, gap: {gap:.0f}px)")
                        combined.append(c2)
                        used.add(j)
                        # Update rect1 to include both
                        x1, y1, w1, h1 = rect1
                        x2, y2, w2, h2 = rect2
                        x_min = min(x1, x2)
                        y_min = min(y1, y2)
                        x_max = max(x1 + w1, x2 + w2)
                        y_max = max(y1 + h1, y2 + h2)
                        rect1 = (x_min, y_min, x_max - x_min, y_max - y_min)
            
            # Combine all contours in this group
            if len(combined) > 1:
                # Concatenate all points
                all_points = np.vstack([c.reshape(-1, 2) for c in combined])
                # Create new contour from combined points
                combined_contour = all_points.reshape(-1, 1, 2).astype(np.int32)
                combined_contours.append(combined_contour)
            else:
                combined_contours.append(combined[0])
        
        if combined_contours:
            print(f"[Cone_3] Combined into {len(combined_contours)} contour(s)")
            # Select the topmost combined contour (should include the top part)
            topmost_combined = min(combined_contours, key=lambda c: cv2.boundingRect(c)[1])
            return topmost_combined
        else:
            # Fallback: select topmost contour
            print(f"[Cone_3]   No vertical alignment found, selecting topmost contour")
            topmost_contour = contours_with_tops[0][1]
            return topmost_contour
    
    # Single contour - return it
    return filtered_contours[0]


def split_contour_edges(contour: np.ndarray, nozzle_x: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """
    Split contour points into left and right edges.
    
    The spray cone contour is split at the nozzle x-coordinate (or center if not provided).
    Points to the left of the split become the left edge, points to the right become the right edge.
    
    Args:
        contour: Contour points as (N, 1, 2) or (N, 2) array
        nozzle_x: X-coordinate of nozzle. If None, uses mean x of all points (center of contour).
        
    Returns:
        Tuple of (left_edge_points, right_edge_points), each as (M, 2) array
        where M is the number of points on each edge
    """
    # Reshape contour to (N, 2) format if needed
    # OpenCV contours are typically (N, 1, 2) - reshape to (N, 2) for easier indexing
    if contour.ndim == 3:
        points = contour.reshape(-1, 2)  # Flatten: (N, 1, 2) -> (N, 2)
    else:
        points = contour  # Already (N, 2)
    
    if len(points) == 0:
        raise ValueError("Contour has no points")
    
    # Determine split x-coordinate (vertical line that divides left and right)
    if nozzle_x is None:
        # Use mean x-coordinate of all points (center of contour)
        split_x = np.mean(points[:, 0])
    else:
        # Use provided nozzle x-coordinate
        split_x = float(nozzle_x)
    
    # Split into left and right edges using boolean masks
    left_mask = points[:, 0] < split_x   # Points with x < split_x (left side)
    right_mask = points[:, 0] >= split_x  # Points with x >= split_x (right side)
    
    # Extract points for each edge
    left_points = points[left_mask]
    right_points = points[right_mask]
    
    # Validate that we have enough points for each edge (need at least 3 for PCA)
    if len(left_points) < 3:
        raise ValueError(f"Left edge has too few points: {len(left_points)}")
    if len(right_points) < 3:
        raise ValueError(f"Right edge has too few points: {len(right_points)}")
    
    return left_points, right_points


def extract_outermost_points(points: np.ndarray, is_left_edge: bool) -> np.ndarray:
    """
    Extract the outermost points from an edge (leftmost for left edge, rightmost for right edge).
    
    This function bins points by y-coordinate and selects the outermost point (leftmost or rightmost)
    in each bin. This helps fit lines to the actual outer boundary of the spray rather than using
    all points (which might include inner points if the contour has thickness).
    
    Args:
        points: Array of edge points (N, 2) where columns are [x, y]
        is_left_edge: True for left edge (extract leftmost x), False for right edge (extract rightmost x)
        
    Returns:
        Array of outermost points (M, 2) where M <= N
    """
    if len(points) == 0:
        return points
    
    # Bin points by y-coordinate to find outermost at each y-level
    # This handles cases where multiple points exist at similar y-coordinates
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    # Calculate number of bins: at least 20 bins, or 1 bin per 10 pixels of height
    num_bins = max(20, int((y_max - y_min) / 10))
    # Don't over-bin: limit to half the number of points (avoid empty bins)
    num_bins = min(num_bins, len(points) // 2)
    
    if num_bins < 2:
        # Too few points or too small range - just return outermost overall
        if is_left_edge:
            return points[np.argmin(points[:, 0])].reshape(1, -1)
        else:
            return points[np.argmax(points[:, 0])].reshape(1, -1)
    
    bin_edges = np.linspace(y_min, y_max, num_bins + 1)
    outermost_points = []
    
    for i in range(num_bins):
        # Find points in this y-bin
        y_low = bin_edges[i]
        y_high = bin_edges[i + 1]
        mask = (points[:, 1] >= y_low) & (points[:, 1] < y_high)
        bin_points = points[mask]
        
        if len(bin_points) == 0:
            continue
        
        # For left edge: find leftmost (minimum x)
        # For right edge: find rightmost (maximum x)
        if is_left_edge:
            outer_idx = np.argmin(bin_points[:, 0])
        else:
            outer_idx = np.argmax(bin_points[:, 0])
        
        outermost_points.append(bin_points[outer_idx])
    
    # Handle last bin (include upper edge)
    mask = points[:, 1] >= bin_edges[-2]
    bin_points = points[mask]
    if len(bin_points) > 0:
        if is_left_edge:
            outer_idx = np.argmin(bin_points[:, 0])
        else:
            outer_idx = np.argmax(bin_points[:, 0])
        outermost_points.append(bin_points[outer_idx])
    
    if len(outermost_points) == 0:
        return points
    
    return np.array(outermost_points)


def compute_pca_direction(points: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Compute the dominant direction of a set of points using PCA (Principal Component Analysis).
    
    PCA finds the direction along which the points have the most variance (spread).
    For a spray edge, this gives us the overall direction the edge is pointing.
    We use eigenvalue decomposition of the covariance matrix to find the principal components.
    
    Args:
        points: Array of points (N, 2) where columns are [x, y]
        
    Returns:
        Tuple of (direction_vector, variance_explained)
        direction_vector: Unit vector (2,) pointing in dominant direction (normalized)
        variance_explained: Fraction (0-1) of variance explained by first principal component
                           (higher = points are more aligned along this direction)
    """
    if len(points) < 2:
        raise ValueError("Need at least 2 points for PCA")
    
    # Step 1: Center the points (subtract mean) - required for PCA
    mean = np.mean(points, axis=0)  # Mean x and y coordinates
    centered = points - mean  # Shift points so mean is at origin
    
    # Step 2: Compute covariance matrix
    # Covariance matrix describes how x and y vary together
    # For 2D points, this is a 2x2 matrix
    cov = np.cov(centered.T)  # Transpose to get (2, N) then compute covariance
    
    # Step 3: Eigenvalue decomposition (more numerically stable for 2x2 than SVD)
    # Eigenvalues = variance along each principal direction
    # Eigenvectors = directions of principal components
    eigenvals, eigenvecs = np.linalg.eigh(cov)  # eigh for symmetric matrices
    
    # Step 4: Sort by eigenvalue (largest first) - largest = most variance = dominant direction
    idx = np.argsort(eigenvals)[::-1]  # Indices sorted descending
    eigenvals = eigenvals[idx]
    eigenvecs = eigenvecs[:, idx]
    
    # Step 5: First principal component (dominant direction)
    direction = eigenvecs[:, 0]  # First column = direction of most variance
    
    # Step 6: Ensure direction points downward (positive y in image coordinates)
    # In images, y increases downward, so spray should point down
    if direction[1] < 0:
        direction = -direction  # Flip if pointing upward
    
    # Step 7: Normalize to unit vector (length = 1)
    norm = np.linalg.norm(direction)
    if norm > 1e-10:  # Avoid division by zero
        direction = direction / norm
    else:
        # Fallback: if direction is degenerate, use vertical direction
        direction = np.array([0.0, 1.0])
    
    # Step 8: Calculate variance explained by first component
    # This tells us how well the points align along this direction
    # 1.0 = perfectly aligned, < 1.0 = some spread perpendicular to direction
    total_var = np.sum(eigenvals)
    if total_var > 1e-10:
        variance_explained = eigenvals[0] / total_var
    else:
        variance_explained = 1.0  # All variance in first component (degenerate case)
    
    return direction, variance_explained


def compute_cone_angle(left_dir: np.ndarray, right_dir: np.ndarray) -> float:
    """
    Compute the cone angle between two direction vectors.
    
    The cone angle is the angle between the left and right edge directions.
    We use the dot product formula: cos(θ) = (a·b) / (|a||b|)
    Since both vectors are unit vectors (length=1), this simplifies to: cos(θ) = a·b
    
    Args:
        left_dir: Unit direction vector for left edge (2,) - normalized, points downward
        right_dir: Unit direction vector for right edge (2,) - normalized, points downward
        
    Returns:
        Cone angle in degrees (acute angle between the two directions)
        Example: 30° means the edges diverge by 30 degrees
    """
    # Compute angle between vectors using dot product
    # Dot product of unit vectors = cosine of angle between them
    dot_product = np.dot(left_dir, right_dir)
    # Clip to [-1, 1] to avoid numerical errors in arccos
    dot_product = np.clip(dot_product, -1.0, 1.0)
    # Convert to angle in radians
    angle_rad = np.arccos(dot_product)
    # Convert to degrees
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
    # ============================================================================
    # STEP 1: Load and preprocess image
    # ============================================================================
    gray = load_image(image_path)
    
    # Crop top 5% of image to remove artifacts (nozzle, mounting hardware, etc.)
    # This prevents these artifacts from being detected as part of the spray
    h_original, w_original = gray.shape
    top_crop_px = int(h_original * 0.05)
    gray = gray[top_crop_px:, :]  # Remove top 5%, keep rest
    print(f"[Cone_3] Cropped top {top_crop_px} pixels ({100*top_crop_px/h_original:.1f}%) from image")
    
    # Convert grayscale to binary mask (spray = black, background = white)
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
    
    # ============================================================================
    # STEP 4: Split contour into left and right edges
    # ============================================================================
    left_points, right_points = split_contour_edges(contour, nozzle_x)
    
    # ============================================================================
    # STEP 5: Extract outermost points from each edge
    # ============================================================================
    # Extract outermost points to fit to the actual outer boundary of the spray
    # This gives a better fit than using all points (which may include inner points
    # if the contour has thickness or includes internal features)
    left_outer = extract_outermost_points(left_points, is_left_edge=True)
    right_outer = extract_outermost_points(right_points, is_left_edge=False)
    
    print(f"[Cone_3] Using {len(left_outer)}/{len(left_points)} left outermost points, {len(right_outer)}/{len(right_points)} right outermost points")
    
    # ============================================================================
    # STEP 6: Compute PCA directions for each edge
    # ============================================================================
    # PCA finds the dominant direction (trend) of each edge
    # Returns: (direction_vector, variance_explained)
    # Note: top 5% already cropped from image, so all points are valid
    left_dir, left_var = compute_pca_direction(left_outer)
    right_dir, right_var = compute_pca_direction(right_outer)
    
    # ============================================================================
    # STEP 7: Compute cone angle from the two direction vectors
    # ============================================================================
    angle_deg = compute_cone_angle(left_dir, right_dir)
    
    # ============================================================================
    # STEP 8: Create annotated visualization image
    # ============================================================================
    # Convert grayscale to BGR (3-channel) for color annotations
    annotated = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    
    h, w = gray.shape
    
    # Draw lines along the actual contour edges to visualize the detected angle
    # Find the topmost point (apex) for each edge using outermost points
    # (consistent with PCA which uses outermost points)
    left_top_idx = np.argmin(left_outer[:, 1])  # Minimum y = top of image
    right_top_idx = np.argmin(right_outer[:, 1])
    
    # Get topmost points (apex) from outermost points
    left_top = left_outer[left_top_idx]
    right_top = right_outer[right_top_idx]
    
    # Calculate line positions - span from top to bottom of image
    top_y = 0  # Start at top of image (y=0)
    bottom_y = h  # End at bottom of image (y=h)
    
    # Project lines from apex along PCA direction to the desired y positions
    # left_dir and right_dir are normalized direction vectors pointing downward
    # We need to find x positions at top_y and bottom_y along each direction
    # Using parametric line equation: point = apex + direction * t
    # Solving for t: t = (target_y - apex_y) / direction_y
    
    # For left edge: find x at top_y and bottom_y
    # Line equation: x = left_top[0] + left_dir[0] * t, y = left_top[1] + left_dir[1] * t
    # Solve for t when y = top_y: t = (top_y - left_top[1]) / left_dir[1]
    left_t_top = (top_y - left_top[1]) / left_dir[1] if left_dir[1] != 0 else 0
    left_t_bottom = (bottom_y - left_top[1]) / left_dir[1] if left_dir[1] != 0 else 0
    left_start = left_top + left_dir * left_t_top  # Point at top of image
    left_end = left_top + left_dir * left_t_bottom  # Point at bottom of image
    
    # For right edge: find x at top_y and bottom_y
    right_t_top = (top_y - right_top[1]) / right_dir[1] if right_dir[1] != 0 else 0
    right_t_bottom = (bottom_y - right_top[1]) / right_dir[1] if right_dir[1] != 0 else 0
    right_start = right_top + right_dir * right_t_top
    right_end = right_top + right_dir * right_t_bottom
    
    # Draw left edge line (red, thickness=3)
    cv2.line(annotated,
              (int(left_start[0]), int(left_start[1])),
              (int(left_end[0]), int(left_end[1])),
              (0, 0, 255), 3)  # BGR: (0, 0, 255) = red
    
    # Draw right edge line (red, thickness=3)
    cv2.line(annotated,
              (int(right_start[0]), int(right_start[1])),
              (int(right_end[0]), int(right_end[1])),
              (0, 0, 255), 3)  # BGR: (0, 0, 255) = red
    
    # ============================================================================
    # STEP 9: Add debug overlays and annotations
    # ============================================================================
    # Store centers for debug overlays (using mean of edge points)
    # These are used as starting points for drawing PCA vectors
    left_center = np.array([np.mean(left_points[:, 0]), np.mean(left_points[:, 1])])
    right_center = np.array([np.mean(right_points[:, 0]), np.mean(right_points[:, 1])])
    
    # Draw debug overlays if debug mode is enabled
    # These visualizations help understand what the algorithm is detecting
    if DEBUG_MODE:
        # Draw full contour outline (green) - shows the detected spray boundary
        cv2.drawContours(annotated, [contour], -1, (0, 255, 0), 2)
        
        # Draw left edge points (cyan dots) - sample every 100th point for visibility
        # Shows all points that were assigned to the left edge
        for pt in left_points[::max(1, len(left_points)//100)]:  # Sample points for visibility
            cv2.circle(annotated, (int(pt[0]), int(pt[1])), 2, (255, 255, 0), -1)  # Cyan in BGR
        
        # Draw right edge points (magenta dots) - sample every 100th point
        # Shows all points that were assigned to the right edge
        for pt in right_points[::max(1, len(right_points)//100)]:  # Sample points for visibility
            cv2.circle(annotated, (int(pt[0]), int(pt[1])), 2, (255, 0, 255), -1)  # Magenta in BGR
        
        # Draw outermost points used for PCA (larger, brighter circles)
        # These are the points actually used to compute the PCA direction
        for pt in left_outer:
            cv2.circle(annotated, (int(pt[0]), int(pt[1])), 3, (0, 255, 255), -1)  # Bright cyan
        for pt in right_outer:
            cv2.circle(annotated, (int(pt[0]), int(pt[1])), 3, (255, 255, 0), -1)  # Bright yellow
        
        # Draw PCA vectors (arrows showing the computed direction for each edge)
        vec_length = min(w, h) * 0.15  # Vector length = 15% of smaller image dimension
        # Left PCA vector (bright green arrow)
        left_vec_end = left_center + left_dir * vec_length
        cv2.arrowedLine(annotated,
                       (int(left_center[0]), int(left_center[1])),
                       (int(left_vec_end[0]), int(left_vec_end[1])),
                       (0, 255, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)  # Green arrow
        
        # Right PCA vector (bright blue arrow)
        right_vec_end = right_center + right_dir * vec_length
        cv2.arrowedLine(annotated,
                       (int(right_center[0]), int(right_center[1])),
                       (int(right_vec_end[0]), int(right_vec_end[1])),
                       (255, 0, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)  # Blue arrow
        
        # Draw center points (larger circles at mean position of each edge)
        cv2.circle(annotated, (int(left_center[0]), int(left_center[1])), 5, (0, 255, 0), -1)  # Green
        cv2.circle(annotated, (int(right_center[0]), int(right_center[1])), 5, (255, 0, 0), -1)  # Blue
    
    # Add angle text in top right corner of image
    angle_text = f"Angle: {angle_deg:.2f} deg"
    # Calculate text position to right-align in top right corner
    text_size = cv2.getTextSize(angle_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
    text_x = w - text_size[0] - 20  # Right edge minus text width minus margin
    text_y = 40  # Fixed y position near top
    cv2.putText(annotated, angle_text, (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 0), 2, cv2.LINE_AA)  # Yellow text
    
    # ============================================================================
    # STEP 10: Package debug information for return
    # ============================================================================
    # Store all intermediate results in debug_info dictionary
    # This allows creating detailed debug visualizations later
    debug_info = {
        "contour_area": cv2.contourArea(contour),
        "left_points_count": len(left_points),
        "right_points_count": len(right_points),
        "left_outer_count": len(left_outer),
        "right_outer_count": len(right_outer),
        "left_variance_explained": left_var,
        "right_variance_explained": right_var,
        "left_direction": left_dir.tolist(),
        "right_direction": right_dir.tolist(),
        "gray": gray,
        "binary": binary,
        "contour": contour,
        "left_points": left_points,
        "right_points": right_points,
        "left_outer": left_outer,
        "right_outer": right_outer,
        "left_center": left_center,
        "right_center": right_center,
        "left_dir": left_dir,
        "right_dir": right_dir,
    }
    
    return angle_deg, annotated, debug_info


def create_debug_image(debug_info: dict, image_path: Path) -> np.ndarray:
    """
    Create a debug image showing all processing steps with annotations.
    
    This function creates a 2x3 grid visualization showing:
    - Row 1: Original image, Binary threshold, Detected contour
    - Row 2: Left/Right edge points, PCA direction vectors, Final angle result
    
    This helps understand what the algorithm detected at each step.
    
    Args:
        debug_info: Dictionary containing all debug information from detect_cone_angle()
        image_path: Path to original image (used for title)
        
    Returns:
        Debug visualization image as numpy array (BGR format)
    """
    # Extract all debug information from dictionary
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
    
    # Create a 2x3 grid of images (2 rows, 3 columns)
    # Row 1: Original, Binary, Contour
    # Row 2: Left/Right edges, PCA vectors, Final result
    
    # Resize images to fit in grid (make them smaller to fit 6 images)
    # Each image will be 1/3 width and 1/2 height of original
    grid_h, grid_w = h // 2, w // 3
    # Calculate scale factor to fit image in grid cell (maintain aspect ratio)
    scale = min(grid_w / w, grid_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    
    # Helper function to resize images
    def resize_img(img, target_w, target_h):
        return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
    
    # ============================================================================
    # Create each step of the debug visualization
    # ============================================================================
    
    # Step 1: Original grayscale image
    orig_colored = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)  # Convert to BGR for color annotations
    step1 = resize_img(orig_colored, new_w, new_h)
    # Use yellow text (0, 255, 255 in BGR) for better visibility on dark backgrounds
    text_color = (0, 255, 255)  # Yellow in BGR
    cv2.putText(step1, "1. Original", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 2: Binary (thresholded) image
    # Shows the result of Otsu thresholding - spray should be black, background white
    binary_colored = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    step2 = resize_img(binary_colored, new_w, new_h)
    cv2.putText(step2, "2. Binary (Otsu)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 3: Contour overlay on original image
    # Shows the detected spray contour (green outline)
    step3 = resize_img(orig_colored.copy(), new_w, new_h)
    # Scale contour points to match resized image
    contour_scaled = (contour * scale).astype(np.int32)
    cv2.drawContours(step3, [contour_scaled], -1, (0, 255, 0), 2)  # Green contour
    cv2.putText(step3, "3. Detected Contour", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 4: Left/Right edge points
    # Shows how the contour was split into left and right edges
    step4 = resize_img(orig_colored.copy(), new_w, new_h)
    # Draw left edge points (cyan) - sample every 50th point for visibility
    for pt in left_points[::max(1, len(left_points)//50)]:
        pt_scaled = (pt * scale).astype(int)
        # Check bounds to avoid drawing outside image
        if 0 <= pt_scaled[0] < new_w and 0 <= pt_scaled[1] < new_h:
            cv2.circle(step4, tuple(pt_scaled), 2, (255, 255, 0), -1)  # Cyan in BGR
    # Draw right edge points (magenta) - sample every 50th point
    for pt in right_points[::max(1, len(right_points)//50)]:
        pt_scaled = (pt * scale).astype(int)
        if 0 <= pt_scaled[0] < new_w and 0 <= pt_scaled[1] < new_h:
            cv2.circle(step4, tuple(pt_scaled), 2, (255, 0, 255), -1)  # Magenta in BGR
    cv2.putText(step4, "4. Left (cyan) / Right (magenta)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
    
    # Step 5: PCA direction vectors
    # Shows the computed PCA directions as arrows from the center of each edge
    step5 = resize_img(orig_colored.copy(), new_w, new_h)
    # Scale center points to match resized image
    left_center_scaled = (left_center * scale).astype(int)
    right_center_scaled = (right_center * scale).astype(int)
    vec_length = min(new_w, new_h) * 0.3  # Vector length = 30% of smaller dimension
    
    # Left PCA vector (green arrow) - shows dominant direction of left edge
    left_vec_end_scaled = (left_center_scaled + (left_dir * vec_length)).astype(int)
    cv2.arrowedLine(step5, tuple(left_center_scaled), tuple(left_vec_end_scaled),
                   (0, 255, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)  # Green arrow
    cv2.circle(step5, tuple(left_center_scaled), 4, (0, 255, 0), -1)  # Green center point
    
    # Right PCA vector (blue arrow) - shows dominant direction of right edge
    right_vec_end_scaled = (right_center_scaled + (right_dir * vec_length)).astype(int)
    cv2.arrowedLine(step5, tuple(right_center_scaled), tuple(right_vec_end_scaled),
                   (255, 0, 0), 3, tipLength=0.2, line_type=cv2.LINE_AA)  # Blue arrow
    cv2.circle(step5, tuple(right_center_scaled), 4, (255, 0, 0), -1)  # Blue center point
    
    cv2.putText(step5, "5. PCA Directions", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 6: Final result with angle lines
    # Shows the final detected angle as red lines along the PCA directions
    step6 = resize_img(orig_colored.copy(), new_w, new_h)
    # Draw angle lines (red) along the PCA directions
    left_end_scaled = (left_center_scaled + (left_dir * vec_length)).astype(int)
    right_end_scaled = (right_center_scaled + (right_dir * vec_length)).astype(int)
    cv2.line(step6, tuple(left_center_scaled), tuple(left_end_scaled), (0, 0, 255), 2)  # Red line
    cv2.line(step6, tuple(right_center_scaled), tuple(right_end_scaled), (0, 0, 255), 2)  # Red line
    cv2.putText(step6, f"6. Angle: {angle_deg:.2f} deg", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # ============================================================================
    # Combine all steps into a 2x3 grid
    # ============================================================================
    # Pad images to same size (in case of rounding differences)
    def pad_to_size(img, target_w, target_h):
        """Pad image to target size with black borders."""
        h_img, w_img = img.shape[:2]
        pad_h = target_h - h_img
        pad_w = target_w - w_img
        return cv2.copyMakeBorder(img, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    
    target_w, target_h = new_w, new_h
    # Pad all step images to same size
    step1_pad = pad_to_size(step1, target_w, target_h)
    step2_pad = pad_to_size(step2, target_w, target_h)
    step3_pad = pad_to_size(step3, target_w, target_h)
    step4_pad = pad_to_size(step4, target_w, target_h)
    step5_pad = pad_to_size(step5, target_w, target_h)
    step6_pad = pad_to_size(step6, target_w, target_h)
    
    # Create 2x3 grid by stacking images horizontally then vertically
    row1 = np.hstack([step1_pad, step2_pad, step3_pad])  # Top row: Original, Binary, Contour
    row2 = np.hstack([step4_pad, step5_pad, step6_pad])  # Bottom row: Edges, PCA, Final
    debug_img = np.vstack([row1, row2])  # Stack rows vertically
    
    # Add title at top of debug image
    title_height = 50
    debug_img = cv2.copyMakeBorder(debug_img, title_height, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.putText(debug_img, f"Debug Visualization - {image_path.name}", 
                (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)  # Yellow text
    
    return debug_img


def create_partial_debug_image(debug_info: dict, error_msg: str) -> np.ndarray:
    """
    Create a partial debug image when processing fails.
    
    This function is called when an error occurs during processing. It shows what
    was successfully processed before the error (usually original, binary, and contours)
    and displays the error message. This helps diagnose why processing failed.
    
    Args:
        debug_info: Dictionary containing available debug information
                    (must have 'gray' and optionally 'binary')
        error_msg: Error message to display on the debug image
        
    Returns:
        Partial debug visualization image as numpy array (BGR format)
    """
    # Extract available debug information (may be incomplete due to error)
    gray = debug_info.get("gray")
    binary = debug_info.get("binary")
    image_path = debug_info.get("image_path", Path("unknown"))
    
    # If we don't even have the grayscale image, return blank image
    if gray is None:
        return np.zeros((100, 100, 3), dtype=np.uint8)
    
    # Calculate size for 2x2 grid (smaller than full debug since we have less info)
    h, w = gray.shape
    grid_h, grid_w = h // 2, w // 2
    scale = min(grid_w / w, grid_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    
    def resize_img(img, target_w, target_h):
        return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
    
    text_color = (0, 255, 255)  # Yellow text
    
    # Step 1: Original grayscale image (always available)
    orig_colored = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    step1 = resize_img(orig_colored, new_w, new_h)
    cv2.putText(step1, "1. Original", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 2: Binary image (if available)
    if binary is not None:
        binary_colored = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        step2 = resize_img(binary_colored, new_w, new_h)
        cv2.putText(step2, "2. Binary (Otsu)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
        
        # Step 3: Try to find contours (even if they weren't used)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        step3 = resize_img(orig_colored.copy(), new_w, new_h)
        if contours:
            # Draw up to 10 contours with different colors
            for i, c in enumerate(contours[:10]):
                # Generate different colors for each contour
                color = ((i * 50) % 255, (i * 100) % 255, (i * 150) % 255)
                contour_scaled = (c * scale).astype(np.int32)
                cv2.drawContours(step3, [contour_scaled], -1, color, 2)
            cv2.putText(step3, f"3. All Contours ({len(contours)})", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
        else:
            cv2.putText(step3, "3. No Contours", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    else:
        # Binary not available - show placeholder
        step2 = np.zeros((new_h, new_w, 3), dtype=np.uint8)
        cv2.putText(step2, "2. Binary (N/A)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
        step3 = np.zeros((new_h, new_w, 3), dtype=np.uint8)
        cv2.putText(step3, "3. Contours (N/A)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
    
    # Step 4: Error message display
    step4 = np.zeros((new_h, new_w, 3), dtype=np.uint8)  # Black background
    # Split error message into lines (max 4 lines)
    error_lines = error_msg.split('\n')[:4]
    y_pos = 30
    for line in error_lines:
        # Truncate long lines to fit on image
        if len(line) > 40:
            line = line[:37] + "..."
        # Draw error text in red
        cv2.putText(step4, line, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        y_pos += 25  # Move down for next line
    
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
    
    # Create 2x2 grid
    row1 = np.hstack([step1_pad, step2_pad])  # Top row: Original, Binary
    row2 = np.hstack([step3_pad, step4_pad])  # Bottom row: Contours, Error
    debug_img = np.vstack([row1, row2])
    
    # Add title at top
    title_height = 50
    debug_img = cv2.copyMakeBorder(debug_img, title_height, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    title_text = f"Partial Debug - {Path(image_path).name if isinstance(image_path, (Path, str)) else 'unknown'}"
    cv2.putText(debug_img, title_text, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
    
    return debug_img


def _find_local_image(base_dir: Path, base_name: str = "Cone_Trial_Image") -> Path:
    """
    Find image file in directory with various extensions.
    
    This helper function searches for an image file with a given base name
    and common image extensions. Useful for finding default input images.
    
    Args:
        base_dir: Directory to search in
        base_name: Base name of the image file (without extension)
        
    Returns:
        Path to the found image file
        
    Raises:
        FileNotFoundError: If no image with that name and common extensions is found
    """
    # Try common image file extensions
    exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
    for ext in exts:
        candidate = base_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No image named {base_name} with extensions {exts} found in {base_dir}")


def main():
    """
    Main entry point for command-line execution.
    
    This function:
    1. Sets up command-line argument parsing
    2. Tries to find a default input image if none specified
    3. Validates the input path
    4. Calls process_single_image() to do the actual work
    """
    # Try to find a default image (Cone_Trial_Image.*) in the script directory
    # Don't fail if none exists - user might specify --input
    try:
        default_input_path = _find_local_image(CURRENT_DIR)
    except FileNotFoundError:
        default_input_path = None
    
    # Set up command-line argument parser
    parser = argparse.ArgumentParser(description="Contour-based cone angle detection with PCA")
    parser.add_argument("--input", type=Path, default=default_input_path, 
                       help="Path to input TIFF image (default: searches for Cone_Trial_Image.* in script directory)")
    parser.add_argument("--output", type=Path, default=None, 
                       help="Path to output annotated image (default: input_name_cone3.tiff)")
    parser.add_argument("--nozzle-x", type=float, default=None, 
                       help="X-coordinate of nozzle (optional, uses center if not specified)")
    parser.add_argument("--no-open", action="store_true", 
                       help="Do not auto-open annotated image after processing")
    args = parser.parse_args()
    
    # Get input path from arguments
    input_path = args.input
    
    # If no input specified and no default found, try to find Spray_1 as fallback
    if input_path is None or (input_path == default_input_path and default_input_path is None):
        # Try to find Spray_1 as fallback (common test image name)
        exts = [".tiff", ".tif", ".png", ".jpg", ".jpeg", ".bmp"]
        for ext in exts:
            candidate = CURRENT_DIR / f"Spray_1{ext}"
            if candidate.exists():
                input_path = candidate
                break
        
        # If still no image found, raise error with helpful message
        if input_path is None or not input_path.exists():
            raise FileNotFoundError("No input image specified. Use --input or place Cone_Trial_Image.* or Spray_1.* in script directory")
    
    # Final validation: make sure the input path exists
    if not input_path.exists():
        raise FileNotFoundError(f"Input image not found: {input_path}")
    
    # Process the image
    process_single_image(input_path, args.nozzle_x, args.no_open)


def process_single_image(input_path: Path, nozzle_x: float | None, no_open: bool):
    """
    Process a single image and save outputs.
    
    This is the main processing function that:
    1. Calls detect_cone_angle() to analyze the image
    2. Saves the annotated result image
    3. Optionally creates and saves debug visualizations
    4. Optionally opens the result image automatically
    
    Args:
        input_path: Path to input image file
        nozzle_x: Optional x-coordinate of nozzle (None = use center)
        no_open: If True, don't auto-open the result image
    """
    # Auto-generate output name based on input name
    # Example: "Spray_1.tiff" -> "Spray_1_cone3.tiff"
    output_path = input_path.parent / f"{input_path.stem}_cone3{input_path.suffix}"
    
    print(f"[Cone_3] Loading image: {input_path}")
    print(f"[Cone_3] Debug mode: {DEBUG_MODE}")
    
    try:
        # ========================================================================
        # Main processing: detect cone angle
        # ========================================================================
        angle_deg, annotated, debug_info = detect_cone_angle(input_path, nozzle_x)
        
        # Check if detection failed (angle_deg is None indicates failure)
        if angle_deg is None:
            raise RuntimeError(debug_info.get("error", "Contour detection failed"))
        
        # Add angle to debug_info for debug image creation
        debug_info["angle_deg"] = angle_deg
        
        # Print results summary
        print(f"[Cone_3] Detected cone angle: {angle_deg:.2f} degrees")
        print(f"[Cone_3] Contour area: {debug_info['contour_area']:.0f} pixels")
        print(f"[Cone_3] Left points: {debug_info['left_points_count']}, Right points: {debug_info['right_points_count']}")
        print(f"[Cone_3] Left variance explained: {debug_info['left_variance_explained']:.3f}")
        print(f"[Cone_3] Right variance explained: {debug_info['right_variance_explained']:.3f}")
        
        # ========================================================================
        # Save annotated result image
        # ========================================================================
        cv2.imwrite(str(output_path), annotated)
        print(f"[Cone_3] Saved annotated image to: {output_path}")
        
        # ========================================================================
        # Create and save debug image if debug mode is enabled
        # ========================================================================
        if DEBUG_MODE:
            debug_dir = CURRENT_DIR / "cone_3_debug"
            debug_dir.mkdir(exist_ok=True)  # Create directory if it doesn't exist
            debug_img = create_debug_image(debug_info, input_path)
            debug_output_path = debug_dir / f"{input_path.stem}_debug.png"
            cv2.imwrite(str(debug_output_path), debug_img)
            print(f"[Cone_3] Saved debug visualization to: {debug_output_path}")
        
        # ========================================================================
        # Auto-open visualization on macOS (only for single image, not batch)
        # ========================================================================
        if not no_open:
            try:
                if sys.platform == "darwin":  # macOS
                    import subprocess
                    # Open debug image if DEBUG_MODE is enabled, otherwise open annotated image
                    image_to_open = debug_output_path if DEBUG_MODE else output_path
                    # Use macOS 'open' command to open image in default viewer
                    subprocess.run(["open", str(image_to_open)], check=False)
                    print(f"[Cone_3] Opened visualization: {image_to_open}")
                else:
                    # On other platforms (Windows, Linux), use cv2.imshow
                    if DEBUG_MODE:
                        cv2.imshow("Debug Visualization", debug_img)
                    else:
                        cv2.imshow("Annotated Cone", annotated)
                    cv2.waitKey(0)  # Wait for key press
                    cv2.destroyAllWindows()  # Close window
            except Exception as e:
                print(f"[Cone_3] Warning: could not open image automatically: {e}")
                
    except Exception as e:
        # ========================================================================
        # Error handling: create partial debug image if possible
        # ========================================================================
        print(f"[Cone_3] Error: {e}")
        
        # Try to get partial debug info from the error
        # This helps diagnose what went wrong even if processing failed
        partial_debug_info = {"error": str(e), "image_path": input_path}
        try:
            # Try to load image to get at least gray/binary for debug
            # Even if processing failed, we can show what was detected up to that point
            gray = load_image(input_path)
            binary = preprocess_image(gray)
            partial_debug_info["gray"] = gray
            partial_debug_info["binary"] = binary
        except Exception as load_err:
            print(f"[Cone_3] Could not load image for partial debug: {load_err}")
        
        # Save partial debug output if we have at least gray and binary
        # This shows what was successfully processed before the error
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
        
        # Re-raise the exception so caller knows processing failed
        raise


# ============================================================================
# Entry point: run main() when script is executed directly
# ============================================================================
if __name__ == "__main__":
    main()

