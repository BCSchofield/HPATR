"""
Plot training loss curve from metrics.json
Reads Detectron2 metrics.json and creates loss visualization
"""

import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend to avoid display issues
import matplotlib.pyplot as plt
from pathlib import Path

# Path to metrics file
METRICS_FILE = Path(r"D:\Experiments\AI\training_2025_12_24_19_37_46\metrics.json")
OUTPUT_PLOT = METRICS_FILE.parent / "plots" / "loss_curve.png"

def plot_from_metrics():
    """Read metrics.json and create loss plot"""
    
    print(f"Reading metrics from: {METRICS_FILE}")
    
    if not METRICS_FILE.exists():
        print(f"ERROR: Metrics file not found: {METRICS_FILE}")
        return
    
    # Read metrics (one JSON object per line)
    iterations = []
    total_losses = []
    loss_cls = []
    loss_box_reg = []
    loss_mask = []
    loss_rpn_cls = []
    loss_rpn_loc = []
    
    with open(METRICS_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if 'iteration' in data and 'total_loss' in data:
                    iterations.append(data['iteration'])
                    total_losses.append(data['total_loss'])
                    
                    # Individual losses (may not be in every entry)
                    loss_cls.append(data.get('loss_cls', 0))
                    loss_box_reg.append(data.get('loss_box_reg', 0))
                    loss_mask.append(data.get('loss_mask', 0))
                    loss_rpn_cls.append(data.get('loss_rpn_cls', 0))
                    loss_rpn_loc.append(data.get('loss_rpn_loc', 0))
            except json.JSONDecodeError:
                continue
    
    if len(iterations) == 0:
        print("ERROR: No valid data found in metrics.json")
        return
    
    print(f"Found {len(iterations)} data points")
    print(f"  Iterations: {min(iterations)} to {max(iterations)}")
    print(f"  Total loss range: {min(total_losses):.4f} to {max(total_losses):.4f}")
    
    # Create output directory
    OUTPUT_PLOT.parent.mkdir(parents=True, exist_ok=True)
    
    # Create plot
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))
    
    # Plot 1: Total loss
    ax1 = axes[0]
    ax1.plot(iterations, total_losses, 'b-', linewidth=2, label='Total Loss')
    ax1.set_xlabel('Iteration', fontsize=12)
    ax1.set_ylabel('Total Loss', fontsize=12)
    ax1.set_title('Training Loss Curve - Total Loss', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    
    # Plot 2: Individual losses
    ax2 = axes[1]
    ax2.plot(iterations, loss_cls, label='Classification Loss', linewidth=1.5, alpha=0.8)
    ax2.plot(iterations, loss_box_reg, label='Box Regression Loss', linewidth=1.5, alpha=0.8)
    ax2.plot(iterations, loss_mask, label='Mask Loss', linewidth=1.5, alpha=0.8)
    ax2.plot(iterations, loss_rpn_cls, label='RPN Classification Loss', linewidth=1.5, alpha=0.8)
    ax2.plot(iterations, loss_rpn_loc, label='RPN Localization Loss', linewidth=1.5, alpha=0.8)
    ax2.set_xlabel('Iteration', fontsize=12)
    ax2.set_ylabel('Loss', fontsize=12)
    ax2.set_title('Training Loss Curve - Individual Components', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"\n[OK] Loss plot saved to: {OUTPUT_PLOT}")
    print(f"  Total data points: {len(iterations)}")
    print(f"  Final loss: {total_losses[-1]:.4f} at iteration {iterations[-1]}")

if __name__ == "__main__":
    plot_from_metrics()

