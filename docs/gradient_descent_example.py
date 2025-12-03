"""
Simple example demonstrating gradient descent for circle optimization
This shows how gradient descent "walks uphill" to find the maximum
"""
import numpy as np
import matplotlib.pyplot as plt

def create_test_landscape():
    """Create a 2D function that represents black percentage landscape"""
    x = np.linspace(0, 100, 100)
    y = np.linspace(0, 100, 100)
    X, Y = np.meshgrid(x, y)
    
    # Create a function with a peak (simulating black percentage)
    # Peak at (70, 60) with value 95%
    peak_x, peak_y = 70, 60
    Z = 95 * np.exp(-((X - peak_x)**2 + (Y - peak_y)**2) / 200)
    Z += np.random.randn(100, 100) * 2  # Add some noise
    
    return X, Y, Z

def calculate_gradient_numerical(Z, x_idx, y_idx, step=1):
    """Calculate gradient at position (x_idx, y_idx)"""
    h, w = Z.shape
    
    # Current value
    current = Z[y_idx, x_idx]
    
    # Partial derivative in x direction
    if x_idx + step < w:
        right = Z[y_idx, x_idx + step]
        grad_x = (right - current) / step
    else:
        grad_x = 0
    
    # Partial derivative in y direction
    if y_idx + step < h:
        up = Z[y_idx + step, x_idx]
        grad_y = (up - current) / step
    else:
        grad_y = 0
    
    return np.array([grad_x, grad_y])

def gradient_descent_path(Z, start_x, start_y, learning_rate=2.0, max_iterations=30):
    """Follow gradient descent path"""
    path = [(start_x, start_y)]
    current_x, current_y = start_x, start_y
    
    for i in range(max_iterations):
        # Convert to indices
        x_idx = int(np.clip(current_x, 0, Z.shape[1] - 1))
        y_idx = int(np.clip(current_y, 0, Z.shape[0] - 1))
        
        # Calculate gradient
        gradient = calculate_gradient_numerical(Z, x_idx, y_idx)
        magnitude = np.sqrt(gradient[0]**2 + gradient[1]**2)
        
        # If gradient is very small, we've converged
        if magnitude < 0.1:
            print(f"Converged at iteration {i}")
            break
        
        # Move in direction of gradient (uphill)
        current_x += learning_rate * gradient[0]
        current_y += learning_rate * gradient[1]
        
        # Keep in bounds
        current_x = np.clip(current_x, 0, Z.shape[1] - 1)
        current_y = np.clip(current_y, 0, Z.shape[0] - 1)
        
        path.append((current_x, current_y))
        
        # Print progress
        value = Z[y_idx, x_idx]
        print(f"Iteration {i+1}: Position ({current_x:.1f}, {current_y:.1f}), "
              f"Value: {value:.1f}%, Gradient magnitude: {magnitude:.2f}")
    
    return path

# Create test landscape
print("Creating test landscape (black percentage as function of position)...")
X, Y, Z = create_test_landscape()

# Find actual peak
peak_idx = np.unravel_index(np.argmax(Z), Z.shape)
peak_x, peak_y = X[0, peak_idx[1]], Y[peak_idx[0], 0]
print(f"Actual peak at: ({peak_x:.1f}, {peak_y:.1f}), Value: {Z[peak_idx]:.1f}%")

# Start gradient descent from a random point
start_x, start_y = 20, 30
print(f"\nStarting gradient descent from: ({start_x}, {start_y})")
print("="*60)

path = gradient_descent_path(Z, start_x, start_y)

# Final position
final_x, final_y = path[-1]
final_idx = (int(final_y), int(final_x))
final_value = Z[final_idx[0], final_idx[1]]

print("="*60)
print(f"Final position: ({final_x:.1f}, {final_y:.1f}), Value: {final_value:.1f}%")
print(f"Distance from actual peak: {np.sqrt((final_x - peak_x)**2 + (final_y - peak_y)**2):.1f} pixels")

# Visualize
print("\nCreating visualization...")
fig, ax = plt.subplots(figsize=(10, 8))

# Plot landscape
contour = ax.contourf(X, Y, Z, levels=20, cmap='viridis')
plt.colorbar(contour, ax=ax, label='Black Percentage (%)')

# Plot path
path_x, path_y = zip(*path)
ax.plot(path_x, path_y, 'r-o', linewidth=2, markersize=6, label='Gradient Descent Path')
ax.plot(start_x, start_y, 'go', markersize=12, label='Start')
ax.plot(final_x, final_y, 'ro', markersize=12, label='Final')
ax.plot(peak_x, peak_y, 'y*', markersize=15, label='Actual Peak')

ax.set_xlabel('X Position')
ax.set_ylabel('Y Position')
ax.set_title('Gradient Descent Optimization Path')
ax.legend()
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('gradient_descent_path.png', dpi=150)
print("Saved visualization to: gradient_descent_path.png")
print("\nThe red line shows how gradient descent 'walks uphill' to find the peak!")

