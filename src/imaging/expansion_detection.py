# Merge term 1
"""
HPATR Expansion Detection Module
Core image processing functions for droplet detection using Canny, Watershed, and optimization.
"""
import cv2
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import os
import time

def _gamma_correct_gray(img_gray, gamma=0.75):
    """Apply gamma correction to a single-channel 8-bit image.
    gamma < 1 brightens shadows; gamma > 1 darkens.
    """
    gamma = max(gamma, 1e-6)
    inv = 1.0 / gamma
    # build LUT once per call (256 entries)
    lut = (np.linspace(0, 1, 256) ** inv * 255.0).astype(np.uint8)
    return cv2.LUT(img_gray, lut)

def validate_image(img):
    """Validate loaded image"""
    if img is None:
        raise FileNotFoundError("Image could not be loaded")
    if len(img.shape) != 3:
        raise ValueError("Image must be 3-channel (BGR/RGB)")
    if img.size == 0:
        raise ValueError("Image is empty")
    return True

def process_image(
    input_image_path,
    output_dir=None,
    # Preprocessing
    denoise_ksize: int = 1, #2...Stronger (7-9) removers more noise, but may soften thin edges. Lower keeps edges crisp with less noise suppression.
    clahe_clip: float = 8.0, #3,,,Stronger (3-4) has stronger local contrast, but can amplify noise and grain. Lower is safer on noisy images.
    clahe_tile: tuple = (18, 18), #12,12...Size of clahe grid. Smaller (6x6) will have stronger local equalisation which is better for uneven lighting.
    gamma: float = 0.4, #0.75...<1 brightens shadows and reveals faint edges. 
    blur_ksize: int = 1, #3...Larger has more smoothing and softens edges, smaller (3-5) has sharper edges but may pass more noise to next sections.
    # Canny
    canny_thresh1: int = 50,
    canny_thresh2: int = 150,
    # Hough
    hough_min_radius: int = 15,
    hough_max_radius: int = 120,
    hough_param1: int = 40,
    hough_param2: int = 25,
    hough_min_dist: int = 25,
):
    """Process an image with Canny, Watershed, Hough and optimization.

    Tunable parameters allow adapting preprocessing and detectors to your data.

    Preprocessing:
      - denoise_ksize (odd): median filter kernel size
      - clahe_clip, clahe_tile: CLAHE local contrast
      - gamma: <1 brightens; >1 darkens
      - blur_ksize (odd): Gaussian blur kernel size

    Canny:
      - canny_thresh1, canny_thresh2

    Hough:
      - hough_min_radius, hough_max_radius, hough_param1, hough_param2, hough_min_dist
    """
    
    # Create output directory if specified
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # ==== LOAD IMAGE ====
    img = cv2.imread(input_image_path)
    if img is None:
        raise FileNotFoundError(f"Image not found: {input_image_path}")
    
    # Validate the loaded image
    validate_image(img)
    
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ==== PREPROCESSING: denoise → local contrast (CLAHE) → gamma → normalize → blur ====
    # 1) gentle denoise that preserves edges
    denoised = cv2.medianBlur(gray, ksize=max(3, denoise_ksize | 1))
    # 2) local contrast boost
    clahe = cv2.createCLAHE(clipLimit=float(clahe_clip), tileGridSize=tuple(clahe_tile))
    local_contrast = clahe.apply(denoised)
    # 3) gamma to brighten dim features (tunable)
    gamma_corrected = _gamma_correct_gray(local_contrast, gamma=float(gamma))
    # 4) normalize to full 0-255 range
    enhanced = cv2.normalize(gamma_corrected, None, 0, 255, cv2.NORM_MINMAX)
    # 5) light blur for Canny/Hough robustness
    k = max(3, blur_ksize | 1)
    blur = cv2.GaussianBlur(enhanced, (k, k), 0)

    # Collect preprocessing debug images and params for downstream visualization
    preprocess_debug = {
        'gray': gray,
        'denoised': denoised,
        'clahe': local_contrast,
        'gamma_corrected': gamma_corrected,
        'enhanced': enhanced,
        'blur': blur,
    }
    preprocess_params = {
        'denoise_ksize': int(denoise_ksize),
        'clahe_clip': float(clahe_clip),
        'clahe_tile': tuple(clahe_tile),
        'gamma': float(gamma),
        'blur_ksize': int(blur_ksize),
    }

    # ==== STEP 1: CANNY EDGE DETECTION FOR SMALL DROPLETS ====
    print("Step 1: Canny Edge Detection for small droplets...")
    
    # Canny edge detection (tunable)
    edges = cv2.Canny(blur, int(canny_thresh1), int(canny_thresh2))
    
    # Find contours from Canny edges
    canny_contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Convert Canny contours to circles
    canny_circles = []
    for contour in canny_contours:
        area = cv2.contourArea(contour)
        if area > MIN_DROPLET_AREA and area < SMALL_DROPLET_MAX_AREA:
            # Fit minimum enclosing circle
            (x, y), radius = cv2.minEnclosingCircle(contour)
            if radius >= 5:  # Minimum radius filter
                canny_circles.append([x, y, radius])
    
    print(f"Canny detection found {len(canny_circles)} small droplets")

    # Save Canny edge detection image (only when running directly)
    if not output_dir:
        canny_filename = f"CANNY_EDGES.png"
        canny_save_path = os.path.join("/tmp", canny_filename)  # Temporary location
        cv2.imwrite(canny_save_path, edges)
        print(f"Canny edge detection saved: {canny_save_path}")
    else:
        print(f"Canny edge detection will be saved by calling script")

    # ==== STEP 2: WATERSHED + HOUGH FOR LARGE DROPLETS ====
    print("Step 2: Watershed + Hough detection for large droplets...")
    
    # Thresholding & Morphological Operations
    ret, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = np.ones((3, 3), np.uint8)
    opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
    
    # Hough Circle Detection for large droplets
    min_radius = int(hough_min_radius)
    max_radius = int(hough_max_radius)
    param1 = int(hough_param1)
    param2 = int(hough_param2)
    min_dist = int(hough_min_dist)
    
    hough_circles = cv2.HoughCircles(
        blur, 
        cv2.HOUGH_GRADIENT, 
        dp=1,
        minDist=min_dist,
        param1=param1,
        param2=param2,
        minRadius=min_radius,
        maxRadius=max_radius
    )
    
    watershed_circles = []
    watershed_debug_images = {}  # Store watershed debug images
    if hough_circles is not None:
        hough_circles = np.round(hough_circles[0, :]).astype("int")
        print(f"Hough detection found {len(hough_circles)} potential large droplets")
        
        # Watershed processing with Hough markers
        sure_bg = cv2.dilate(opening, kernel, iterations=WATERSHED_DILATION_ITERATIONS)
        dist_transform = cv2.distanceTransform(opening, cv2.DIST_L2, WATERSHED_DISTANCE_KERNEL)
        ret, sure_fg = cv2.threshold(dist_transform, WATERSHED_DISTANCE_THRESHOLD * dist_transform.max(), 255, 0)
        sure_fg = np.uint8(sure_fg)
        unknown = cv2.subtract(sure_bg, sure_fg)
        
        # Create markers with filtering for small connected components
        ret, markers = cv2.connectedComponents(sure_fg)
        markers = markers + 1
        markers[unknown == 255] = 0
        
        # Filter out small connected component markers
        print(f"Filtering connected component markers...")
        original_marker_count = markers.max() - 1
        filtered_markers = np.zeros_like(markers)
        filtered_markers[unknown == 255] = 0  # Keep unknown regions as 0
        
        # Start with label 1 (background)
        filtered_markers[markers == 1] = 1
        next_filtered_label = 2
        
        for label in range(2, markers.max() + 1):
            # Get mask for this connected component
            component_mask = (markers == label)
            component_area = np.sum(component_mask)
            
            # Only keep components above minimum area threshold
            if component_area >= MIN_CONNECTED_COMPONENT_AREA:
                filtered_markers[component_mask] = next_filtered_label
                next_filtered_label += 1
                print(f"  Kept connected component {label-1}: area={component_area} pixels")
            else:
                print(f"  Filtered out small connected component {label-1}: area={component_area} pixels (below {MIN_CONNECTED_COMPONENT_AREA})")
        
        markers = filtered_markers
        filtered_marker_count = markers.max() - 1
        print(f"Filtered markers: {original_marker_count} -> {filtered_marker_count} (removed {original_marker_count - filtered_marker_count} small components)")
        
        # Add Hough circles as markers
        next_label = markers.max() + 1
        hough_markers_added = 0
        for (x, y, r) in hough_circles:
            if (0 <= y < markers.shape[0] and 0 <= x < markers.shape[1]):
                # Check if near foreground
                search_radius = max(5, r // 2)
                found_foreground = False
                for dy in range(-search_radius, search_radius + 1):
                    for dx in range(-search_radius, search_radius + 1):
                        ny, nx = y + dy, x + dx
                        if (0 <= ny < markers.shape[0] and 0 <= nx < markers.shape[1]):
                            if (sure_fg[ny, nx] > 0 or opening[ny, nx] > 0):
                                found_foreground = True
                                break
                    if found_foreground:
                        break
                
                if found_foreground:
                    markers[y, x] = next_label
                    next_label += 1
                    hough_markers_added += 1
                    print(f"  Added Hough marker {hough_markers_added} at ({x}, {y}) with radius {r}")
                else:
                    print(f"  Skipped Hough circle at ({x}, {y}) - no foreground nearby")
        
        print(f"Added {hough_markers_added} Hough markers out of {len(hough_circles)} circles")
        
        # Apply watershed
        markers_ws = cv2.watershed(img_rgb, markers)
        
        # Create detailed markers visualization
        markers_viz = img_rgb.copy()
        for label in range(2, markers.max() + 1):
            # Find all pixels with this label
            label_mask = (markers == label)
            if np.any(label_mask):
                # Get center of mass for this marker
                y_coords, x_coords = np.where(label_mask)
                center_x = int(np.mean(x_coords))
                center_y = int(np.mean(y_coords))
                
                # Draw marker center
                cv2.circle(markers_viz, (center_x, center_y), 3, (255, 255, 0), -1)  # Yellow center
                cv2.putText(markers_viz, str(label-1), (center_x+5, center_y-5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
        
        # Add Hough circle markers in different color
        for i, (x, y, r) in enumerate(hough_circles):
            cv2.circle(markers_viz, (int(x), int(y)), 2, (0, 255, 255), -1)  # Cyan for Hough
            cv2.putText(markers_viz, f"H{i+1}", (int(x)+5, int(y)+5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        
        # Store watershed debug images
        watershed_debug_images = {
            'original': img_rgb,
            'threshold': thresh,
            'opening': opening,
            'sure_background': sure_bg,
            'distance_transform': dist_transform,
            'sure_foreground': sure_fg,
            'unknown_region': unknown,
            'markers': markers,
            'markers_visualization': markers_viz,  # Add detailed markers visualization
            'watershed_result': markers_ws
        }
        
        # Extract watershed regions with area filtering
        print(f"Extracting watershed regions from {markers_ws.max() - 1} labels...")
        watershed_regions_found = 0
        small_regions_skipped = 0
        
        # Debug: Check what watershed labels actually exist
        print(f"DEBUG: Watershed labels range from 2 to {markers_ws.max()}")
        for label in range(2, markers_ws.max() + 1):
            mask = np.zeros_like(gray)
            mask[markers_ws == label] = 255
            
            # Count pixels for this label
            label_pixel_count = np.sum(mask > 0)
            print(f"  Label {label}: {label_pixel_count} pixels")
            
            # Find contours in this watershed region
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > MIN_DROPLET_AREA:
                    (x, y), radius = cv2.minEnclosingCircle(contour)
                    if radius >= 10:  # Minimum radius for watershed results
                        watershed_circles.append([x, y, radius])
                        watershed_regions_found += 1
                        print(f"    Kept watershed region {watershed_regions_found}: center=({x:.1f}, {y:.1f}), radius={radius:.1f}, area={area:.0f}")
                    else:
                        small_regions_skipped += 1
                        print(f"    [SKIP] Skipped small region: center=({x:.1f}, {y:.1f}), radius={radius:.1f} (too small)")
                else:
                    small_regions_skipped += 1
                    print(f"    [SKIP] Skipped small region: area={area:.0f} (below MIN_DROPLET_AREA={MIN_DROPLET_AREA})")
        
        print(f"Watershed extraction complete: {watershed_regions_found} regions kept, {small_regions_skipped} small regions skipped")
    
    print(f"Watershed processing found {len(watershed_circles)} large droplets")

    # ==== STEP 3: COMBINE ALL DETECTED CIRCLES ====
    print("Step 3: Combining all detected circles...")
    
    all_circles = []
    circle_sources = []  # Track which method found each circle
    
    # Add Canny circles
    for circle in canny_circles:
        all_circles.append(circle)
        circle_sources.append("Canny")
    
    # Add Watershed circles (avoid duplicates)
    for watershed_circle in watershed_circles:
        # Check if this circle is too close to existing ones
        is_duplicate = False
        for existing_circle in all_circles:
            dx = watershed_circle[0] - existing_circle[0]
            dy = watershed_circle[1] - existing_circle[1]
            distance = np.sqrt(dx*dx + dy*dy)
            if distance < 20:  # If centers are within 20 pixels, consider duplicate
                is_duplicate = True
                break
        
        if not is_duplicate:
            all_circles.append(watershed_circle)
            circle_sources.append("Watershed")
    
    print(f"Combined detection: {len(all_circles)} total circles")
    print(f"  - Canny: {circle_sources.count('Canny')} circles")
    print(f"  - Watershed: {circle_sources.count('Watershed')} circles")
    
    # Debug: Print details of each circle
    print("\nDEBUG: Circle details before optimization:")
    for i, (circle, source) in enumerate(zip(all_circles, circle_sources)):
        print(f"  Circle {i+1}: ({circle[0]:.1f}, {circle[1]:.1f}, r={circle[2]:.1f}) - {source}")

    # ==== STEP 4: OPTIMIZE ALL CIRCLES ====
    print("Step 4: Optimizing all detected circles...")
    
    optimized_circles = []
    optimization_data = []
    position_optimization_data = []
    
    if len(all_circles) > 0:
        # First optimize circle sizes
        optimized_circles, optimization_debug = optimize_circle_sizes(all_circles, gray)
        
        # Store circles after size optimization (before position optimization)
        size_optimized_circles = optimized_circles.copy()
        
        # Debug: Print what's actually in size_optimized_circles
        print("\nDEBUG: Size optimized circles (should have same centers as original):")
        for i, (orig, size_opt) in enumerate(zip(all_circles, size_optimized_circles)):
            print(f"  Circle {i+1}: Original ({orig[0]:.1f}, {orig[1]:.1f}) -> Size-opt ({size_opt[0]:.1f}, {size_opt[1]:.1f})")
        
        # Then optimize positions for circles below target
        print("\nStep 4b: Optimizing circle positions...")
        position_optimized_circles = []
        
        for i, (original_circle, optimized_circle, source) in enumerate(zip(all_circles, optimized_circles, circle_sources)):
            print(f"Position optimizing circle {i+1}/{len(optimized_circles)} ({source})")
            
            # Get the final black percentage from size optimization
            final_black_pct = 0
            if i < len(optimization_debug.get('final_percentages', [])):
                final_black_pct = optimization_debug['final_percentages'][i]
            
            # Only optimize position if below target
            if final_black_pct < 98:
                # Dynamic search radius based on droplet size
                # Larger droplets can move further (less risk of moving to wrong droplet)
                droplet_radius = optimized_circle[2]
                dynamic_search_radius = int(min(50, max(10, droplet_radius * 0.8)))  # Convert to int

                print(f"  Using dynamic search radius: {dynamic_search_radius}px (droplet radius: {droplet_radius:.1f}px)")
                
                position_optimized_circle, position_percentage, position_info = optimize_circle_position(
                    optimized_circle, gray, search_radius=dynamic_search_radius, step_size=3
                )
                position_optimized_circles.append(position_optimized_circle)
                position_optimization_data.append(position_info)
                print(f"  Position optimization: {final_black_pct:.1f}% → {position_percentage:.1f}%")
            else:
                position_optimized_circles.append(optimized_circle)
                position_optimization_data.append({
                    'original_position': [optimized_circle[0], optimized_circle[1]],
                    'best_position': [optimized_circle[0], optimized_circle[1]],
                    'movement_distance': 0,
                    'improvement': 0,
                    'positions_tested': 0,
                    'best_positions': [[optimized_circle[0], optimized_circle[1]]]
                })
                print(f"  Already above target ({final_black_pct:.1f}%), skipping position optimization")
        
        # Use position-optimized circles for final results
        optimized_circles = position_optimized_circles
        
        # Create comprehensive optimization data
        for i, (original_circle, optimized_circle, source) in enumerate(zip(all_circles, optimized_circles, circle_sources)):
            original_radius = original_circle[2]
            optimized_radius = optimized_circle[2]
            radius_change_pct = ((optimized_radius - original_radius) / original_radius) * 100
            
            # Get final black percentage (after position optimization)
            final_black_pct = 0
            if i < len(optimization_debug.get('final_percentages', [])):
                final_black_pct = optimization_debug['final_percentages'][i]
            
            # Add position optimization info
            position_info = position_optimization_data[i]
            movement_distance = position_info['movement_distance']
            position_improvement = position_info['improvement']
            
            optimization_data.append({
                'circle_number': i + 1,
                'detection_method': source,
                'original_diameter_px': original_radius * 2,
                'optimized_diameter_px': optimized_radius * 2,
                'radius_change_percent': radius_change_pct,
                'final_black_percentage': final_black_pct,
                'x_coord': optimized_circle[0],
                'y_coord': optimized_circle[1],
                'position_movement_pixels': movement_distance,
                'position_improvement_percent': position_improvement,
                'positions_tested': position_info['positions_tested']
            })
    
    print(f"Optimization complete: {len(optimized_circles)} circles optimized")

    # ==== STEP 5: CREATE FINAL OUTPUT ====
    print("Step 5: Creating final output...")
    
    # Create final annotated image
    final_image = img_rgb.copy()
    
    # Draw all optimized circles
    for i, (circle, data) in enumerate(zip(optimized_circles, optimization_data)):
        x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
        
        # Color based on detection method
        if data['detection_method'] == 'Canny':
            color = (0, 255, 0)  # Green for Canny
        else:
            color = (255, 0, 0)  # Red for Watershed
        
        # Draw circle
        cv2.circle(final_image, (x, y), r, color, 2)
        
        # Add circle number
        cv2.putText(final_image, str(i+1), (x-10, y-10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    
    # Results are saved by the calling script (save_and_analyse.py or __main__ section)
    if output_dir:
        print(f"Results will be saved by calling script to: {output_dir}")
    
    # Print summary
    print(f"\nFINAL SUMMARY:")
    print(f"  Total droplets detected: {len(optimized_circles)}")
    print(f"  Canny detection: {circle_sources.count('Canny')} droplets")
    print(f"  Watershed detection: {circle_sources.count('Watershed')} droplets")
    print(f"  Average radius change: {np.mean([d['radius_change_percent'] for d in optimization_data]):.1f}%")
    print(f"  Average final black percentage: {np.mean([d['final_black_percentage'] for d in optimization_data]):.1f}%")
    
    return {
        'final_image': final_image,
        'optimized_circles': optimized_circles,
        'optimization_data': optimization_data,
        'canny_circles': canny_circles,
        'watershed_circles': watershed_circles,
        'circle_sources': circle_sources,
        'all_circles_before_optimization': all_circles,  # Add this to track original circles
        'position_optimization_data': position_optimization_data,  # Add position optimization data
        'size_optimized_circles': size_optimized_circles,  # Add circles after size optimization
        'watershed_debug_images': watershed_debug_images,  # Add watershed debug images
        'canny_edges': edges,  # Add canny edges for the watershed debug visualization
        'preprocess_debug': preprocess_debug,
        'preprocess_params': preprocess_params,
    }

def calculate_black_percentage_numpy(gray_img, cx, cy, cr, black_threshold=128):
    """
    Calculate black pixel percentage for a circle using NumPy masks (vectorized, fast).
    
    Args:
        gray_img: Grayscale image (2D numpy array)
        cx: Circle center x coordinate
        cy: Circle center y coordinate
        cr: Circle radius
        black_threshold: Pixel value threshold for black (default 128)
    
    Returns:
        percentage: Black pixel percentage (0-100)
        total_pixels: Total pixels in circle
    """
    height, width = gray_img.shape
    
    # Create coordinate grids for entire image
    y_coords, x_coords = np.ogrid[:height, :width]
    
    # Calculate distance squared from circle center for ALL pixels at once
    distances_squared = (x_coords - cx)**2 + (y_coords - cy)**2
    
    # Create boolean mask: True where pixel is inside circle
    circle_mask = distances_squared <= cr**2
    
    # Extract pixels inside circle and count black ones
    pixels_in_circle = gray_img[circle_mask]
    black_pixels = np.sum(pixels_in_circle < black_threshold)
    total_pixels = np.sum(circle_mask)
    
    percentage = (black_pixels / total_pixels) * 100 if total_pixels > 0 else 0
    return percentage, total_pixels

def optimize_circle_sizes(circles, original_image, target_black_percentage=98, max_expansion_factor=2.0, max_contraction_factor=0.5):
    """
    Optimize circle sizes based on the percentage of black pixels within each circle.
    
    Args:
        circles: Array of circles from Hough detection [(x, y, radius), ...]
        original_image: Original grayscale image
        target_black_percentage: Target percentage of black pixels (default 92%)
        max_expansion_factor: Maximum expansion factor (default 2.0x)
        max_contraction_factor: Maximum contraction factor (default 0.5x)
    
    Returns:
        optimized_circles: Array of optimized circles
        debug_info: Dictionary with optimization details for visualization
    """
    if circles is None or len(circles) == 0:
        return None, {}
    
    optimized_circles = []
    debug_info = {
        'original_circles': circles.copy(),
        'optimization_steps': [],
        'final_percentages': []
    }
    
    # Convert to grayscale if needed
    if len(original_image.shape) == 3:
        gray_img = cv2.cvtColor(original_image, cv2.COLOR_BGR2GRAY)
    else:
        gray_img = original_image
    
    height, width = gray_img.shape
    
    for i, (x, y, original_radius) in enumerate(circles):
        print(f"Optimizing circle {i+1}/{len(circles)} at ({x}, {y}) with radius {original_radius}")
        
        # Test different radius values
        test_radii = []
        black_percentages = []
        
        # Generate test radii (contraction and expansion)
        base_radius = int(original_radius)
        best_radius = base_radius
        best_percentage = 0
        found_target = False
        
        # Test expansion first (larger radii)
        for factor in np.arange(1.0, max_expansion_factor + 0.1, 0.1):
            test_radius = int(base_radius * factor)
            if test_radius < 3:  # Minimum radius
                continue
                
            # Calculate black pixel percentage for this radius using NumPy masks (fast!)
            percentage, total_pixels = calculate_black_percentage_numpy(gray_img, x, y, test_radius)
            
            if total_pixels > 0:
                test_radii.append(test_radius)
                black_percentages.append(percentage)
                print(f"  Radius {test_radius}: {percentage:.1f}% black")
                
                # Check if we've found a good percentage
                if percentage >= target_black_percentage:
                    if not found_target or abs(percentage - target_black_percentage) < abs(best_percentage - target_black_percentage):
                        best_radius = test_radius
                        best_percentage = percentage
                        found_target = True
                elif percentage < best_percentage and not found_target:
                    # If we haven't found target yet, keep the best so far
                    best_radius = test_radius
                    best_percentage = percentage
                
                # Early stopping: if we found target and percentage starts dropping significantly
                if found_target and percentage < target_black_percentage - 5:
                    print(f"  Early stopping expansion at radius {test_radius} (percentage dropped to {percentage:.1f}%)")
                    break
        
        # Add the optimized circle and debug info
        optimized_circles.append([x, y, best_radius])
        debug_info['optimization_steps'].append({
            'circle_id': i,
            'original_radius': original_radius,
            'optimized_radius': best_radius,
            'test_radii': test_radii,
            'black_percentages': black_percentages,
            'best_percentage': best_percentage
        })
        debug_info['final_percentages'].append(best_percentage)
        
        print(f"  Optimized: {original_radius} → {best_radius} ({best_percentage:.1f}% black)")
        
        # If we didn't find target with expansion, try contraction
        if not found_target:
            print(f"  No target found with expansion, trying contraction...")
            for factor in np.arange(0.9, max_contraction_factor - 0.1, -0.1):
                test_radius = int(base_radius * factor)
                if test_radius < 3:  # Minimum radius
                    continue
                    
                # Calculate black pixel percentage for this radius using NumPy masks (fast!)
                percentage, total_pixels = calculate_black_percentage_numpy(gray_img, x, y, test_radius)
                
                if total_pixels > 0:
                    test_radii.append(test_radius)
                    black_percentages.append(percentage)
                    print(f"  Radius {test_radius}: {percentage:.1f}% black")
                    
                    # Check if we've found a good percentage
                    if percentage >= target_black_percentage:
                        if abs(percentage - target_black_percentage) < abs(best_percentage - target_black_percentage):
                            best_radius = test_radius
                            best_percentage = percentage
                            found_target = True
                    elif percentage > best_percentage:
                        # Keep the best percentage so far
                        best_radius = test_radius
                        best_percentage = percentage
                    
                    # Early stopping: if percentage drops significantly below target
                    if found_target and percentage < target_black_percentage - 5:
                        print(f"  Early stopping contraction at radius {test_radius} (percentage dropped to {percentage:.1f}%)")
                        break
            
            # Update the optimized circle with contraction results
            optimized_circles[-1] = [x, y, best_radius]
            debug_info['optimization_steps'][-1]['optimized_radius'] = best_radius
            debug_info['optimization_steps'][-1]['best_percentage'] = best_percentage
            debug_info['final_percentages'][-1] = best_percentage
            
            print(f"  Updated with contraction: {original_radius} → {best_radius} ({best_percentage:.1f}% black)")
    
    return np.array(optimized_circles), debug_info

def optimize_circle_position(circle, original_image, search_radius=240, step_size=3, target_black_percentage=98):
    """
    Optimize circle position by moving it around to find the best black pixel percentage.
    
    Args:
        circle: [x, y, radius] - original circle
        original_image: Grayscale image
        search_radius: How far to search from original position
        step_size: Step size for movement (pixels)
        target_black_percentage: Target percentage of black pixels
    
    Returns:
        optimized_circle: [x, y, radius] - circle with best position
        best_percentage: Best black pixel percentage found
        movement_info: Dictionary with movement details
    """
    x, y, r = circle
    
    # Convert to grayscale if needed
    if len(original_image.shape) == 3:
        gray_img = cv2.cvtColor(original_image, cv2.COLOR_BGR2GRAY)
    else:
        gray_img = original_image
    
    height, width = gray_img.shape
    
    def calculate_black_percentage(cx, cy, cr):
        """Calculate black pixel percentage for a circle at given position using NumPy masks"""
        percentage, _ = calculate_black_percentage_numpy(gray_img, cx, cy, cr)
        return percentage
    
    # Start with original position
    best_x, best_y = x, y
    best_percentage = calculate_black_percentage(x, y, r)
    original_percentage = best_percentage
    
    print(f"  Original position ({x:.1f}, {y:.1f}): {best_percentage:.1f}% black")
    
    # If already above target, no need to move
    if best_percentage >= target_black_percentage:
        print(f"  Already above target ({target_black_percentage}%), keeping original position")
        return [best_x, best_y, r], best_percentage, {
            'original_position': [x, y],
            'best_position': [best_x, best_y],
            'movement_distance': 0,
            'improvement': 0,
            'positions_tested': 1
        }
    
    # Step 1: Coarse grid search to find promising region (avoid local maxima)
    print(f"  Step 1: Coarse grid search (step_size={step_size*3})...")
    coarse_step = step_size * 3  # Coarse grid: 3x larger steps
    coarse_positions_tested = 0
    coarse_best_x, coarse_best_y = x, y
    coarse_best_percentage = best_percentage
    
    for dy in range(-search_radius, search_radius + 1, coarse_step):
        for dx in range(-search_radius, search_radius + 1, coarse_step):
            test_x, test_y = x + dx, y + dy
            
            # Check if position is within image bounds
            if test_x - r >= 0 and test_x + r < width and test_y - r >= 0 and test_y + r < height:
                percentage = calculate_black_percentage(test_x, test_y, r)
                coarse_positions_tested += 1
                
                # Update best if this is better
                if percentage > coarse_best_percentage:
                    coarse_best_percentage = percentage
                    coarse_best_x, coarse_best_y = test_x, test_y
    
    print(f"  Coarse search: {coarse_positions_tested} positions tested, best: ({coarse_best_x:.1f}, {coarse_best_y:.1f}) with {coarse_best_percentage:.1f}%")
    
    # Step 2: Gradient descent from best coarse position
    print(f"  Step 2: Gradient descent refinement...")
    current_x, current_y = coarse_best_x, coarse_best_y
    current_percentage = coarse_best_percentage
    learning_rate = max(2.0, step_size)  # Adaptive learning rate
    max_iterations = 50
    gradient_step = 1.0  # Step size for gradient calculation
    convergence_threshold = 0.1  # Stop when gradient magnitude is below this
    
    positions_tested = coarse_positions_tested
    gradient_iterations = 0
    
    for iteration in range(max_iterations):
        # Calculate gradient numerically using central differences
        grad_x = 0.0
        grad_y = 0.0
        
        # Gradient in x direction (central difference)
        if current_x + gradient_step < width - r and current_x - gradient_step >= r:
            right_percentage = calculate_black_percentage(current_x + gradient_step, current_y, r)
            left_percentage = calculate_black_percentage(current_x - gradient_step, current_y, r)
            grad_x = (right_percentage - left_percentage) / (2 * gradient_step)
        elif current_x + gradient_step < width - r:
            # Forward difference if can't go left
            right_percentage = calculate_black_percentage(current_x + gradient_step, current_y, r)
            grad_x = (right_percentage - current_percentage) / gradient_step
        elif current_x - gradient_step >= r:
            # Backward difference if can't go right
            left_percentage = calculate_black_percentage(current_x - gradient_step, current_y, r)
            grad_x = (current_percentage - left_percentage) / gradient_step
        
        # Gradient in y direction (central difference)
        if current_y + gradient_step < height - r and current_y - gradient_step >= r:
            down_percentage = calculate_black_percentage(current_x, current_y + gradient_step, r)
            up_percentage = calculate_black_percentage(current_x, current_y - gradient_step, r)
            grad_y = (down_percentage - up_percentage) / (2 * gradient_step)
        elif current_y + gradient_step < height - r:
            # Forward difference if can't go up
            down_percentage = calculate_black_percentage(current_x, current_y + gradient_step, r)
            grad_y = (down_percentage - current_percentage) / gradient_step
        elif current_y - gradient_step >= r:
            # Backward difference if can't go down
            up_percentage = calculate_black_percentage(current_x, current_y - gradient_step, r)
            grad_y = (current_percentage - up_percentage) / gradient_step
        
        # Calculate gradient magnitude
        gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)
        
        # Check for convergence
        if gradient_magnitude < convergence_threshold:
            print(f"  Converged at iteration {iteration + 1} (gradient magnitude: {gradient_magnitude:.3f})")
            break
        
        # Move in direction of gradient (uphill)
        new_x = current_x + learning_rate * grad_x
        new_y = current_y + learning_rate * grad_y
        
        # Keep within image bounds
        new_x = np.clip(new_x, r, width - r)
        new_y = np.clip(new_y, r, height - r)
        
        # Calculate new percentage
        new_percentage = calculate_black_percentage(new_x, new_y, r)
        positions_tested += 1
        gradient_iterations += 1
        
        # Update if better
        if new_percentage > current_percentage:
            current_x, current_y = new_x, new_y
            current_percentage = new_percentage
        else:
            # If not improving, reduce learning rate
            learning_rate *= 0.8
            if learning_rate < 0.5:
                break  # Learning rate too small, converged
    
    # Use best position found
    best_x, best_y = current_x, current_y
    best_percentage = current_percentage
    best_positions = [[best_x, best_y]]
    
    # Calculate movement distance
    movement_distance = np.sqrt((best_x - x)**2 + (best_y - y)**2)
    improvement = best_percentage - original_percentage
    
    print(f"  Best position ({best_x:.1f}, {best_y:.1f}): {best_percentage:.1f}% black")
    print(f"  Movement: {movement_distance:.1f} pixels, Improvement: +{improvement:.1f}%")
    print(f"  Total positions tested: {positions_tested} (coarse: {coarse_positions_tested}, gradient: {gradient_iterations})")
    
    return [best_x, best_y, r], best_percentage, {
        'original_position': [x, y],
        'best_position': [best_x, best_y],
        'movement_distance': movement_distance,
        'improvement': improvement,
        'positions_tested': positions_tested,
        'coarse_positions_tested': coarse_positions_tested,
        'gradient_iterations': gradient_iterations,
        'best_positions': best_positions
    }

def create_optimization_visualization(original_image, circles, optimized_circles, debug_info):
    """
    Create a comprehensive visualization of the circle optimization process.
    
    Returns:
        debug_images: Dictionary with visualization images
    """
    if len(debug_info) == 0:
        return {}
    
    # Convert to RGB for visualization
    if len(original_image.shape) == 3:
        rgb_img = cv2.cvtColor(original_image, cv2.COLOR_BGR2RGB)
    else:
        rgb_img = cv2.cvtColor(original_image, cv2.COLOR_GRAY2RGB)
    
    debug_images = {}
    
    # 1. Original circles
    original_viz = rgb_img.copy()
    if circles is not None:
        for (x, y, r) in circles:
            cv2.circle(original_viz, (int(x), int(y)), int(r), (255, 0, 0), 2)  # Blue
            cv2.circle(original_viz, (int(x), int(y)), 2, (0, 255, 0), 3)  # Green center
    debug_images['original_circles'] = original_viz
    
    # 2. Optimized circles
    optimized_viz = rgb_img.copy()
    if optimized_circles is not None:
        for (x, y, r) in optimized_circles:
            cv2.circle(optimized_viz, (int(x), int(y)), int(r), (0, 0, 255), 2)  # Red
            cv2.circle(optimized_viz, (int(x), int(y)), 2, (0, 255, 0), 3)  # Green center
    debug_images['optimized_circles'] = optimized_viz
    
    # 3. Comparison overlay
    comparison_viz = rgb_img.copy()
    if circles is not None:
        for (x, y, r) in circles:
            cv2.circle(comparison_viz, (int(x), int(y)), int(r), (255, 0, 0), 2)  # Blue (original)
    if optimized_circles is not None:
        for (x, y, r) in optimized_circles:
            cv2.circle(comparison_viz, (int(x), int(y)), int(r), (0, 0, 255), 2)  # Red (optimized)
    debug_images['comparison_overlay'] = comparison_viz
    
    # 4. Radius change visualization
    radius_changes = rgb_img.copy()
    if circles is not None and optimized_circles is not None:
        for i, ((x1, y1, r1), (x2, y2, r2)) in enumerate(zip(circles, optimized_circles)):
            change_factor = r2 / r1
            if change_factor > 1.1:  # Expanded
                color = (0, 255, 0)  # Green
            elif change_factor < 0.9:  # Contracted
                color = (255, 0, 0)  # Blue
            else:  # No significant change
                color = (128, 128, 128)  # Gray
            
            cv2.circle(radius_changes, (int(x2), int(y2)), int(r2), color, 2)
            cv2.putText(radius_changes, f"{change_factor:.1f}x", (int(x2)+5, int(y2)-5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    debug_images['radius_changes'] = radius_changes
    
    # 5. Black percentage heatmap
    percentage_viz = rgb_img.copy()
    if optimized_circles is not None and 'final_percentages' in debug_info:
        for i, ((x, y, r), percentage) in enumerate(zip(optimized_circles, debug_info['final_percentages'])):
            # Color based on percentage (green=good, red=bad)
            if percentage >= 90:
                color = (0, 255, 0)  # Green
            elif percentage >= 80:
                color = (0, 255, 255)  # Yellow
            else:
                color = (0, 0, 255)  # Red
            
            cv2.circle(percentage_viz, (int(x), int(y)), int(r), color, 2)
            cv2.putText(percentage_viz, f"{percentage:.0f}%", (int(x)+5, int(y)+5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    debug_images['percentage_heatmap'] = percentage_viz
    
    # 6. Optimization curves (for first few circles)
    if len(debug_info['optimization_steps']) > 0:
        # Create a plot showing optimization curves
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 2, figsize=(10, 8))
        fig.suptitle('Circle Optimization Analysis', fontsize=14)
        
        # Plot 1: Radius vs Percentage for first circle
        if len(debug_info['optimization_steps']) > 0:
            step = debug_info['optimization_steps'][0]
            axes[0,0].plot(step['test_radii'], step['black_percentages'], 'b-o')
            axes[0,0].axhline(y=92, color='r', linestyle='--', label='Target (92%)')
            axes[0,0].set_title(f'Circle 1: Radius vs Black %')
            axes[0,0].set_xlabel('Radius (pixels)')
            axes[0,0].set_ylabel('Black Pixels (%)')
            axes[0,0].legend()
            axes[0,0].grid(True)
        
        # Plot 2: Radius change distribution (ALL circles)
        if len(debug_info['optimization_steps']) > 0:
            changes = []
            for step in debug_info['optimization_steps']:
                change = step['optimized_radius'] / step['original_radius']
                changes.append(change)
            
            axes[0,1].hist(changes, bins=min(10, len(changes)), color='skyblue', edgecolor='black')
            axes[0,1].axvline(x=1, color='r', linestyle='--', label='No Change')
            axes[0,1].set_title(f'Radius Change Distribution ({len(changes)} circles)')
            axes[0,1].set_xlabel('Change Factor')
            axes[0,1].set_ylabel('Number of Circles')
            axes[0,1].legend()
            axes[0,1].grid(True)
        
        # Plot 3: Final percentages distribution (ALL circles)
        if 'final_percentages' in debug_info:
            axes[1,0].hist(debug_info['final_percentages'], bins=min(10, len(debug_info['final_percentages'])), color='lightgreen', edgecolor='black')
            axes[1,0].axvline(x=92, color='r', linestyle='--', label='Target (92%)')
            axes[1,0].set_title(f'Final Black Percentage Distribution ({len(debug_info["final_percentages"])} circles)')
            axes[1,0].set_xlabel('Black Pixels (%)')
            axes[1,0].set_ylabel('Number of Circles')
            axes[1,0].legend()
            axes[1,0].grid(True)
        
        # Plot 4: Before vs After radius comparison (ALL circles)
        if len(debug_info['optimization_steps']) > 0:
            original_radii = [step['original_radius'] for step in debug_info['optimization_steps']]
            optimized_radii = [step['optimized_radius'] for step in debug_info['optimization_steps']]
            
            axes[1,1].scatter(original_radii, optimized_radii, alpha=0.7)
            axes[1,1].plot([0, max(original_radii)], [0, max(original_radii)], 'r--', label='No Change')
            axes[1,1].set_title(f'Before vs After Radius ({len(original_radii)} circles)')
            axes[1,1].set_xlabel('Original Radius')
            axes[1,1].set_ylabel('Optimized Radius')
            axes[1,1].legend()
            axes[1,1].grid(True)
        
        plt.tight_layout()
        
        # Convert plot to image
        import io
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        
        # Read the image
        plot_img = cv2.imdecode(np.frombuffer(buf.getvalue(), np.uint8), cv2.IMREAD_COLOR)
        plot_img = cv2.cvtColor(plot_img, cv2.COLOR_BGR2RGB)
        debug_images['optimization_analysis'] = plot_img
        
        plt.close()
    
    # Add fallback plots if no optimization steps available
    if len(debug_info.get('optimization_steps', [])) == 0:
        # Create basic plots even without optimization steps
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 2, figsize=(10, 8))
        fig.suptitle('Circle Optimization Analysis', fontsize=14)
        
        # Plot 1: Radius change distribution
        if circles is not None and optimized_circles is not None:
            changes = []
            for orig_circle, opt_circle in zip(circles, optimized_circles):
                change = opt_circle[2] / orig_circle[2]
                changes.append(change)
            
            axes[0,0].hist(changes, bins=min(10, len(changes)), color='skyblue', edgecolor='black')
            axes[0,0].axvline(x=1, color='r', linestyle='--', label='No Change')
            axes[0,0].set_title(f'Radius Change Distribution ({len(changes)} circles)')
            axes[0,0].set_xlabel('Change Factor')
            axes[0,0].set_ylabel('Number of Circles')
            axes[0,0].legend()
            axes[0,0].grid(True)
        
        # Plot 2: Final percentages distribution
        if 'final_percentages' in debug_info:
            axes[0,1].hist(debug_info['final_percentages'], bins=min(10, len(debug_info['final_percentages'])), color='lightgreen', edgecolor='black')
            axes[0,1].axvline(x=92, color='r', linestyle='--', label='Target (92%)')
            axes[0,1].set_title(f'Final Black Percentage Distribution ({len(debug_info["final_percentages"])} circles)')
            axes[0,1].set_xlabel('Black Pixels (%)')
            axes[0,1].set_ylabel('Number of Circles')
            axes[0,1].legend()
            axes[0,1].grid(True)
        
        # Plot 3: Before vs After radius comparison
        if circles is not None and optimized_circles is not None:
            original_radii = [circle[2] for circle in circles]
            optimized_radii = [circle[2] for circle in optimized_circles]
            
            axes[1,0].scatter(original_radii, optimized_radii, alpha=0.7)
            axes[1,0].plot([0, max(original_radii)], [0, max(original_radii)], 'r--', label='No Change')
            axes[1,0].set_title(f'Before vs After Radius ({len(original_radii)} circles)')
            axes[1,0].set_xlabel('Original Radius')
            axes[1,0].set_ylabel('Optimized Radius')
            axes[1,0].legend()
            axes[1,0].grid(True)
        
        # Plot 4: Radius change percentage
        if circles is not None and optimized_circles is not None:
            changes_pct = []
            for orig_circle, opt_circle in zip(circles, optimized_circles):
                change_pct = ((opt_circle[2] - orig_circle[2]) / orig_circle[2]) * 100
                changes_pct.append(change_pct)
            
            axes[1,1].hist(changes_pct, bins=min(10, len(changes_pct)), color='orange', edgecolor='black')
            axes[1,1].axvline(x=0, color='r', linestyle='--', label='No Change')
            axes[1,1].set_title(f'Radius Change Percentage ({len(changes_pct)} circles)')
            axes[1,1].set_xlabel('Change (%)')
            axes[1,1].set_ylabel('Number of Circles')
            axes[1,1].legend()
            axes[1,1].grid(True)
        
        plt.tight_layout()
        
        # Convert plot to image
        import io
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        
        # Read the image
        plot_img = cv2.imdecode(np.frombuffer(buf.getvalue(), np.uint8), cv2.IMREAD_COLOR)
        plot_img = cv2.cvtColor(plot_img, cv2.COLOR_BGR2RGB)
        debug_images['optimization_analysis'] = plot_img
        
        plt.close()
    
    return debug_images

def create_position_optimization_visualization(original_image, original_circles, size_optimized_circles, optimized_circles, position_data):
    """
    Create a side-by-side visualization showing before/after circle positions.
    
    Args:
        original_image: Original image
        original_circles: Circles before position optimization
        optimized_circles: Circles after position optimization
        position_data: List of position optimization data
    
    Returns:
        comparison_viz: Side-by-side image showing before/after
    """
    # Convert to RGB for visualization
    if len(original_image.shape) == 3:
        rgb_img = cv2.cvtColor(original_image, cv2.COLOR_BGR2RGB)
    else:
        rgb_img = cv2.cvtColor(original_image, cv2.COLOR_GRAY2RGB)
    
    # Create side-by-side comparison
    height, width = rgb_img.shape[:2]  # Get only height and width, ignore channels
    comparison_viz = np.zeros((height, width * 2, 3), dtype=np.uint8)
    
    # Left side: All circles after size optimization (before position optimization)
    left_side = rgb_img.copy()
    print("\nDEBUG: Drawing left side circles (size-optimized):")
    for i, (x, y, r) in enumerate(size_optimized_circles):
        print(f"  Circle {i+1}: ({x:.1f}, {y:.1f}, r={r:.1f})")
        cv2.circle(left_side, (int(x), int(y)), int(r), (0, 255, 0), 1)  # Thinner green circles
        cv2.circle(left_side, (int(x), int(y)), 2, (0, 255, 0), -1)  # Smaller green centers
        cv2.putText(left_side, f"{i+1}", (int(x)-5, int(y)-5), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    # Right side: All final circles with red highlighting for moved ones
    right_side = rgb_img.copy()
    moved_count = 0
    
    for i, (orig_circle, opt_circle, pos_info) in enumerate(zip(original_circles, optimized_circles, position_data)):
        orig_x, orig_y, orig_r = orig_circle
        opt_x, opt_y, opt_r = opt_circle
        movement_distance = pos_info['movement_distance']
        
        # Debug: Print actual coordinates
        print(f"Circle {i+1}: Original ({orig_x:.1f}, {orig_y:.1f}) -> Final ({opt_x:.1f}, {opt_y:.1f}) = {movement_distance:.1f} pixels")
        
        if movement_distance > 0:
            # Circle moved - draw in red with arrow
            cv2.circle(right_side, (int(opt_x), int(opt_y)), int(opt_r), (255, 0, 0), 1)  # Thinner red circle
            cv2.circle(right_side, (int(opt_x), int(opt_y)), 2, (255, 0, 0), -1)  # Smaller red center
            
            # Draw movement arrow (thinner and more visible)
            # Start arrow from outside the original circle
            start_x = int(orig_x + (orig_x - opt_x) * 0.3)  # Start 30% towards original from center
            start_y = int(orig_y + (orig_y - opt_y) * 0.3)
            
            cv2.arrowedLine(right_side, 
                           (start_x, start_y), 
                           (int(opt_x), int(opt_y)), 
                           (255, 255, 0), 4, tipLength=0.6)  # Thinner yellow arrow
            
            # Add movement distance
            cv2.putText(right_side, f"{movement_distance:.1f}px", (int(opt_x)+5, int(opt_y)-5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            moved_count += 1
        else:
            # Circle didn't move - draw in green
            cv2.circle(right_side, (int(opt_x), int(opt_y)), int(opt_r), (0, 255, 0), 1)  # Thinner green circle
            cv2.circle(right_side, (int(opt_x), int(opt_y)), 2, (0, 255, 0), -1)  # Smaller green center
        
        # Add circle number
        cv2.putText(right_side, f"{i+1}", (int(opt_x)-5, int(opt_y)-5), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    # Combine left and right sides
    comparison_viz[:, :width] = left_side
    comparison_viz[:, width:] = right_side
    
    # Add labels
    cv2.putText(comparison_viz, "BEFORE: All Original Circles", (10, 30), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(comparison_viz, "AFTER: Red = Moved, Green = Stationary", (width + 10, 30), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    
    # Add legend
    legend_y = 70
    cv2.putText(comparison_viz, "Green: Original/Stationary", (10, legend_y), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.putText(comparison_viz, "Red: Moved Circles", (10, legend_y+25), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
    cv2.putText(comparison_viz, "Yellow Arrow: Movement Direction", (10, legend_y+50), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
    
    # Add statistics
    stats_y = legend_y + 85
    cv2.putText(comparison_viz, f"Circles Moved: {moved_count}/{len(original_circles)}", (10, stats_y), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    return comparison_viz

# ==== CONFIGURATION ====
# Watershed parameters for better droplet separation
WATERSHED_DISTANCE_THRESHOLD = 0.25      # Lower threshold to find more centers
WATERSHED_DILATION_ITERATIONS = 2         # More dilation to separate overlapping droplets
WATERSHED_DISTANCE_KERNEL = 3            # Smaller kernel for more precise distance calculation

# Connected component filtering
MIN_CONNECTED_COMPONENT_AREA = 50        # Minimum area for connected component markers (prevents tiny spurious markers)

# Droplet detection parameters
MIN_DROPLET_AREA = 220                  # Minimum droplet area in pixels (filters out tiny spiky regions)
SMALL_DROPLET_MAX_AREA = 4000            # Allow larger droplets in Canny detection (scaled for 1620x1080)

# Note: Canny thresholds are now passed as parameters to process_image()
# (canny_thresh1 and canny_thresh2) for better flexibility

# ==== MAIN EXECUTION (only runs when script is executed directly) ====
if __name__ == "__main__":
    # Add src directory to path for imports
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config_loader import get_imaging_config
    
    # ==== ADJUSTABLE PARAMETERS FOR DIRECT EXECUTION ====
    # Use config defaults or command line argument
    config = get_imaging_config()
    if len(sys.argv) > 1:
        IMAGE_PATH = sys.argv[1]
    else:
        default_input_dir = config.get('default_input_dir', '/Volumes/LaCie/Phantom/Flashed_Output')
        default_input_file = config.get('default_input_file', 'flashed_output.tiff')
        IMAGE_PATH = os.path.join(default_input_dir, default_input_file)
    
    # Use config for output directory, fallback to local data directory
    try:
        output_root = config.get('output_root', None)
        if output_root:
            SAVE_DIR = os.path.join(output_root, "Expansion_Detection_Tests", time.strftime("%m_%d_%H_%M_%S"))
        else:
            SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'sample_output')
    except:
        SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'sample_output')
    os.makedirs(SAVE_DIR, exist_ok=True)
    ANNOTATED_IMAGE_PATH = f'{SAVE_DIR}/manual_annotated_droplets_combined.png'
    CSV_PATH = f'{SAVE_DIR}/manual_droplet_sizes_combined.csv'
    
    # Process the image (pass None so it doesn't save internally, we'll save manually)
    result = process_image(IMAGE_PATH, None)
    
    # Save the results locally (for when running script directly)
    cv2.imwrite(ANNOTATED_IMAGE_PATH, cv2.cvtColor(result['final_image'], cv2.COLOR_RGB2BGR))
    print(f"Annotated image saved to {ANNOTATED_IMAGE_PATH}")

    # Save CSV
    df = pd.DataFrame(result['optimization_data'])
    df.to_csv(CSV_PATH, index=False)
    print(f"Droplet size data saved to {CSV_PATH}")

    # ==== DISPLAY ANNOTATED IMAGE ====
    plt.figure(figsize=(8, 8))
    plt.title('Final Optimized Droplets')
    plt.imshow(result['final_image'])
    plt.axis('off')
    plt.show()

    # ==== HISTOGRAM OF DROPLET SIZES ====
    if len(df) > 0:
        plt.figure(figsize=(8, 4))
        plt.hist(df['optimized_diameter_px'], bins=20, color='skyblue', edgecolor='black')
        plt.title('Histogram of Optimized Droplet Diameters (pixels)')
        plt.xlabel('Diameter (pixels)')
        plt.ylabel('Count')
        plt.show()
        
        # Show detection method breakdown
        canny_count = result['circle_sources'].count('Canny')
        watershed_count = result['circle_sources'].count('Watershed')
        
        plt.figure(figsize=(6, 6))
        plt.pie([canny_count, watershed_count], labels=['Canny', 'Watershed'], 
               colors=['lightgreen', 'lightcoral'], autopct='%1.1f%%')
        plt.title('Detection Method Breakdown')
        plt.show()
        
        # Show radius change distribution
        plt.figure(figsize=(8, 4))
        plt.hist(df['radius_change_percent'], bins=20, color='orange', edgecolor='black')
        plt.title('Distribution of Radius Changes (%)')
        plt.xlabel('Radius Change (%)')
        plt.ylabel('Count')
        plt.axvline(x=0, color='red', linestyle='--', label='No Change')
        plt.legend()
        plt.show()
    else:
        print("No droplets detected with the current parameters.")

    # ==== CREATE COMPREHENSIVE VISUALIZATION ====
    print("Creating comprehensive visualization...")
    
    # Create a figure to show the complete pipeline
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('Complete Droplet Detection & Optimization Pipeline', fontsize=14)
    
    # Row 1: Detection Methods
    # Original image with Canny circles (before optimization)
    canny_viz = cv2.imread(IMAGE_PATH)
    canny_viz = cv2.cvtColor(canny_viz, cv2.COLOR_BGR2RGB)
    for circle in result['canny_circles']:
        x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
        cv2.circle(canny_viz, (x, y), r, (0, 255, 0), 2)  # Green for Canny
    axes[0,0].imshow(canny_viz)
    axes[0,0].set_title(f'Canny Detection ({len(result["canny_circles"])} circles)')
    axes[0,0].axis('off')
    
    # Watershed circles (before optimization)
    watershed_viz = cv2.imread(IMAGE_PATH)
    watershed_viz = cv2.cvtColor(watershed_viz, cv2.COLOR_BGR2RGB)
    for circle in result['watershed_circles']:
        x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
        cv2.circle(watershed_viz, (x, y), r, (255, 0, 0), 2)  # Blue for Watershed
    axes[0,1].imshow(watershed_viz)
    axes[0,1].set_title(f'Watershed Detection ({len(result["watershed_circles"])} circles)')
    axes[0,1].axis('off')
    
    # Combined detection (before optimization)
    combined_viz = cv2.imread(IMAGE_PATH)
    combined_viz = cv2.cvtColor(combined_viz, cv2.COLOR_BGR2RGB)
    
    # Draw Canny circles first
    for circle in result['canny_circles']:
        x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
        cv2.circle(combined_viz, (x, y), r, (0, 255, 0), 2)  # Green for Canny
    
    # Draw Watershed circles (avoiding duplicates)
    for watershed_circle in result['watershed_circles']:
        # Check if this circle is too close to existing Canny circles
        is_duplicate = False
        for canny_circle in result['canny_circles']:
            dx = watershed_circle[0] - canny_circle[0]
            dy = watershed_circle[1] - canny_circle[1]
            distance = np.sqrt(dx*dx + dy*dy)
            if distance < 20:  # If centers are within 20 pixels, consider duplicate
                is_duplicate = True
                break
        
        if not is_duplicate:
            x, y, r = int(watershed_circle[0]), int(watershed_circle[1]), int(watershed_circle[2])
            cv2.circle(combined_viz, (x, y), r, (255, 0, 0), 2)  # Blue for Watershed
    
    axes[0,2].imshow(combined_viz)
    axes[0,2].set_title(f'Combined Detection (Before Optimization)')
    axes[0,2].axis('off')
    
    # Row 2: Analysis
    # Final optimized result
    axes[1,0].imshow(result['final_image'])
    axes[1,0].set_title('Final Optimized Result')
    axes[1,0].axis('off')
    
    # Diameter histogram
    if len(df) > 0:
        axes[1,1].hist(df['optimized_diameter_px'], bins=20, color='skyblue', edgecolor='black')
        axes[1,1].set_title('Optimized Diameter Distribution')
        axes[1,1].set_xlabel('Diameter (pixels)')
        axes[1,1].set_ylabel('Count')
    else:
        axes[1,1].text(0.5, 0.5, 'No droplets detected', ha='center', va='center', transform=axes[1,1].transAxes)
        axes[1,1].set_title('Diameter Distribution')
    
    # Radius change histogram
    if len(df) > 0:
        axes[1,2].hist(df['radius_change_percent'], bins=20, color='orange', edgecolor='black')
        axes[1,2].set_title('Radius Change Distribution')
        axes[1,2].set_xlabel('Radius Change (%)')
        axes[1,2].set_ylabel('Count')
        axes[1,2].axvline(x=0, color='red', linestyle='--')
    else:
        axes[1,2].text(0.5, 0.5, 'No optimization data', ha='center', va='center', transform=axes[1,2].transAxes)
        axes[1,2].set_title('Radius Change Distribution')
    
    plt.tight_layout()
    
    # Save the comprehensive visualization (reuse SAVE_DIR from earlier)
    filename = f"COMPLETE_PIPELINE.png"
    save_path = os.path.join(SAVE_DIR, filename)
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"Complete pipeline visualization saved to: {save_path}")
    
    plt.show()
    
    # ==== OPTIMIZATION VISUALIZATION ====
    print("Creating optimization visualization...")
    
    # Create optimization visualization
    opt_debug_images = create_optimization_visualization(
        cv2.imread(IMAGE_PATH),
        result['all_circles_before_optimization'],  # Use original circles before optimization
        result['optimized_circles'],  # Use optimized circles
        {'optimization_steps': [], 'final_percentages': [d['final_black_percentage'] for d in result['optimization_data']]}
    )
    
    if len(opt_debug_images) > 0:
        # Create a new figure for optimization visualization
        fig_opt, axes_opt = plt.subplots(2, 3, figsize=(15, 10))
        fig_opt.suptitle('Circle Size Optimization Analysis', fontsize=14)
        
        # Row 1: Visualizations
        axes_opt[0,0].imshow(opt_debug_images['original_circles'])
        axes_opt[0,0].set_title('Original Circles')
        axes_opt[0,0].axis('off')
        
        axes_opt[0,1].imshow(opt_debug_images['optimized_circles'])
        axes_opt[0,1].set_title('Optimized Circles')
        axes_opt[0,1].axis('off')
        
        axes_opt[0,2].imshow(opt_debug_images['comparison_overlay'])
        axes_opt[0,2].set_title('Comparison Overlay')
        axes_opt[0,2].axis('off')
        
        # Row 2: Analysis
        axes_opt[1,0].imshow(opt_debug_images['radius_changes'])
        axes_opt[1,0].set_title('Radius Changes')
        axes_opt[1,0].axis('off')
        
        axes_opt[1,1].imshow(opt_debug_images['percentage_heatmap'])
        axes_opt[1,1].set_title('Black Percentage Heatmap')
        axes_opt[1,1].axis('off')
        
        if 'optimization_analysis' in opt_debug_images:
            axes_opt[1,2].imshow(opt_debug_images['optimization_analysis'])
            axes_opt[1,2].set_title('Optimization Analysis')
            axes_opt[1,2].axis('off')
        else:
            axes_opt[1,2].text(0.5, 0.5, 'Analysis plots\n(see console output)', 
                             ha='center', va='center', transform=axes_opt[1,2].transAxes)
            axes_opt[1,2].set_title('Optimization Analysis')
        
        plt.tight_layout()
        
        # Save optimization visualization
        opt_filename = f"OPTIMIZATION_ANALYSIS.png"
        opt_save_path = os.path.join(SAVE_DIR, opt_filename)
        plt.savefig(opt_save_path, dpi=300, bbox_inches='tight')
        print(f"Optimization visualization saved to: {opt_save_path}")
        
        plt.show()
    else:
        print("[WARNING] No optimization visualization created")
    
    # ==== POSITION OPTIMIZATION VISUALIZATION ====
    print("Creating position optimization visualization...")
    
    # Create position movement visualization
    position_movement_viz = create_position_optimization_visualization(
        cv2.imread(IMAGE_PATH),
        result['all_circles_before_optimization'],  # TRUE original circles (before any optimization)
        result['size_optimized_circles'],  # Circles after size optimization (before position)
        result['optimized_circles'],  # Final circles (after size + position optimization)
        result['position_optimization_data']
    )
    
    # Save position movement visualization
    position_filename = f"POSITION_MOVEMENT.png"
    position_save_path = os.path.join(SAVE_DIR, position_filename)
    cv2.imwrite(position_save_path, cv2.cvtColor(position_movement_viz, cv2.COLOR_RGB2BGR))
    print(f"Position movement visualization saved to: {position_save_path}")
    
    # Display position movement visualization
    plt.figure(figsize=(12, 8))
    plt.imshow(position_movement_viz)
    plt.title('Circle Position Optimization Movement')
    plt.axis('off')
    plt.show()
    
    # Create final optimized circles image with numbers
    final_circles_img = cv2.imread(IMAGE_PATH)
    final_circles_img = cv2.cvtColor(final_circles_img, cv2.COLOR_BGR2RGB)
    
    for i, (circle, data) in enumerate(zip(result['optimized_circles'], result['optimization_data'])):
        x, y, r = int(circle[0]), int(circle[1]), int(circle[2])
        color = (0, 255, 0) if data['detection_method'] == 'Canny' else (255, 0, 0)
        cv2.circle(final_circles_img, (x, y), r, color, 3)  # Colored circles
        cv2.circle(final_circles_img, (x, y), 2, (0, 255, 255), 3)  # Yellow centers
        # Add circle number
        cv2.putText(final_circles_img, str(i+1), (x-10, y-10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    # Save final optimized circles image
    final_img_filename = f"FINAL_OPTIMIZED_CIRCLES.png"
    final_img_path = os.path.join(SAVE_DIR, final_img_filename)
    cv2.imwrite(final_img_path, cv2.cvtColor(final_circles_img, cv2.COLOR_RGB2BGR))
    print(f"Final optimized circles image saved: {final_img_path}")
    
    # Print summary
    print(f"\nOptimization Summary:")
    print(f"  Total circles optimized: {len(result['optimization_data'])}")
    avg_change = df['radius_change_percent'].mean()
    print(f"  Average radius change: {avg_change:.1f}%")
    avg_percentage = df['final_black_percentage'].mean()
    print(f"  Average final black percentage: {avg_percentage:.1f}%")
    print(f"  Canny detection: {result['circle_sources'].count('Canny')} droplets")
    print(f"  Watershed detection: {result['circle_sources'].count('Watershed')} droplets")

# ==== END ==== 