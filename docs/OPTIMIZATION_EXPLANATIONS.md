# Optimization Techniques Explained

## 1. NumPy Mask Approach for Circle Pixel Sampling

### Current Approach (Slow - Nested Loops)

**What it does:**
```python
# For each test radius, iterate through every pixel
for dy in range(-test_radius, test_radius + 1):
    for dx in range(-test_radius, test_radius + 1):
        if dx*dx + dy*dy <= test_radius*test_radius:
            ny, nx = int(y + dy), int(x + dx)
            if 0 <= ny < height and 0 <= nx < width:
                total_pixels += 1
                if gray_img[ny, nx] < 128:
                    black_pixels += 1
```

**Visual Representation:**
```
Image (10x10 pixels):
┌─────────────────────────┐
│  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  │
│  .  .  .  O  .  .  .  .  │  ← Circle center at (5, 5)
│  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  │
└─────────────────────────┘

For radius=3, the code checks:
- dx=-3, dy=-3: Check if (-3)² + (-3)² ≤ 3² → 18 > 9 → SKIP
- dx=-2, dy=-2: Check if (-2)² + (-2)² ≤ 3² → 8 ≤ 9 → CHECK PIXEL
- dx=-1, dy=-1: Check if (-1)² + (-1)² ≤ 3² → 2 ≤ 9 → CHECK PIXEL
- ... (checks ~28 pixels for radius 3)
- dx=0, dy=0: Always included (center)
- ... (continues for all pixels in bounding box)

Total operations: For radius R, checks (2R+1)² pixels
For R=50: 10,201 pixel checks per circle per test radius!
```

**Problems:**
- Python loops are slow
- Checks pixels outside circle (wasteful)
- Repeats calculations
- For 10 circles × 20 test radii × 10,201 pixels = 2+ million operations

---

### NumPy Mask Approach (Fast - Vectorized)

**What it does:**
```python
# Create coordinate grids for entire image
y_coords, x_coords = np.ogrid[:height, :width]

# Calculate distance from circle center for ALL pixels at once
distances_squared = (x_coords - cx)**2 + (y_coords - cy)**2

# Create boolean mask: True where pixel is inside circle
circle_mask = distances_squared <= r**2

# Extract pixels inside circle and count black ones
pixels_in_circle = gray_img[circle_mask]
black_pixels = np.sum(pixels_in_circle < 128)
total_pixels = np.sum(circle_mask)
percentage = (black_pixels / total_pixels) * 100
```

**Visual Representation:**
```
Step 1: Create coordinate grids
x_coords = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],    y_coords = [[0], [1], [2], [3], [4],
           [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],                 [5], [6], [7], [8], [9]]
           [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
           ... (for all rows)

Step 2: Calculate distances (for circle at cx=5, cy=5, r=3)
distances_squared = [[34, 25, 18, 13, 10, 9, 10, 13, 18, 25],
                     [25, 16,  9,  4,  1, 0,  1,  4,  9, 16],
                     [18,  9,  2,  1,  2, 5,  2,  1,  2,  9],
                     [13,  4,  1,  0,  1, 4,  1,  0,  1,  4],
                     [10,  1,  2,  1,  2, 5,  2,  1,  2,  1],
                     [ 9,  0,  5,  4,  5, 8,  5,  4,  5,  0],
                     ...]

Step 3: Create mask (r² = 9)
circle_mask = [[False, False, False, False, False, False, False, False, False, False],
               [False, False, False, False, False,  True, False, False, False, False],
               [False, False,  True,  True,  True,  True,  True,  True,  True, False],
               [False, False,  True,  True,  True,  True,  True,  True,  True, False],
               [False,  True,  True,  True,  True,  True,  True,  True,  True,  True],
               [ True,  True,  True,  True,  True,  True,  True,  True,  True,  True],
               ...]

Visual circle (True = inside, False = outside):
    0 1 2 3 4 5 6 7 8 9
  0 . . . . . . . . . .
  1 . . . . . X . . . .
  2 . . X X X X X X X .
  3 . . X X X X X X X .
  4 . X X X X X X X X X
  5 X X X X X X X X X X  ← Center
  6 . X X X X X X X X X
  7 . . X X X X X X X .
  8 . . X X X X X X X .
  9 . . . . . X . . . .

Step 4: Extract and count (one operation!)
pixels_in_circle = gray_img[circle_mask]  # Gets all pixels where mask=True
black_pixels = np.sum(pixels_in_circle < 128)  # Counts in one operation
```

**Why it's faster:**
1. **Vectorized operations**: NumPy does calculations in C, not Python
2. **Single pass**: Calculates all distances at once
3. **Efficient memory access**: NumPy optimizes memory layout
4. **No Python loop overhead**: No function call overhead per pixel

**Speed comparison:**
- Old way: ~2,000,000 Python operations for 10 circles
- New way: ~10 NumPy operations (each processes thousands of pixels)
- **Expected speedup: 50-200x faster!**

---

## 2. Gradient Descent for Circle Optimization

### Current Approach (Grid Search)

**What it does:**
```python
# Test every position in a grid
for dy in range(-search_radius, search_radius + 1, step_size):
    for dx in range(-search_radius, search_radius + 1, step_size):
        test_x, test_y = x + dx, y + dy
        percentage = calculate_black_percentage(test_x, test_y, r)
        if percentage > best_percentage:
            best_x, best_y = test_x, test_y
```

**Visual Representation:**
```
Search space (search_radius=240, step_size=3):
┌─────────────────────────────────────────────┐
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  X  .  .  .  .  .  .  .  .  .  │  ← Start position
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
│  .  .  .  .  .  .  .  .  .  .  .  .  .  .  │
└─────────────────────────────────────────────┘

Tests positions in a grid pattern:
X = start
. = tested position (every 3 pixels)
Total: ~6,400 positions tested

Black percentage "landscape":
     ┌─────────────────┐
    ╱                 ╲
   ╱                   ╲
  ╱                     ╲
 ╱        Peak           ╲
╱                         ╲
─────────────────────────────
Grid search finds peak by checking every point
```

**Problems:**
- Tests many unnecessary positions
- Doesn't use information about which direction improves
- Slow for large search areas

---

### Gradient Descent Approach

**Concept:**
Instead of testing random positions, follow the "slope" (gradient) that increases black percentage.

**Visual Representation:**
```
Black percentage as a 2D function:
     Percentage
        ↑
        │     ╱╲
        │    ╱  ╲
        │   ╱    ╲
        │  ╱      ╲
        │ ╱        ╲
        │╱          ╲
        └──────────────→ Position (x, y)

At any point, we can calculate the gradient:
- Gradient points in direction of steepest increase
- Follow gradient to find maximum

Step-by-step visualization:
Start: X
       │
       │  Gradient points this way →
       │  (black % increases fastest in this direction)
       ↓
Step 1: Move in gradient direction
       X──→X'
       │
       │  New gradient
       ↓
Step 2: Follow new gradient
       X──→X'──→X''
       │
       │  Gradient getting smaller (near peak)
       ↓
Step 3: Converge at peak
       X──→X'──→X''──→● (optimal position)
```

**Mathematical Explanation:**

1. **Calculate Gradient:**
```python
# Gradient = how much black percentage changes when we move
# Partial derivatives tell us the slope in x and y directions

def calculate_gradient(cx, cy, r, gray_img, step=1.0):
    """Calculate gradient of black percentage at position (cx, cy)"""
    
    # Current black percentage
    current = calculate_black_percentage(cx, cy, r, gray_img)
    
    # How much does it change if we move right?
    right = calculate_black_percentage(cx + step, cy, r, gray_img)
    gradient_x = (right - current) / step
    
    # How much does it change if we move up?
    up = calculate_black_percentage(cx, cy + step, r, gray_img)
    gradient_y = (up - current) / step
    
    return np.array([gradient_x, gradient_y])
```

2. **Follow the Gradient:**
```python
def gradient_descent_optimize(circle, gray_img, learning_rate=5.0, max_iterations=50):
    """Optimize circle position using gradient descent"""
    x, y, r = circle
    current_x, current_y = x, y
    
    for iteration in range(max_iterations):
        # Calculate gradient at current position
        gradient = calculate_gradient(current_x, current_y, r, gray_img)
        
        # Gradient magnitude (how steep is the slope?)
        magnitude = np.sqrt(gradient[0]**2 + gradient[1]**2)
        
        # If gradient is very small, we're at a peak (converged)
        if magnitude < 0.1:
            break
        
        # Move in direction of gradient (uphill)
        # learning_rate controls step size
        current_x += learning_rate * gradient[0]
        current_y += learning_rate * gradient[1]
        
        # Keep within image bounds
        current_x = np.clip(current_x, r, width - r)
        current_y = np.clip(current_y, r, height - r)
    
    return [current_x, current_y, r]
```

**Visual Path:**
```
Starting position: X
                   │
                   │ Gradient points → (black % increases this way)
                   ↓
Iteration 1:      X──→X₁
                   │
                   │ New gradient
                   ↓
Iteration 2:      X──→X₁──→X₂
                   │
                   │ Gradient getting smaller
                   ↓
Iteration 3:      X──→X₁──→X₂──→X₃
                   │
                   │ Gradient very small (converged)
                   ↓
Final:            X──→X₁──→X₂──→X₃──→● (optimal)
```

**Advantages:**
1. **Much fewer evaluations**: ~10-50 iterations vs 6,400 grid points
2. **Finds optimal position**: Follows the actual slope to maximum
3. **Adaptive**: Takes larger steps when far from peak, smaller when close
4. **Can handle multiple peaks**: With different starting points

**Comparison:**

| Method | Evaluations | Time | Accuracy |
|--------|------------|------|----------|
| Grid Search | ~6,400 | Slow | Good (finds global max if fine enough) |
| Gradient Descent | ~20-50 | Fast | Excellent (finds local max, can miss global) |

**Hybrid Approach (Best of Both):**
1. Start with coarse grid search (step_size=20) to find promising region
2. Use gradient descent from best grid point to refine
3. Result: Fast + finds global maximum

---

## Summary

### NumPy Masks:
- **What**: Vectorized operations instead of loops
- **Why**: 50-200x faster pixel sampling
- **How**: Create boolean masks, use NumPy indexing

### Gradient Descent:
- **What**: Follow the slope to find maximum
- **Why**: 100-300x fewer position evaluations
- **How**: Calculate gradient, move in that direction, repeat

Both techniques work together to make circle optimization much faster while maintaining or improving accuracy!

