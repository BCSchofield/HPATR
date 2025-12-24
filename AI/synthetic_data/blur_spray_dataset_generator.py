"""
Synthetic Spray Dataset Generator for Mask R-CNN Training

This module generates synthetic grayscale spray images with instance-level annotations
for training Mask R-CNN models in Detectron2. It creates realistic droplets and ligaments
with domain randomization to cover a wide range of physically plausible conditions.

REALISM IMPROVEMENTS FOR SHADOWGRAPH IMAGING:
=============================================
1. Droplet Rendering: Absorption-style droplets with radial intensity profiles
   - Dark centers with gradual radial falloff
   - Soft, size-dependent edges using Gaussian blur
   - Subtle bright rim/halo near droplet boundaries
   
2. Size Distribution: Log-normal distribution favoring many small droplets (2-5px)
   - Heavy-tailed distribution matches real spray characteristics
   - Many droplets near noise floor
   
3. Ligament Realism: Non-uniform thickness and intensity along length
   - Varying thickness creates necked regions
   - Intensity variation along curve
   - Can be broken or have gaps
   
4. Background Realism: Grainy, bright background with gradients
   - Low-frequency illumination gradients
   - Additive Gaussian noise for graininess
   - Bright but textured appearance
   
5. Instance Masks: Exact pixel-level binary masks preserved for RLE encoding
   - Masks remain accurate despite realistic rendering
   - Compatible with COCO format and Detectron2
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from multiprocessing import Pool, cpu_count
from functools import partial

import cv2
import matplotlib.pyplot as plt
import numpy as np
from pycocotools import mask as coco_mask


# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# Number of images to generate (adjust for testing)
NUM_IMAGES = 10

# Create side-by-side image/mask visualizations? (True/False)
CREATE_SIDEBYSIDE_VIS = True

# Output Detectron2 essentials only? (True = only images + annotations.json, False = all outputs)
# When True: Skips visualizations and sidebyside to save time/space for large datasets
OUTPUT_DETECTRON_ONLY = False

# Multiprocessing settings
# Number of worker processes (None = use all CPU cores, or set to specific number)
NUM_WORKERS = None  # None = auto-detect (uses all cores), or set to e.g. 4, 8, etc.

# Output directory (will create timestamped folders here)
OUTPUT_BASE_DIR = r"D:\Experiments\TrainingData"

# Image dimensions
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 800
IMAGE_SHAPE = (IMAGE_HEIGHT, IMAGE_WIDTH)

# Intensity ranges
# REALISM: Much brighter background - limit darkest to ~240 (was 200, then 225)
BACKGROUND_INTENSITY_MIN = 240  # Much brighter to avoid dark backgrounds
BACKGROUND_INTENSITY_MAX = 255
LIQUID_INTENSITY_MIN = 20
LIQUID_INTENSITY_MAX = 80

# Droplet parameters - REALISM: Heavy-tailed size distribution
DROPLET_RADIUS_MIN = 2  # Many very small droplets
DROPLET_RADIUS_MAX = 50
DROPLET_POISSON_LAMBDA = 70  # Doubled from 35 - many more droplets per image
# Size distribution: log-normal with heavy tail for small droplets
# REALISM: 25% larger average droplet size (2.0 * 1.25 = 2.5)
DROPLET_SIZE_MU = 2.5  # Log-normal mean (in log space) - 25% larger than 2.0
DROPLET_SIZE_SIGMA = 0.8  # Log-normal std (creates heavy tail)

# Ligament parameters
LIGAMENT_LENGTH_MIN = 30
LIGAMENT_LENGTH_MAX = 600
LIGAMENT_THICKNESS_MIN = 3
LIGAMENT_THICKNESS_MAX = 50
LIGAMENT_POISSON_LAMBDA = 5  # Average number of ligaments per image

# Domain randomization parameters
GAUSSIAN_BLUR_SIGMA_MIN = 0.5
GAUSSIAN_BLUR_SIGMA_MAX = 2.0
MOTION_BLUR_LENGTH_MIN = 3
MOTION_BLUR_LENGTH_MAX = 15
NOISE_STD_MIN = 2.0
NOISE_STD_MAX = 8.0
INTENSITY_SCALE_MIN = 0.9
INTENSITY_SCALE_MAX = 1.1
INTENSITY_SHIFT_MIN = -10
INTENSITY_SHIFT_MAX = 10

# REALISM: Shadowgraph-specific parameters
DROPLET_ABSORPTION_ALPHA_MIN = 80  # Maximum intensity drop at center
DROPLET_ABSORPTION_ALPHA_MAX = 150
DROPLET_ABSORPTION_BETA_MIN = 2.0  # Radial falloff rate
DROPLET_ABSORPTION_BETA_MAX = 4.0
DROPLET_EDGE_BLUR_SIGMA_MIN = 0.3  # Edge softening (size-dependent)
DROPLET_EDGE_BLUR_SIGMA_MAX = 1.5
HALO_INTENSITY_BOOST = 5  # Bright rim intensity boost
HALO_WIDTH_FACTOR = 0.15  # Halo width as fraction of radius
BACKGROUND_GRADIENT_STRENGTH = 10  # Max intensity variation across image
BACKGROUND_NOISE_STD = 3.0  # Base background noise level

# Background blurred droplets (out-of-focus layer)
# REALISM: Simulates droplets that are out of focus - should NOT be annotated
BACKGROUND_DROPLET_POISSON_LAMBDA = 50  # Many blurred droplets in background
BACKGROUND_DROPLET_SIZE_MU = 1.44  # Smaller average size for background (20% smaller: 1.8 * 0.8)
BACKGROUND_DROPLET_SIZE_SIGMA = 1.2  # Wider size distribution
BACKGROUND_DROPLET_BLUR_SIGMA_MIN = 0.5  # Variable blur - can be very light for in-focus
BACKGROUND_DROPLET_BLUR_SIGMA_MAX = 8.0  # Heavy blur for out-of-focus
BACKGROUND_DROPLET_OPACITY = 0.6  # Slightly transparent to blend with background
# Probability that a background droplet is in-focus (crisp, should be annotated)
BACKGROUND_DROPLET_IN_FOCUS_PROB = 0.15  # 15% of background droplets are in-focus
# Minimum blur sigma to be considered "in-focus" (crisp edges)
BACKGROUND_DROPLET_IN_FOCUS_BLUR_THRESHOLD = 1.5  # Below this, droplet is considered in-focus

# Category IDs
CATEGORY_DROPLET = 1
CATEGORY_LIGAMENT = 2


# ============================================================================
# DROPLET GENERATION FUNCTIONS - REALISM: Absorption-style rendering
# ============================================================================

def draw_circular_droplet_realistic(
    image: np.ndarray,
    center: Tuple[int, int],
    radius: float,
    background_intensity: float,
    rng: np.random.Generator,
    apply_edge_blur: bool = True
) -> np.ndarray:
    """
    Draw a realistic circular droplet with absorption-style intensity profile.
    REALISM: Uses distance transform to create radial intensity variation.
    
    Args:
        image: Grayscale image array (will be modified in place)
        center: (x, y) center coordinates
        radius: Droplet radius in pixels
        background_intensity: Background intensity value
        rng: Random number generator for parameter variation
        
    Returns:
        Modified image array
    """
    height, width = image.shape
    cx, cy = center
    
    # Create a binary mask for the droplet
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, center, int(radius), 255, -1)
    
    # REALISM: Use distance transform to create radial intensity profile
    # Distance from center, normalized to [0, 1] at edge
    dist_transform = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    normalized_dist = dist_transform / (radius + 1e-6)  # Avoid division by zero
    normalized_dist = np.clip(normalized_dist, 0, 1)
    
    # REALISM: Absorption model - dark center, gradually lighter toward edge
    # I = background - alpha * exp(-beta * normalized_distance)
    alpha = rng.uniform(DROPLET_ABSORPTION_ALPHA_MIN, DROPLET_ABSORPTION_ALPHA_MAX)
    beta = rng.uniform(DROPLET_ABSORPTION_BETA_MIN, DROPLET_ABSORPTION_BETA_MAX)
    
    # Intensity profile: darker at center, lighter at edges
    intensity_profile = background_intensity - alpha * np.exp(-beta * normalized_dist)
    intensity_profile = np.clip(intensity_profile, 0, 255)
    
    # Apply to image where mask is non-zero
    droplet_region = mask > 0
    image[droplet_region] = intensity_profile[droplet_region].astype(np.uint8)
    
    # REALISM: Add subtle bright rim/halo near edge
    if rng.random() < 0.6:  # 60% chance of halo
        # Create edge mask (pixels near boundary)
        edge_mask = np.zeros_like(mask)
        kernel_size = max(1, int(radius * HALO_WIDTH_FACTOR))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        dilated = cv2.dilate(mask, kernel, iterations=1)
        edge_mask = dilated - mask
        
        # Add bright rim
        rim_intensity = np.clip(background_intensity + HALO_INTENSITY_BOOST, 0, 255)
        image[edge_mask > 0] = np.minimum(
            image[edge_mask > 0].astype(np.float32) + HALO_INTENSITY_BOOST * 0.3,
            255
        ).astype(np.uint8)
    
    # REALISM: Apply minimal size-dependent edge blur for soft edges (only if enabled)
    # For in-focus droplets, use minimal blur; for background, use heavy blur
    if apply_edge_blur:
        blur_sigma = radius * rng.uniform(0.02, 0.05)  # Very minimal blur for in-focus
        blur_sigma = np.clip(blur_sigma, 0.1, 0.5)  # Keep it very small
        ksize = int(6 * blur_sigma + 1)
        if ksize % 2 == 0:
            ksize += 1
        if ksize >= 3:  # Only blur if kernel is large enough
            blurred_region = cv2.GaussianBlur(image, (ksize, ksize), blur_sigma)
            image[droplet_region] = blurred_region[droplet_region]
    
    return image


def draw_elliptical_droplet_realistic(
    image: np.ndarray,
    center: Tuple[int, int],
    axes: Tuple[int, int],
    angle: float,
    background_intensity: float,
    rng: np.random.Generator,
    apply_edge_blur: bool = True
) -> np.ndarray:
    """
    Draw a realistic elliptical droplet with absorption-style intensity profile.
    REALISM: Similar to circular but with elliptical geometry.
    
    Args:
        image: Grayscale image array (will be modified in place)
        center: (x, y) center coordinates
        axes: (major_axis, minor_axis) in pixels
        angle: Rotation angle in degrees
        background_intensity: Background intensity value
        rng: Random number generator for parameter variation
        
    Returns:
        Modified image array
    """
    height, width = image.shape
    
    # Create a binary mask for the droplet
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(mask, center, axes, angle, 0, 360, 255, -1)
    
    # REALISM: Use distance transform for radial intensity profile
    dist_transform = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    # Normalize by average radius
    avg_radius = (axes[0] + axes[1]) / 2.0
    normalized_dist = dist_transform / (avg_radius + 1e-6)
    normalized_dist = np.clip(normalized_dist, 0, 1)
    
    # REALISM: Absorption model
    alpha = rng.uniform(DROPLET_ABSORPTION_ALPHA_MIN, DROPLET_ABSORPTION_ALPHA_MAX)
    beta = rng.uniform(DROPLET_ABSORPTION_BETA_MIN, DROPLET_ABSORPTION_BETA_MAX)
    
    intensity_profile = background_intensity - alpha * np.exp(-beta * normalized_dist)
    intensity_profile = np.clip(intensity_profile, 0, 255)
    
    # Apply to image
    droplet_region = mask > 0
    image[droplet_region] = intensity_profile[droplet_region].astype(np.uint8)
    
    # REALISM: Add subtle bright rim
    if rng.random() < 0.6:
        edge_mask = np.zeros_like(mask)
        kernel_size = max(1, int(avg_radius * HALO_WIDTH_FACTOR))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        dilated = cv2.dilate(mask, kernel, iterations=1)
        edge_mask = dilated - mask
        
        image[edge_mask > 0] = np.minimum(
            image[edge_mask > 0].astype(np.float32) + HALO_INTENSITY_BOOST * 0.3,
            255
        ).astype(np.uint8)
    
    # REALISM: Apply minimal edge blur (only if enabled)
    if apply_edge_blur:
        blur_sigma = avg_radius * rng.uniform(0.02, 0.05)  # Very minimal blur for in-focus
        blur_sigma = np.clip(blur_sigma, 0.1, 0.5)  # Keep it very small
        ksize = int(6 * blur_sigma + 1)
        if ksize % 2 == 0:
            ksize += 1
        if ksize >= 3:  # Only blur if kernel is large enough
            blurred_region = cv2.GaussianBlur(image, (ksize, ksize), blur_sigma)
            image[droplet_region] = blurred_region[droplet_region]
    
    return image


def draw_blurred_background_droplet(
    image: np.ndarray,
    center: Tuple[int, int],
    radius: float,
    background_intensity: float,
    rng: np.random.Generator,
    blur_sigma: Optional[float] = None
) -> np.ndarray:
    """
    Draw a background droplet with variable blur (can be in-focus or out-of-focus).
    REALISM: Blur level is randomized per droplet. In-focus ones should be annotated.
    
    Args:
        image: Grayscale image array (will be modified in place)
        center: (x, y) center coordinates
        radius: Droplet radius in pixels
        background_intensity: Background intensity value
        rng: Random number generator
        blur_sigma: Optional blur sigma (if None, randomly generated)
        
    Returns:
        Modified image array
    """
    height, width = image.shape
    cx, cy = center
    
    # Create a binary mask for the droplet
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, center, int(radius), 255, -1)
    
    # Use distance transform for radial intensity profile
    dist_transform = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    normalized_dist = dist_transform / (radius + 1e-6)
    normalized_dist = np.clip(normalized_dist, 0, 1)
    
    # Absorption model (similar to in-focus but can be lighter)
    alpha = rng.uniform(DROPLET_ABSORPTION_ALPHA_MIN * 0.7, DROPLET_ABSORPTION_ALPHA_MAX * 0.9)
    beta = rng.uniform(DROPLET_ABSORPTION_BETA_MIN, DROPLET_ABSORPTION_BETA_MAX)
    
    intensity_profile = background_intensity - alpha * np.exp(-beta * normalized_dist)
    intensity_profile = np.clip(intensity_profile, 0, 255)
    
    # Create droplet layer
    droplet_layer = image.copy()
    droplet_region = mask > 0
    droplet_layer[droplet_region] = intensity_profile[droplet_region].astype(np.float32)
    
    # REALISM: Apply variable blur - randomized per droplet
    if blur_sigma is None:
        blur_sigma = rng.uniform(BACKGROUND_DROPLET_BLUR_SIGMA_MIN, BACKGROUND_DROPLET_BLUR_SIGMA_MAX)
    ksize = int(6 * blur_sigma + 1)
    if ksize % 2 == 0:
        ksize += 1
    
    # Blur the entire droplet layer
    blurred_layer = cv2.GaussianBlur(droplet_layer, (ksize, ksize), blur_sigma)
    
    # Blend with background using opacity
    # Only blend where the original droplet was (expanded region due to blur)
    blurred_mask = cv2.GaussianBlur(mask.astype(np.float32), (ksize, ksize), blur_sigma)
    blurred_mask = blurred_mask / 255.0  # Normalize to [0, 1]
    blurred_mask = np.clip(blurred_mask * BACKGROUND_DROPLET_OPACITY, 0, 1)
    
    # Blend: image = background * (1 - mask) + blurred_droplet * mask
    image = image.astype(np.float32)
    image = image * (1 - blurred_mask) + blurred_layer * blurred_mask
    
    return image


def generate_background_droplet_parameters(
    rng: np.random.Generator,
    image_shape: Tuple[int, int]
) -> Dict:
    """
    Generate random parameters for a background blurred droplet.
    REALISM: Wider size distribution for out-of-focus droplets.
    
    Args:
        rng: NumPy random number generator
        image_shape: (height, width) of the image
        
    Returns:
        Dictionary with droplet parameters (circular only for simplicity)
    """
    height, width = image_shape
    
    # Random position (can be anywhere, including edges)
    margin = 20  # Smaller margin for background droplets
    x = rng.integers(margin, width - margin)
    y = rng.integers(margin, height - margin)
    center = (x, y)
    
    # REALISM: Wider size distribution for background droplets
    log_radius = rng.normal(BACKGROUND_DROPLET_SIZE_MU, BACKGROUND_DROPLET_SIZE_SIGMA)
    radius = np.exp(log_radius)
    radius = np.clip(radius, DROPLET_RADIUS_MIN, DROPLET_RADIUS_MAX * 1.5)  # Can be larger
    
    return {
        'type': 'circular',
        'center': center,
        'radius': radius
    }


def get_droplet_diameter(params: Dict) -> float:
    """
    Calculate the diameter of a droplet from its parameters.
    
    Args:
        params: Droplet parameters dictionary
        
    Returns:
        Diameter in pixels
    """
    if params['type'] == 'circular':
        return 2.0 * params['radius']
    else:  # elliptical
        # Use average of major and minor axes as effective diameter
        return (params['axes'][0] + params['axes'][1])


def generate_droplet_parameters(
    rng: np.random.Generator,
    image_shape: Tuple[int, int]
) -> Dict:
    """
    Generate random parameters for a droplet.
    REALISM: Uses log-normal distribution for heavy-tailed size distribution.
    
    Args:
        rng: NumPy random number generator
        image_shape: (height, width) of the image
        
    Returns:
        Dictionary with droplet parameters:
        - type: 'circular' or 'elliptical'
        - center: (x, y) tuple
        - radius: float (for circular)
        - axes: (major, minor) tuple (for elliptical)
        - angle: float (for elliptical)
    """
    height, width = image_shape
    
    # Random position with margin to avoid edge clipping
    margin = 60
    x = rng.integers(margin, width - margin)
    y = rng.integers(margin, height - margin)
    center = (x, y)
    
    # REALISM: Log-normal size distribution - many small, few large droplets
    # This creates a heavy-tailed distribution favoring small droplets
    log_radius = rng.normal(DROPLET_SIZE_MU, DROPLET_SIZE_SIGMA)
    radius = np.exp(log_radius)
    radius = np.clip(radius, DROPLET_RADIUS_MIN, DROPLET_RADIUS_MAX)
    
    # Decide between circular and elliptical (75% circular, 25% elliptical)
    if rng.random() < 0.75:
        return {
            'type': 'circular',
            'center': center,
            'radius': radius
        }
    else:
        # Elliptical droplet - use similar size distribution
        log_major = rng.normal(DROPLET_SIZE_MU, DROPLET_SIZE_SIGMA)
        major_axis = np.clip(np.exp(log_major), DROPLET_RADIUS_MIN, DROPLET_RADIUS_MAX * 1.5)
        minor_axis = rng.uniform(DROPLET_RADIUS_MIN, major_axis)
        axes = (int(major_axis), int(minor_axis))
        angle = rng.uniform(0, 360)
        return {
            'type': 'elliptical',
            'center': center,
            'axes': axes,
            'angle': angle
        }


# ============================================================================
# LIGAMENT GENERATION FUNCTIONS
# ============================================================================

def draw_straight_ligament_realistic(
    image: np.ndarray,
    start: Tuple[int, int],
    end: Tuple[int, int],
    base_thickness: int,
    base_intensity: float,
    background_intensity: float,
    rng: np.random.Generator
) -> np.ndarray:
    """
    Draw a realistic straight ligament as a stretched droplet (transparent unit).
    REALISM: Uses absorption-style intensity profile like droplets, creating a cohesive transparent unit.
    
    Args:
        image: Grayscale image array (will be modified in place)
        start: (x, y) start coordinates
        end: (x, y) end coordinates
        base_thickness: Base thickness (radius) in pixels
        base_intensity: Base intensity drop from background
        background_intensity: Background intensity value
        rng: Random number generator
        
    Returns:
        Modified image array
    """
    height, width = image.shape
    
    # Calculate line length and direction
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = np.sqrt(dx**2 + dy**2)
    
    if length < 1:
        return image
    
    # Create a capsule-shaped mask (rectangle with rounded ends)
    mask = np.zeros((height, width), dtype=np.uint8)
    
    # Calculate angle for rotation
    angle_rad = np.arctan2(dy, dx)
    angle_deg = np.degrees(angle_rad)
    
    # Center point
    center_x = (start[0] + end[0]) / 2.0
    center_y = (start[1] + end[1]) / 2.0
    center = (int(center_x), int(center_y))
    
    # Create capsule: ellipse with major axis = length, minor axis = 2 * thickness
    axes = (int(length / 2), base_thickness)
    
    # Draw filled ellipse (capsule shape)
    cv2.ellipse(mask, center, axes, angle_deg, 0, 360, 255, -1)
    
    # REALISM: Use distance transform to create radial intensity profile (like droplets)
    dist_transform = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    # Normalize by thickness (radius)
    normalized_dist = dist_transform / (base_thickness + 1e-6)
    normalized_dist = np.clip(normalized_dist, 0, 1)
    
    # REALISM: Absorption model - dark center, gradually lighter toward edge
    # Use similar parameters to droplets but slightly adjusted for ligaments
    alpha = rng.uniform(DROPLET_ABSORPTION_ALPHA_MIN * 0.8, DROPLET_ABSORPTION_ALPHA_MAX * 0.95)
    beta = rng.uniform(DROPLET_ABSORPTION_BETA_MIN, DROPLET_ABSORPTION_BETA_MAX)
    
    # Intensity profile: darker at center, lighter at edges
    intensity_profile = background_intensity - alpha * np.exp(-beta * normalized_dist)
    intensity_profile = np.clip(intensity_profile, 0, 255)
    
    # Apply to image where mask is non-zero
    ligament_region = mask > 0
    image[ligament_region] = intensity_profile[ligament_region].astype(np.uint8)
    
    # REALISM: Add subtle bright rim/halo near edge (optional, less common for ligaments)
    if rng.random() < 0.3:  # 30% chance of halo (less than droplets)
        edge_mask = np.zeros_like(mask)
        kernel_size = max(1, int(base_thickness * HALO_WIDTH_FACTOR))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        dilated = cv2.dilate(mask, kernel, iterations=1)
        edge_mask = dilated - mask
        
        image[edge_mask > 0] = np.minimum(
            image[edge_mask > 0].astype(np.float32) + HALO_INTENSITY_BOOST * 0.2,
            255
        ).astype(np.uint8)
    
    return image


def draw_curved_ligament_realistic(
    image: np.ndarray,
    control_points: List[Tuple[int, int]],
    base_thickness: int,
    base_intensity: float,
    background_intensity: float,
    rng: np.random.Generator
) -> np.ndarray:
    """
    Draw a realistic curved ligament as a stretched droplet (transparent unit).
    REALISM: Uses absorption-style intensity profile like droplets, following the curve path.
    
    Args:
        image: Grayscale image array (will be modified in place)
        control_points: List of (x, y) control points for the curve
        base_thickness: Base thickness (radius) in pixels
        base_intensity: Base intensity drop from background
        background_intensity: Background intensity value
        rng: Random number generator
        
    Returns:
        Modified image array
    """
    if len(control_points) < 2:
        return image
    
    # Convert to numpy array for easier manipulation
    points = np.array(control_points, dtype=np.int32)
    
    # Calculate total curve length for parameterization
    if len(control_points) == 2:
        # Simple straight line
        return draw_straight_ligament_realistic(
            image, tuple(points[0]), tuple(points[1]), 
            base_thickness, base_intensity, background_intensity, rng
        )
    
    height, width = image.shape
    
    # REALISM: Generate Bezier curve with more points for smooth mask
    t_values = np.linspace(0, 1, max(100, int(np.linalg.norm(points[-1] - points[0]) / 2)))
    curve_points = []
    
    n = len(control_points) - 1
    for t in t_values:
        point = np.zeros(2)
        for i, p in enumerate(control_points):
            # Bernstein polynomial
            coeff = (math.factorial(n) / 
                    (math.factorial(i) * math.factorial(n - i))) * \
                    (t ** i) * ((1 - t) ** (n - i))
            point += coeff * np.array(p)
        curve_points.append(point.astype(int))
    
    # Create mask by drawing thick curve (capsule segments along the path)
    mask = np.zeros((height, width), dtype=np.uint8)
    
    # Draw capsule segments along the curve
    for i in range(len(curve_points) - 1):
        p1 = tuple(curve_points[i])
        p2 = tuple(curve_points[i + 1])
        
        # Draw thick line segment
        cv2.line(mask, p1, p2, 255, base_thickness * 2)
    
    # Add rounded caps at the ends
    cv2.circle(mask, tuple(curve_points[0]), base_thickness, 255, -1)
    cv2.circle(mask, tuple(curve_points[-1]), base_thickness, 255, -1)
    
    # Fill any gaps by dilating slightly
    kernel_size = max(3, base_thickness // 2)
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    
    # REALISM: Use distance transform to create radial intensity profile (like droplets)
    dist_transform = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    # Normalize by thickness (radius)
    normalized_dist = dist_transform / (base_thickness + 1e-6)
    normalized_dist = np.clip(normalized_dist, 0, 1)
    
    # REALISM: Absorption model - dark center, gradually lighter toward edge
    # Use similar parameters to droplets but slightly adjusted for ligaments
    alpha = rng.uniform(DROPLET_ABSORPTION_ALPHA_MIN * 0.8, DROPLET_ABSORPTION_ALPHA_MAX * 0.95)
    beta = rng.uniform(DROPLET_ABSORPTION_BETA_MIN, DROPLET_ABSORPTION_BETA_MAX)
    
    # Intensity profile: darker at center, lighter at edges
    intensity_profile = background_intensity - alpha * np.exp(-beta * normalized_dist)
    intensity_profile = np.clip(intensity_profile, 0, 255)
    
    # Apply to image where mask is non-zero
    ligament_region = mask > 0
    image[ligament_region] = intensity_profile[ligament_region].astype(np.uint8)
    
    # REALISM: Add subtle bright rim/halo near edge (optional, less common for ligaments)
    if rng.random() < 0.3:  # 30% chance of halo (less than droplets)
        edge_mask = np.zeros_like(mask)
        kernel_size = max(1, int(base_thickness * HALO_WIDTH_FACTOR))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        dilated = cv2.dilate(mask, kernel, iterations=1)
        edge_mask = dilated - mask
        
        image[edge_mask > 0] = np.minimum(
            image[edge_mask > 0].astype(np.float32) + HALO_INTENSITY_BOOST * 0.2,
            255
        ).astype(np.uint8)
    
    return image


def generate_ligament_parameters(
    rng: np.random.Generator,
    image_shape: Tuple[int, int]
) -> Dict:
    """
    Generate random parameters for a ligament.
    
    Args:
        rng: NumPy random number generator
        image_shape: (height, width) of the image
        
    Returns:
        Dictionary with ligament parameters:
        - type: 'straight' or 'curved'
        - start: (x, y) tuple
        - end: (x, y) tuple (for straight)
        - control_points: List of (x, y) tuples (for curved)
        - thickness: int
        - intensity: int
    """
    height, width = image_shape
    margin = 60
    
    # Random start position
    start_x = rng.integers(margin, width - margin)
    start_y = rng.integers(margin, height - margin)
    start = (start_x, start_y)
    
    # Random thickness (intensity will be calculated from background)
    thickness = rng.integers(LIGAMENT_THICKNESS_MIN, LIGAMENT_THICKNESS_MAX + 1)
    
    # Decide between straight and curved (5% straight, 95% curved)
    if rng.random() < 0.05:
        # Straight ligament (rare - only 5%)
        length = rng.uniform(LIGAMENT_LENGTH_MIN, LIGAMENT_LENGTH_MAX)
        angle = rng.uniform(0, 2 * np.pi)
        end_x = int(start_x + length * np.cos(angle))
        end_y = int(start_y + length * np.sin(angle))
        
        # Clamp to image bounds
        end_x = max(margin, min(width - margin, end_x))
        end_y = max(margin, min(height - margin, end_y))
        end = (end_x, end_y)
        
        return {
            'type': 'straight',
            'start': start,
            'end': end,
            'thickness': thickness
        }
    else:
        # Curved ligament (95% of the time) with multiple direction changes
        # Generate more control points for complex curves with multiple direction changes
        # Number of control points: 4-10 for more complex curves
        num_points = rng.integers(4, 11)
        control_points = [start]
        
        current_x, current_y = start_x, start_y
        # Start with a random initial direction
        current_angle = rng.uniform(0, 2 * np.pi)
        
        # Total target length for the ligament
        total_length = rng.uniform(LIGAMENT_LENGTH_MIN, LIGAMENT_LENGTH_MAX)
        # Average segment length
        avg_segment_length = total_length / (num_points - 1)
        
        for i in range(num_points - 1):
            # Vary segment length (some segments longer, some shorter)
            segment_length = avg_segment_length * rng.uniform(0.5, 1.5)
            
            # Change direction - can turn significantly (up to 180 degrees)
            # More likely to continue in similar direction but with some variation
            angle_change = rng.normal(0, np.pi / 3)  # Mean 0, std dev = 60 degrees
            # Clamp to reasonable range (can turn up to ~120 degrees)
            angle_change = np.clip(angle_change, -2 * np.pi / 3, 2 * np.pi / 3)
            current_angle += angle_change
            
            # Occasionally make a sharp turn (random direction change)
            if rng.random() < 0.3:  # 30% chance of sharp turn
                current_angle = rng.uniform(0, 2 * np.pi)
            
            # Calculate next point
            next_x = int(current_x + segment_length * np.cos(current_angle))
            next_y = int(current_y + segment_length * np.sin(current_angle))
            
            # Clamp to image bounds
            next_x = max(margin, min(width - margin, next_x))
            next_y = max(margin, min(height - margin, next_y))
            
            # Avoid going back to the same point
            if next_x != current_x or next_y != current_y:
                control_points.append((next_x, next_y))
                current_x, current_y = next_x, next_y
        
        # Ensure we have at least 2 points (start + one more)
        if len(control_points) < 2:
            # Fallback: add a point in a random direction
            angle = rng.uniform(0, 2 * np.pi)
            length = rng.uniform(LIGAMENT_LENGTH_MIN / 2, LIGAMENT_LENGTH_MAX / 2)
            end_x = max(margin, min(width - margin, int(start_x + length * np.cos(angle))))
            end_y = max(margin, min(height - margin, int(start_y + length * np.sin(angle))))
            control_points.append((end_x, end_y))
        
        return {
            'type': 'curved',
            'control_points': control_points,
            'thickness': thickness
        }


# ============================================================================
# INSTANCE MASK GENERATION
# ============================================================================

def create_instance_mask(
    shape: Tuple[int, int],
    instance_type: str,
    params: Dict
) -> np.ndarray:
    """
    Create a binary mask for a single instance.
    
    Args:
        shape: (height, width) of the mask
        instance_type: 'droplet' or 'ligament'
        params: Parameters dictionary for the instance
        
    Returns:
        Binary mask (255 for instance, 0 for background)
    """
    mask = np.zeros(shape, dtype=np.uint8)
    
    if instance_type == 'droplet':
        if params['type'] == 'circular':
            cv2.circle(mask, params['center'], int(params['radius']), 255, -1)
        else:  # elliptical
            cv2.ellipse(mask, params['center'], params['axes'], 
                       params['angle'], 0, 360, 255, -1)
    
    elif instance_type == 'ligament':
        if params['type'] == 'straight':
            # Match the drawing method: capsule shape (ellipse)
            start = params['start']
            end = params['end']
            thickness = params['thickness']
            
            # Calculate length and angle
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = np.sqrt(dx**2 + dy**2)
            angle_deg = np.degrees(np.arctan2(dy, dx))
            
            # Center point
            center_x = (start[0] + end[0]) / 2.0
            center_y = (start[1] + end[1]) / 2.0
            center = (int(center_x), int(center_y))
            
            # Create capsule: ellipse with major axis = length, minor axis = 2 * thickness
            axes = (int(length / 2), thickness)
            cv2.ellipse(mask, center, axes, angle_deg, 0, 360, 255, -1)
        else:  # curved
            control_points = params['control_points']
            thickness = params['thickness']
            
            if len(control_points) == 2:
                # Simple line - use capsule shape
                start = control_points[0]
                end = control_points[1]
                dx = end[0] - start[0]
                dy = end[1] - start[1]
                length = np.sqrt(dx**2 + dy**2)
                angle_deg = np.degrees(np.arctan2(dy, dx))
                center = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
                axes = (int(length / 2), thickness)
                cv2.ellipse(mask, center, axes, angle_deg, 0, 360, 255, -1)
            else:
                # Draw curved ligament on mask - match the drawing method
                # Generate Bezier curve with more points
                t_values = np.linspace(0, 1, max(100, int(np.linalg.norm(
                    np.array(control_points[-1]) - np.array(control_points[0])) / 2)))
                n = len(control_points) - 1
                curve_points = []
                
                for t in t_values:
                    point = np.zeros(2)
                    for i, p in enumerate(control_points):
                        coeff = (math.factorial(n) / 
                                (math.factorial(i) * math.factorial(n - i))) * \
                                (t ** i) * ((1 - t) ** (n - i))
                        point += coeff * np.array(p)
                    curve_points.append(point.astype(int))
                
                # Draw capsule segments along the curve (match drawing method)
                for i in range(len(curve_points) - 1):
                    p1 = tuple(curve_points[i])
                    p2 = tuple(curve_points[i + 1])
                    # Draw thick line segment (thickness * 2 to match drawing)
                    cv2.line(mask, p1, p2, 255, thickness * 2)
                
                # Add rounded caps at the ends
                cv2.circle(mask, tuple(curve_points[0]), thickness, 255, -1)
                cv2.circle(mask, tuple(curve_points[-1]), thickness, 255, -1)
                
                # Fill any gaps by dilating slightly (match drawing method)
                kernel_size = max(3, thickness // 2)
                if kernel_size % 2 == 0:
                    kernel_size += 1
                kernel = np.ones((kernel_size, kernel_size), np.uint8)
                mask = cv2.dilate(mask, kernel, iterations=1)
    
    return mask


def extract_contours_from_mask(mask: np.ndarray) -> List[List[Tuple[int, int]]]:
    """
    Extract polygon contours from a binary mask.
    
    Args:
        mask: Binary mask (255 for foreground, 0 for background)
        
    Returns:
        List of contours, where each contour is a list of (x, y) points
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    polygon_contours = []
    for contour in contours:
        # Simplify contour to reduce number of points
        epsilon = 0.002 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        
        # Convert to list of (x, y) tuples
        points = [(int(point[0][0]), int(point[0][1])) for point in approx]
        if len(points) >= 3:  # Valid polygon needs at least 3 points
            polygon_contours.append(points)
    
    return polygon_contours


# ============================================================================
# REALISTIC BACKGROUND GENERATION
# ============================================================================

def create_realistic_background(
    image_shape: Tuple[int, int],
    base_intensity: float,
    rng: np.random.Generator
) -> np.ndarray:
    """
    Create a realistic shadowgraph background with gradients and noise.
    REALISM: Low-frequency illumination gradient + grainy noise.
    Ensures background stays bright (minimum enforced).
    
    Args:
        image_shape: (height, width) of the image
        base_intensity: Base background intensity
        rng: Random number generator
        
    Returns:
        Background image array
    """
    height, width = image_shape
    
    # Start with uniform background
    background = np.full((height, width), base_intensity, dtype=np.float32)
    
    # REALISM: Add low-frequency illumination gradient
    # Create smooth gradient using multiple sine waves
    y_coords, x_coords = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')
    
    # Random gradient direction and strength (reduced to avoid darkening)
    gradient_strength = rng.uniform(0.2, 0.6) * BACKGROUND_GRADIENT_STRENGTH  # Reduced max from 1.0 to 0.6
    angle = rng.uniform(0, 2 * np.pi)
    wavelength_x = rng.uniform(width * 0.5, width * 2.0)
    wavelength_y = rng.uniform(height * 0.5, height * 2.0)
    phase = rng.uniform(0, 2 * np.pi)
    
    gradient = gradient_strength * np.sin(
        2 * np.pi * (x_coords * np.cos(angle) / wavelength_x + 
                     y_coords * np.sin(angle) / wavelength_y) + phase
    )
    background += gradient
    
    # REALISM: Add grainy Gaussian noise (reduced to avoid darkening)
    noise = rng.normal(0, BACKGROUND_NOISE_STD * 0.7, (height, width))  # Reduced noise
    background += noise
    
    # REALISM: Ensure minimum brightness - clip to stay above minimum
    background = np.clip(background, BACKGROUND_INTENSITY_MIN, 255)
    
    return background.astype(np.uint8)


# ============================================================================
# DOMAIN RANDOMIZATION FUNCTIONS
# ============================================================================

def apply_gaussian_blur(
    image: np.ndarray,
    rng: np.random.Generator
) -> np.ndarray:
    """
    Apply random Gaussian blur to simulate optical PSF.
    
    Args:
        image: Input grayscale image
        rng: NumPy random number generator
        
    Returns:
        Blurred image
    """
    sigma = rng.uniform(GAUSSIAN_BLUR_SIGMA_MIN, GAUSSIAN_BLUR_SIGMA_MAX)
    ksize = int(6 * sigma + 1)
    if ksize % 2 == 0:
        ksize += 1
    return cv2.GaussianBlur(image, (ksize, ksize), sigma)


def apply_motion_blur(
    image: np.ndarray,
    rng: np.random.Generator
) -> np.ndarray:
    """
    Apply random motion blur in a random direction.
    
    Args:
        image: Input grayscale image
        rng: NumPy random number generator
        
    Returns:
        Motion-blurred image
    """
    length = rng.integers(MOTION_BLUR_LENGTH_MIN, MOTION_BLUR_LENGTH_MAX + 1)
    angle = rng.uniform(0, 360)
    
    # Create motion blur kernel
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[int((length - 1) / 2), :] = np.ones(length, dtype=np.float32)
    kernel = kernel / length
    
    # Rotate kernel
    M = cv2.getRotationMatrix2D((length / 2, length / 2), angle, 1.0)
    kernel = cv2.warpAffine(kernel, M, (length, length))
    
    # Apply blur
    blurred = cv2.filter2D(image, -1, kernel)
    return blurred


def add_gaussian_noise(
    image: np.ndarray,
    rng: np.random.Generator
) -> np.ndarray:
    """
    Add random Gaussian noise to the image.
    
    Args:
        image: Input grayscale image
        rng: NumPy random number generator
        
    Returns:
        Noisy image
    """
    std = rng.uniform(NOISE_STD_MIN, NOISE_STD_MAX)
    noise = rng.normal(0, std, image.shape).astype(np.float32)
    noisy = image.astype(np.float32) + noise
    return np.clip(noisy, 0, 255).astype(np.uint8)


def apply_intensity_variation(
    image: np.ndarray,
    rng: np.random.Generator
) -> np.ndarray:
    """
    Apply random intensity scaling and shifting.
    
    Args:
        image: Input grayscale image
        rng: NumPy random number generator
        
    Returns:
        Image with modified intensity
    """
    scale = rng.uniform(INTENSITY_SCALE_MIN, INTENSITY_SCALE_MAX)
    shift = rng.integers(INTENSITY_SHIFT_MIN, INTENSITY_SHIFT_MAX + 1)
    
    adjusted = image.astype(np.float32) * scale + shift
    return np.clip(adjusted, 0, 255).astype(np.uint8)


# ============================================================================
# COCO ANNOTATION GENERATION
# ============================================================================

def generate_coco_annotations(
    instances: List[Dict],
    image_id: int,
    image_filename: str,
    image_shape: Tuple[int, int]
) -> Tuple[List[Dict], Dict]:
    """
    Generate COCO-format annotations for a single image using RLE encoding.
    
    Args:
        instances: List of instance dictionaries with 'type', 'params', 'mask', 'category_id'
        image_id: Unique image ID
        image_filename: Filename of the image
        image_shape: (height, width) of the image
        
    Returns:
        Tuple of (annotations_list, image_dict)
    """
    height, width = image_shape
    
    # Image entry
    image_dict = {
        'id': image_id,
        'file_name': image_filename,
        'height': height,
        'width': width
    }
    
    # Annotation entries
    annotations = []
    annotation_id = image_id * 1000  # Base annotation ID
    
    for instance in instances:
        mask = instance['mask']
        
        # Convert mask to binary (0/1) for pycocotools
        # Mask is currently 0/255, convert to 0/1
        binary_mask = (mask > 0).astype(np.uint8)
        
        # Skip if mask is empty
        if np.sum(binary_mask) == 0:
            continue
        
        # Encode mask to RLE format using pycocotools
        rle = coco_mask.encode(np.asfortranarray(binary_mask))
        # Ensure counts is a string for JSON serialization
        if isinstance(rle['counts'], bytes):
            rle['counts'] = rle['counts'].decode('utf-8')
        # Ensure size is a list (not numpy array) for JSON serialization
        rle['size'] = list(rle['size'])
        
        # Calculate bounding box from mask
        rows = np.any(binary_mask, axis=1)
        cols = np.any(binary_mask, axis=0)
        
        if not np.any(rows) or not np.any(cols):
            continue
        
        y_min, y_max = np.where(rows)[0][[0, -1]]
        x_min, x_max = np.where(cols)[0][[0, -1]]
        
        bbox = [float(x_min), float(y_min), 
                float(x_max - x_min + 1), float(y_max - y_min + 1)]
        
        # Calculate area from mask
        area = float(np.sum(binary_mask))
        
        annotation = {
            'id': annotation_id,
            'image_id': image_id,
            'category_id': instance['category_id'],
            'segmentation': rle,  # RLE format: {'size': [height, width], 'counts': '...'}
            'bbox': bbox,
            'area': area,
            'iscrowd': 0
        }
        
        annotations.append(annotation)
        annotation_id += 1
    
    return annotations, image_dict


# ============================================================================
# MAIN IMAGE GENERATION FUNCTION
# ============================================================================

def generate_synthetic_image(
    rng: np.random.Generator,
    image_shape: Tuple[int, int],
    config: Dict
) -> Tuple[np.ndarray, List[Dict]]:
    """
    Generate a single realistic synthetic spray image with instances.
    REALISM: Uses absorption-style droplets, realistic background, varying ligaments.
    Adds background layer of out-of-focus blurred droplets (NOT annotated).
    
    Args:
        rng: NumPy random number generator
        image_shape: (height, width) of the image
        config: Configuration dictionary (currently unused, for future extension)
        
    Returns:
        Tuple of (image, instances_list)
        instances_list contains dicts with 'type', 'params', 'mask', 'category_id'
        NOTE: Background blurred droplets are NOT included in instances_list
    """
    height, width = image_shape
    
    # REALISM: Create realistic background with gradients and noise
    bg_intensity = rng.integers(BACKGROUND_INTENSITY_MIN, BACKGROUND_INTENSITY_MAX + 1)
    image = create_realistic_background(image_shape, bg_intensity, rng)
    image = image.astype(np.float32)  # Use float for intermediate calculations
    
    # REALISM: Add background layer of droplets with variable blur
    # Some are in-focus (crisp edges) and should be annotated, others are blurred (not annotated)
    num_background_droplets = rng.poisson(BACKGROUND_DROPLET_POISSON_LAMBDA)
    background_instances = []  # Track in-focus background droplets for annotation
    
    for _ in range(num_background_droplets):
        params = generate_background_droplet_parameters(rng, image_shape)
        
        # Randomly decide if this background droplet is in-focus (crisp) or blurred
        is_in_focus = rng.random() < BACKGROUND_DROPLET_IN_FOCUS_PROB
        
        if is_in_focus:
            # In-focus background droplet: use low blur (crisp edges)
            blur_sigma = rng.uniform(
                BACKGROUND_DROPLET_BLUR_SIGMA_MIN, 
                BACKGROUND_DROPLET_IN_FOCUS_BLUR_THRESHOLD
            )
        else:
            # Out-of-focus background droplet: use heavy blur
            blur_sigma = rng.uniform(
                BACKGROUND_DROPLET_IN_FOCUS_BLUR_THRESHOLD,
                BACKGROUND_DROPLET_BLUR_SIGMA_MAX
            )
        
        # Draw background droplet with specified blur level
        image = draw_blurred_background_droplet(
            image, params['center'], params['radius'],
            float(bg_intensity), rng, blur_sigma=blur_sigma
        )
        
        # If in-focus, add to instances for annotation
        if is_in_focus:
            # Create mask for annotation
            mask = create_instance_mask(image_shape, 'droplet', params)
            background_instances.append({
                'type': 'droplet',
                'params': params,
                'mask': mask,
                'category_id': CATEGORY_DROPLET
            })
    
    # Generate instances (in-focus foreground droplets, in-focus background droplets, and ligaments)
    instances = []
    # Track all drawn objects for occlusion detection
    occlusion_mask = np.zeros(image_shape, dtype=np.uint8)
    
    # Generate foreground droplets - REALISM: More droplets with log-normal size distribution
    num_droplets = rng.poisson(DROPLET_POISSON_LAMBDA)
    for _ in range(num_droplets):
        params = generate_droplet_parameters(rng, image_shape)
        
        # Filter out small droplets (< 20px diameter) - don't annotate them
        diameter = get_droplet_diameter(params)
        if diameter < 20.0:
            # Still draw the droplet in the image, but don't annotate it
            if params['type'] == 'circular':
                image = draw_circular_droplet_realistic(
                    image, params['center'], params['radius'], 
                    float(bg_intensity), rng, apply_edge_blur=False
                )
            else:
                image = draw_elliptical_droplet_realistic(
                    image, params['center'], params['axes'], 
                    params['angle'], float(bg_intensity), rng, apply_edge_blur=False
                )
            # Update occlusion mask (but don't annotate)
            droplet_mask = create_instance_mask(image_shape, 'droplet', params)
            occlusion_mask = np.maximum(occlusion_mask, droplet_mask)
            continue  # Skip annotation for small droplets
        
        # REALISM: Draw realistic in-focus droplet with absorption profile
        # apply_edge_blur=False for in-focus droplets (minimal blur)
        if params['type'] == 'circular':
            image = draw_circular_droplet_realistic(
                image, params['center'], params['radius'], 
                float(bg_intensity), rng, apply_edge_blur=False
            )
        else:
            image = draw_elliptical_droplet_realistic(
                image, params['center'], params['axes'], 
                params['angle'], float(bg_intensity), rng, apply_edge_blur=False
            )
        
        # Create mask for annotation (exact binary mask)
        mask = create_instance_mask(image_shape, 'droplet', params)
        
        # Check if droplet is completely occluded by previously drawn objects
        # A droplet is occluded if all its pixels are already covered
        visible_area = np.sum((mask > 0) & (occlusion_mask == 0))
        total_area = np.sum(mask > 0)
        
        # Only annotate if at least some area is visible (not completely occluded)
        if visible_area > 0 and total_area > 0:
            # Check if enough is visible (at least 10% visible to avoid tiny slivers)
            visibility_ratio = visible_area / total_area
            if visibility_ratio >= 0.1:
                instances.append({
                    'type': 'droplet',
                    'params': params,
                    'mask': mask,
                    'category_id': CATEGORY_DROPLET
                })
                # Update occlusion mask
                occlusion_mask = np.maximum(occlusion_mask, mask)
    
    # Add in-focus background droplets to instances (filter small ones and check occlusion)
    for bg_instance in background_instances:
        diameter = get_droplet_diameter(bg_instance['params'])
        if diameter >= 20.0:  # Only annotate if >= 20px diameter
            mask = bg_instance['mask']
            # Check occlusion
            visible_area = np.sum((mask > 0) & (occlusion_mask == 0))
            total_area = np.sum(mask > 0)
            if visible_area > 0 and total_area > 0:
                visibility_ratio = visible_area / total_area
                if visibility_ratio >= 0.1:
                    instances.append(bg_instance)
                    occlusion_mask = np.maximum(occlusion_mask, mask)
    
    # Generate ligaments - REALISM: Varying thickness and intensity
    num_ligaments = rng.poisson(LIGAMENT_POISSON_LAMBDA)
    for _ in range(num_ligaments):
        params = generate_ligament_parameters(rng, image_shape)
        
        # Calculate base intensity drop from background
        base_intensity_drop = rng.uniform(
            LIQUID_INTENSITY_MIN, LIQUID_INTENSITY_MAX
        )
        
        # REALISM: Draw realistic ligament with varying properties
        if params['type'] == 'straight':
            image = draw_straight_ligament_realistic(
                image, params['start'], params['end'], 
                params['thickness'], base_intensity_drop, 
                float(bg_intensity), rng
            )
        else:
            image = draw_curved_ligament_realistic(
                image, params['control_points'], 
                params['thickness'], base_intensity_drop,
                float(bg_intensity), rng
            )
        
        # Create mask for annotation (exact binary mask matching the drawn shape)
        mask = create_instance_mask(image_shape, 'ligament', params)
        
        instances.append({
            'type': 'ligament',
            'params': params,
            'mask': mask,
            'category_id': CATEGORY_LIGAMENT
        })
        
        # Update occlusion mask (ligaments can occlude future droplets)
        occlusion_mask = np.maximum(occlusion_mask, mask)
    
    # Convert back to uint8
    image = np.clip(image, 0, 255).astype(np.uint8)
    
    # REALISM: Apply additional domain randomization (reduced probability)
    # Less aggressive since we already have realistic rendering
    if rng.random() < 0.3:  # 30% chance of additional blur
        image = apply_gaussian_blur(image, rng)
    
    if rng.random() < 0.2:  # 20% chance of motion blur
        image = apply_motion_blur(image, rng)
    
    # Additional noise is already in background, but can add more
    if rng.random() < 0.4:  # 40% chance of additional noise
        image = add_gaussian_noise(image, rng)
    
    return image, instances


# ============================================================================
# VISUALIZATION FUNCTION
# ============================================================================

def visualize_instances(
    image: np.ndarray,
    instances: List[Dict],
    output_path: str
) -> None:
    """
    Create a visualization overlay showing instance masks on the image.
    
    Args:
        image: Grayscale image
        instances: List of instance dictionaries
        output_path: Path to save the visualization
    """
    # Convert to RGB for colored overlay
    vis_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    
    # Create overlay with transparency
    overlay = vis_image.copy()
    
    # Draw each instance with different colors
    for instance in instances:
        mask = instance['mask']
        category_id = instance['category_id']
        
        # Color: blue for droplets, red for ligaments
        if category_id == CATEGORY_DROPLET:
            color = (0, 255, 0)  # Green for droplets
        else:
            color = (255, 0, 0)  # Red for ligaments
        
        # Create colored mask
        colored_mask = np.zeros_like(vis_image)
        colored_mask[mask > 0] = color
        
        # Blend with overlay
        overlay = cv2.addWeighted(overlay, 1.0, colored_mask, 0.4, 0)
    
    # Draw contours
    for instance in instances:
        mask = instance['mask']
        category_id = instance['category_id']
        
        if category_id == CATEGORY_DROPLET:
            color = (0, 255, 0)
        else:
            color = (255, 0, 0)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, color, 2)
    
    # Save visualization
    cv2.imwrite(output_path, cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))


def create_sidebyside_visualization(
    image: np.ndarray,
    instances: List[Dict],
    output_path: str
) -> None:
    """
    Create a side-by-side visualization showing original image and visualization with colored masks.
    
    Args:
        image: Grayscale image
        instances: List of instance dictionaries
        output_path: Path to save the visualization
    """
    height, width = image.shape
    
    # Left side: Original image (convert to RGB)
    image_rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    
    # Right side: Create visualization with colored masks (same as visualize_instances)
    vis_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    overlay = vis_image.copy()
    
    # Draw each instance with different colors
    for instance in instances:
        mask = instance['mask']
        category_id = instance['category_id']
        
        # Color: green for droplets, red for ligaments
        if category_id == CATEGORY_DROPLET:
            color = (0, 255, 0)  # Green for droplets
        else:
            color = (255, 0, 0)  # Red for ligaments
        
        # Create colored mask
        colored_mask = np.zeros_like(vis_image)
        colored_mask[mask > 0] = color
        
        # Blend with overlay
        overlay = cv2.addWeighted(overlay, 1.0, colored_mask, 0.4, 0)
    
    # Draw contours
    for instance in instances:
        mask = instance['mask']
        category_id = instance['category_id']
        
        if category_id == CATEGORY_DROPLET:
            color = (0, 255, 0)
        else:
            color = (255, 0, 0)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, color, 2)
    
    # Create side-by-side image
    sidebyside = np.hstack([image_rgb, overlay])
    
    # Add labels
    # Create a small text overlay area at the top
    label_height = 40
    sidebyside_with_labels = np.zeros((height + label_height, width * 2, 3), dtype=np.uint8)
    sidebyside_with_labels[label_height:, :] = sidebyside
    
    # Add text labels
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1.2
    thickness = 2
    text_color = (255, 255, 255)
    
    # Left label: "Original Image"
    text_size_left = cv2.getTextSize("Original Image", font, font_scale, thickness)[0]
    text_x_left = (width - text_size_left[0]) // 2
    cv2.putText(sidebyside_with_labels, "Original Image", 
                (text_x_left, 30), font, font_scale, text_color, thickness)
    
    # Right label: "Visualization"
    text_size_right = cv2.getTextSize("Visualization", font, font_scale, thickness)[0]
    text_x_right = width + (width - text_size_right[0]) // 2
    cv2.putText(sidebyside_with_labels, "Visualization", 
                (text_x_right, 30), font, font_scale, text_color, thickness)
    
    # Save visualization
    cv2.imwrite(output_path, cv2.cvtColor(sidebyside_with_labels, cv2.COLOR_RGB2BGR))


# ============================================================================
# MULTIPROCESSING WORKER FUNCTION
# ============================================================================

def generate_single_image_worker(args):
    """
    Worker function for multiprocessing - generates a single image and returns data.
    
    Args:
        args: Tuple of (image_id, image_filename, images_dir_str, image_shape, config, 
                        detectron_only, visualizations_dir_str, sidebyside_dir_str, create_sidebyside)
    
    Returns:
        Dictionary with image data, annotations, and paths
    """
    (image_id, image_filename, images_dir_str, image_shape, config, 
     detectron_only, visualizations_dir_str, sidebyside_dir_str, create_sidebyside) = args
    
    # Convert string paths back to Path objects
    images_dir = Path(images_dir_str)
    visualizations_dir = Path(visualizations_dir_str) if visualizations_dir_str else None
    sidebyside_dir = Path(sidebyside_dir_str) if sidebyside_dir_str else None
    
    # Create independent RNG for this worker (seed based on image_id for reproducibility)
    rng = np.random.default_rng(seed=image_id)
    
    # Generate synthetic image
    image, instances = generate_synthetic_image(rng, image_shape, config)
    
    # Save image
    image_path = images_dir / image_filename
    cv2.imwrite(str(image_path), image)
    
    # Generate annotations
    annotations, image_dict = generate_coco_annotations(
        instances, image_id, image_filename, image_shape
    )
    
    result = {
        'image_dict': image_dict,
        'annotations': annotations,
        'image_id': image_id
    }
    
    # Create visualizations only if not in detectron-only mode
    if not detectron_only and visualizations_dir:
        # Create visualization
        vis_path = visualizations_dir / f"blur_image_{image_id:04d}_vis.png"
        visualize_instances(image, instances, str(vis_path))
        
        # Create side-by-side visualization if enabled
        if create_sidebyside and sidebyside_dir:
            sidebyside_path = sidebyside_dir / f"blur_image_{image_id:04d}_sidebyside.png"
            create_sidebyside_visualization(image, instances, str(sidebyside_path))
    
    return result


# ============================================================================
# DATASET GENERATION FUNCTION
# ============================================================================

def generate_dataset(
    num_images: int,
    base_output_dir: str,
    config: Optional[Dict] = None,
    create_sidebyside: bool = False,
    detectron_only: bool = False,
    num_workers: Optional[int] = None
) -> Dict:
    """
    Generate a complete synthetic dataset.
    
    Args:
        num_images: Number of images to generate
        base_output_dir: Base output directory (synthetic_data folder)
        config: Optional configuration dictionary
        
    Returns:
        Dictionary with paths to generated files
    """
    if config is None:
        config = {}
    
    # Create timestamped folder with "blur_" prefix
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    output_dir = Path(base_output_dir) / f"blur_{timestamp}"
    images_dir = output_dir / "images"
    
    images_dir.mkdir(parents=True, exist_ok=True)
    
    # Only create visualization directories if not in detectron-only mode
    visualizations_dir = None
    sidebyside_dir = None
    if not detectron_only:
        visualizations_dir = output_dir / "visualizations"
        visualizations_dir.mkdir(parents=True, exist_ok=True)
        
        # Create side-by-side directory if enabled
        if create_sidebyside:
            sidebyside_dir = output_dir / "sidebyside"
            sidebyside_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating {num_images} synthetic images...")
    print(f"Output directory: {output_dir}")
    print(f"{'='*60}")
    
    # Initialize COCO dataset structure
    coco_dataset = {
        'images': [],
        'annotations': [],
        'categories': [
            {'id': CATEGORY_DROPLET, 'name': 'droplet'},
            {'id': CATEGORY_LIGAMENT, 'name': 'ligament'}
        ]
    }
    
    # Determine number of workers
    if num_workers is None:
        num_workers = cpu_count() if NUM_WORKERS is None else NUM_WORKERS
    
    # Use multiprocessing if more than 1 worker, otherwise use sequential (faster for small batches)
    if num_workers > 1 and num_images > 1:
        print(f"Using {num_workers} worker process(es) for parallel generation")
        
        # Prepare arguments for workers (convert Path objects to strings for multiprocessing)
        worker_args = []
        for i in range(num_images):
            image_id = i + 1
            image_filename = f"blur_image_{image_id:04d}.png"
            worker_args.append((
                image_id, image_filename, str(images_dir), IMAGE_SHAPE, config,
                detectron_only, 
                str(visualizations_dir) if visualizations_dir else None,
                str(sidebyside_dir) if sidebyside_dir else None,
                create_sidebyside
            ))
        
        # Generate images using multiprocessing
        print(f"Starting parallel generation of {num_images} images...")
        try:
            with Pool(processes=num_workers) as pool:
                results = pool.map(generate_single_image_worker, worker_args)
            
            # Collect and merge results
            print("Collecting results and generating annotations...")
            for result in results:
                coco_dataset['images'].append(result['image_dict'])
                coco_dataset['annotations'].extend(result['annotations'])
        except Exception as e:
            print(f"Multiprocessing failed: {e}")
            print("Falling back to sequential generation...")
            num_workers = 1  # Fall through to sequential code
    
    # Sequential generation (for single worker or fallback)
    if num_workers == 1:
        print("Using sequential generation (single process)")
        rng = np.random.default_rng()
        
        # Calculate progress reporting intervals (every 1%)
        last_reported_percent = -1
        
        for i in range(num_images):
            image_id = i + 1
            image_filename = f"blur_image_{image_id:04d}.png"
            image_path = images_dir / image_filename
            
            # Generate synthetic image
            image, instances = generate_synthetic_image(rng, IMAGE_SHAPE, config)
            
            # Save image
            cv2.imwrite(str(image_path), image)
            
            # Generate annotations
            annotations, image_dict = generate_coco_annotations(
                instances, image_id, image_filename, IMAGE_SHAPE
            )
            
            coco_dataset['images'].append(image_dict)
            coco_dataset['annotations'].extend(annotations)
            
            # Create visualizations only if not in detectron-only mode
            if not detectron_only:
                # Create visualization
                vis_path = visualizations_dir / f"blur_image_{image_id:04d}_vis.png"
                visualize_instances(image, instances, str(vis_path))
                
                # Create side-by-side visualization if enabled
                if create_sidebyside and sidebyside_dir:
                    sidebyside_path = sidebyside_dir / f"blur_image_{image_id:04d}_sidebyside.png"
                    create_sidebyside_visualization(image, instances, str(sidebyside_path))
            
            # Report progress every 1%
            current_percent = int((image_id / num_images) * 100)
            if current_percent > last_reported_percent or image_id == num_images:
                print(f"  Progress: {current_percent}% ({image_id}/{num_images} images)")
                last_reported_percent = current_percent
    
    # Sort by image_id to ensure correct order
    coco_dataset['images'].sort(key=lambda x: x['id'])
    coco_dataset['annotations'].sort(key=lambda x: x['image_id'])
    
    # Save COCO annotations
    annotations_path = output_dir / "blur_annotations.json"
    with open(annotations_path, 'w') as f:
        json.dump(coco_dataset, f, indent=2)
    
    print(f"\nDataset generation complete!")
    print(f"  Images: {images_dir}")
    print(f"  Annotations: {annotations_path}")
    if not detectron_only:
        print(f"  Visualizations: {visualizations_dir}")
        if sidebyside_dir:
            print(f"  Side-by-side: {sidebyside_dir}")
    else:
        print(f"  Mode: Detectron2 essentials only (no visualizations)")
    print(f"  Total instances: {len(coco_dataset['annotations'])}")
    
    return {
        'output_dir': str(output_dir),
        'images_dir': str(images_dir),
        'annotations_path': str(annotations_path),
        'visualizations_dir': str(visualizations_dir),
        'num_images': num_images,
        'num_annotations': len(coco_dataset['annotations'])
    }


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # Use configured output directory
    output_base_dir = Path(OUTPUT_BASE_DIR)
    # Create directory if it doesn't exist
    output_base_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_base_dir}")
    
    # Generate dataset
    results = generate_dataset(
        NUM_IMAGES, 
        str(output_base_dir), 
        create_sidebyside=CREATE_SIDEBYSIDE_VIS,
        detectron_only=OUTPUT_DETECTRON_ONLY,
        num_workers=NUM_WORKERS
    )
    
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Generated {results['num_images']} images")
    print(f"  Generated {results['num_annotations']} annotations")
    print(f"  Output folder: {results['output_dir']}")
    print(f"{'='*60}")
