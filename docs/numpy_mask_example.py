"""
Simple example demonstrating NumPy mask approach vs nested loops
Run this to see the performance difference!
"""
import numpy as np
import time

def slow_circle_pixels_loop(img, cx, cy, r):
    """Old way: Nested loops"""
    height, width = img.shape
    black_pixels = 0
    total_pixels = 0
    
    for dy in range(-int(r), int(r) + 1):
        for dx in range(-int(r), int(r) + 1):
            if dx*dx + dy*dy <= r*r:
                ny, nx = int(cy + dy), int(cx + dx)
                if 0 <= ny < height and 0 <= nx < width:
                    total_pixels += 1
                    if img[ny, nx] < 128:
                        black_pixels += 1
    
    return black_pixels, total_pixels

def fast_circle_pixels_mask(img, cx, cy, r):
    """New way: NumPy masks"""
    height, width = img.shape
    
    # Create coordinate grids
    y_coords, x_coords = np.ogrid[:height, :width]
    
    # Calculate distance squared from center for ALL pixels at once
    distances_squared = (x_coords - cx)**2 + (y_coords - cy)**2
    
    # Create boolean mask: True where pixel is inside circle
    circle_mask = distances_squared <= r**2
    
    # Extract pixels and count
    pixels_in_circle = img[circle_mask]
    black_pixels = np.sum(pixels_in_circle < 128)
    total_pixels = np.sum(circle_mask)
    
    return black_pixels, total_pixels

# Test with a sample image
print("Creating test image (500x500)...")
test_img = np.random.randint(0, 255, (500, 500), dtype=np.uint8)
cx, cy, r = 250, 250, 50  # Circle in center

# Test slow method
print("\nTesting SLOW method (nested loops)...")
start = time.time()
black1, total1 = slow_circle_pixels_loop(test_img, cx, cy, r)
time_slow = time.time() - start
print(f"  Result: {black1}/{total1} black pixels ({black1/total1*100:.1f}%)")
print(f"  Time: {time_slow*1000:.2f} ms")

# Test fast method
print("\nTesting FAST method (NumPy masks)...")
start = time.time()
black2, total2 = fast_circle_pixels_mask(test_img, cx, cy, r)
time_fast = time.time() - start
print(f"  Result: {black2}/{total2} black pixels ({black2/total2*100:.1f}%)")
print(f"  Time: {time_fast*1000:.2f} ms")

# Verify results match
assert black1 == black2, "Results don't match!"
assert total1 == total2, "Total pixels don't match!"

# Show speedup
speedup = time_slow / time_fast
print(f"\n{'='*50}")
print(f"SPEEDUP: {speedup:.1f}x faster!")
print(f"{'='*50}")

# Visualize the mask
print("\nVisualizing circle mask (50x50 crop around center):")
mask_y, mask_x = np.ogrid[200:300, 200:300]
distances = (mask_x - cx)**2 + (mask_y - cy)**2
mask = distances <= r**2

# Print ASCII visualization
for i in range(0, 100, 5):
    row = mask[i:i+5, :]
    line = ""
    for j in range(0, 100, 2):
        if mask[i, j]:
            line += "██"
        else:
            line += "  "
    print(line)

print("\n(██ = inside circle, spaces = outside)")

