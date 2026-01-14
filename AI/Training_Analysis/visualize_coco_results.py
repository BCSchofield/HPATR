"""
Visualize COCO evaluation results from validation run
Creates multiple visualizations to understand model performance
"""

import json
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from collections import Counter, defaultdict

# Paths
RESULTS_FILE = Path(r"D:\Experiments\AI\training_2025_12_25_15_43_57\validation_eval\coco_instances_results.json")
OUTPUT_DIR = Path(r"D:\Experiments\AI\training_2025_12_25_15_43_57\validation_eval\visualizations")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_results():
    """Load COCO results JSON"""
    print(f"Loading results from: {RESULTS_FILE}")
    with open(RESULTS_FILE, 'r') as f:
        results = json.load(f)
    print(f"Loaded {len(results)} predictions")
    return results

def visualize_score_distribution(results):
    """Plot distribution of confidence scores"""
    scores = [r['score'] for r in results]
    
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))
    
    # Histogram
    ax1 = axes[0]
    ax1.hist(scores, bins=50, edgecolor='black', alpha=0.7, color='steelblue')
    ax1.set_xlabel('Confidence Score', fontsize=12)
    ax1.set_ylabel('Number of Predictions', fontsize=12)
    ax1.set_title('Distribution of Prediction Confidence Scores', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.axvline(np.mean(scores), color='red', linestyle='--', linewidth=2, 
                label=f'Mean: {np.mean(scores):.3f}')
    ax1.axvline(np.median(scores), color='green', linestyle='--', linewidth=2, 
                label=f'Median: {np.median(scores):.3f}')
    ax1.legend()
    
    # Cumulative distribution
    ax2 = axes[1]
    sorted_scores = np.sort(scores)
    cumulative = np.arange(1, len(sorted_scores) + 1) / len(sorted_scores)
    ax2.plot(sorted_scores, cumulative, linewidth=2, color='steelblue')
    ax2.set_xlabel('Confidence Score', fontsize=12)
    ax2.set_ylabel('Cumulative Proportion', fontsize=12)
    ax2.set_title('Cumulative Distribution of Scores', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    # Add percentile markers
    for p in [50, 75, 90, 95, 99]:
        idx = int(len(sorted_scores) * p / 100)
        if idx < len(sorted_scores):
            score_val = sorted_scores[idx]
            ax2.axvline(score_val, color='red', linestyle='--', alpha=0.5)
            ax2.text(score_val, 0.02, f'{p}%: {score_val:.3f}', 
                    rotation=90, verticalalignment='bottom')
    
    plt.tight_layout()
    output_path = OUTPUT_DIR / "score_distribution.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  [OK] Score distribution saved: {output_path}")
    
    # Print statistics
    print(f"\n  Score Statistics:")
    print(f"    Mean: {np.mean(scores):.4f}")
    print(f"    Median: {np.median(scores):.4f}")
    print(f"    Std Dev: {np.std(scores):.4f}")
    print(f"    Min: {np.min(scores):.4f}")
    print(f"    Max: {np.max(scores):.4f}")
    print(f"    25th percentile: {np.percentile(scores, 25):.4f}")
    print(f"    75th percentile: {np.percentile(scores, 75):.4f}")
    print(f"    95th percentile: {np.percentile(scores, 95):.4f}")

def visualize_category_distribution(results):
    """Plot distribution by category"""
    category_counts = Counter([r['category_id'] for r in results])
    category_scores = defaultdict(list)
    
    for r in results:
        category_scores[r['category_id']].append(r['score'])
    
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))
    
    # Count by category
    ax1 = axes[0]
    categories = list(category_counts.keys())
    counts = [category_counts[c] for c in categories]
    category_names = [f'Category {c}' for c in categories]
    
    bars = ax1.bar(category_names, counts, color=['steelblue', 'coral'], alpha=0.7, edgecolor='black')
    ax1.set_xlabel('Category', fontsize=12)
    ax1.set_ylabel('Number of Predictions', fontsize=12)
    ax1.set_title('Number of Predictions by Category', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Add count labels on bars
    for bar, count in zip(bars, counts):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{count:,}', ha='center', va='bottom', fontweight='bold')
    
    # Score distribution by category
    ax2 = axes[1]
    for cat_id in sorted(categories):
        scores = category_scores[cat_id]
        ax2.hist(scores, bins=30, alpha=0.6, label=f'Category {cat_id}', 
                edgecolor='black')
    
    ax2.set_xlabel('Confidence Score', fontsize=12)
    ax2.set_ylabel('Number of Predictions', fontsize=12)
    ax2.set_title('Score Distribution by Category', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = OUTPUT_DIR / "category_distribution.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  [OK] Category distribution saved: {output_path}")
    
    # Print category statistics
    print(f"\n  Category Statistics:")
    for cat_id in sorted(categories):
        scores = category_scores[cat_id]
        print(f"    Category {cat_id}: {category_counts[cat_id]:,} predictions")
        print(f"      Mean score: {np.mean(scores):.4f}")
        print(f"      Median score: {np.median(scores):.4f}")

def visualize_predictions_per_image(results):
    """Plot distribution of number of predictions per image"""
    predictions_per_image = Counter([r['image_id'] for r in results])
    counts = list(predictions_per_image.values())
    
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))
    
    # Histogram
    ax1 = axes[0]
    ax1.hist(counts, bins=50, edgecolor='black', alpha=0.7, color='steelblue')
    ax1.set_xlabel('Number of Predictions per Image', fontsize=12)
    ax1.set_ylabel('Number of Images', fontsize=12)
    ax1.set_title('Distribution of Predictions per Image', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.axvline(np.mean(counts), color='red', linestyle='--', linewidth=2,
                label=f'Mean: {np.mean(counts):.1f}')
    ax1.axvline(np.median(counts), color='green', linestyle='--', linewidth=2,
                label=f'Median: {np.median(counts):.1f}')
    ax1.legend()
    
    # Box plot
    ax2 = axes[1]
    ax2.boxplot([counts], vert=True, patch_artist=True,
                boxprops=dict(facecolor='steelblue', alpha=0.7))
    ax2.set_ylabel('Number of Predictions per Image', fontsize=12)
    ax2.set_title('Box Plot: Predictions per Image', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.set_xticklabels(['All Images'])
    
    plt.tight_layout()
    output_path = OUTPUT_DIR / "predictions_per_image.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  [OK] Predictions per image saved: {output_path}")
    
    print(f"\n  Predictions per Image Statistics:")
    print(f"    Total images with predictions: {len(predictions_per_image):,}")
    print(f"    Mean predictions per image: {np.mean(counts):.2f}")
    print(f"    Median predictions per image: {np.median(counts):.2f}")
    print(f"    Min predictions: {np.min(counts)}")
    print(f"    Max predictions: {np.max(counts)}")
    print(f"    Images with 0 predictions: {4000 - len(predictions_per_image):,}")  # Assuming 4000 validation images

def visualize_bbox_sizes(results):
    """Plot distribution of bounding box sizes"""
    areas = []
    widths = []
    heights = []
    
    for r in results:
        bbox = r['bbox']  # [x, y, width, height]
        width = bbox[2]
        height = bbox[3]
        area = width * height
        
        widths.append(width)
        heights.append(height)
        areas.append(area)
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # Area distribution
    ax1 = axes[0, 0]
    ax1.hist(areas, bins=50, edgecolor='black', alpha=0.7, color='steelblue')
    ax1.set_xlabel('Bounding Box Area (pixels²)', fontsize=11)
    ax1.set_ylabel('Number of Predictions', fontsize=11)
    ax1.set_title('Distribution of Bounding Box Areas', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.set_yscale('log')
    
    # Width distribution
    ax2 = axes[0, 1]
    ax2.hist(widths, bins=50, edgecolor='black', alpha=0.7, color='coral')
    ax2.set_xlabel('Bounding Box Width (pixels)', fontsize=11)
    ax2.set_ylabel('Number of Predictions', fontsize=11)
    ax2.set_title('Distribution of Bounding Box Widths', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    # Height distribution
    ax3 = axes[1, 0]
    ax3.hist(heights, bins=50, edgecolor='black', alpha=0.7, color='green')
    ax3.set_xlabel('Bounding Box Height (pixels)', fontsize=11)
    ax3.set_ylabel('Number of Predictions', fontsize=11)
    ax3.set_title('Distribution of Bounding Box Heights', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    
    # Width vs Height scatter
    ax4 = axes[1, 1]
    # Sample for performance if too many points
    if len(widths) > 10000:
        indices = np.random.choice(len(widths), 10000, replace=False)
        sample_widths = [widths[i] for i in indices]
        sample_heights = [heights[i] for i in indices]
    else:
        sample_widths = widths
        sample_heights = heights
    
    ax4.scatter(sample_widths, sample_heights, alpha=0.3, s=1, color='steelblue')
    ax4.set_xlabel('Width (pixels)', fontsize=11)
    ax4.set_ylabel('Height (pixels)', fontsize=11)
    ax4.set_title('Width vs Height Scatter', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = OUTPUT_DIR / "bbox_sizes.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  [OK] Bounding box sizes saved: {output_path}")
    
    print(f"\n  Bounding Box Statistics:")
    print(f"    Mean area: {np.mean(areas):.1f} pixels²")
    print(f"    Median area: {np.median(areas):.1f} pixels²")
    print(f"    Mean width: {np.mean(widths):.1f} pixels")
    print(f"    Mean height: {np.mean(heights):.1f} pixels")

def visualize_score_vs_category(results):
    """Plot score distribution by category"""
    category_scores = defaultdict(list)
    
    for r in results:
        category_scores[r['category_id']].append(r['score'])
    
    fig, ax = plt.subplots(1, 1, figsize=(12, 6))
    
    categories = sorted(category_scores.keys())
    data_to_plot = [category_scores[cat] for cat in categories]
    labels = [f'Category {cat}' for cat in categories]
    
    bp = ax.boxplot(data_to_plot, tick_labels=labels, patch_artist=True,
                    showmeans=True, meanline=True)
    
    # Color the boxes
    colors = ['steelblue', 'coral']
    for patch, color in zip(bp['boxes'], colors[:len(bp['boxes'])]):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    ax.set_ylabel('Confidence Score', fontsize=12)
    ax.set_title('Score Distribution by Category (Box Plot)', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    output_path = OUTPUT_DIR / "score_vs_category.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  [OK] Score vs category saved: {output_path}")

def create_summary_report(results):
    """Create a text summary report"""
    report_path = OUTPUT_DIR / "summary_report.txt"
    
    scores = [r['score'] for r in results]
    category_counts = Counter([r['category_id'] for r in results])
    predictions_per_image = Counter([r['image_id'] for r in results])
    
    areas = []
    for r in results:
        bbox = r['bbox']
        areas.append(bbox[2] * bbox[3])
    
    with open(report_path, 'w') as f:
        f.write("=" * 60 + "\n")
        f.write("COCO VALIDATION RESULTS SUMMARY\n")
        f.write("=" * 60 + "\n\n")
        
        f.write(f"Total Predictions: {len(results):,}\n")
        f.write(f"Unique Images: {len(predictions_per_image):,}\n")
        f.write(f"Images with 0 predictions: {4000 - len(predictions_per_image):,}\n\n")
        
        f.write("SCORE STATISTICS:\n")
        f.write("-" * 60 + "\n")
        f.write(f"  Mean: {np.mean(scores):.4f}\n")
        f.write(f"  Median: {np.median(scores):.4f}\n")
        f.write(f"  Std Dev: {np.std(scores):.4f}\n")
        f.write(f"  Min: {np.min(scores):.4f}\n")
        f.write(f"  Max: {np.max(scores):.4f}\n")
        f.write(f"  25th percentile: {np.percentile(scores, 25):.4f}\n")
        f.write(f"  75th percentile: {np.percentile(scores, 75):.4f}\n")
        f.write(f"  95th percentile: {np.percentile(scores, 95):.4f}\n")
        f.write(f"  99th percentile: {np.percentile(scores, 99):.4f}\n\n")
        
        f.write("CATEGORY DISTRIBUTION:\n")
        f.write("-" * 60 + "\n")
        for cat_id in sorted(category_counts.keys()):
            count = category_counts[cat_id]
            pct = (count / len(results)) * 100
            f.write(f"  Category {cat_id}: {count:,} ({pct:.1f}%)\n")
        f.write("\n")
        
        f.write("PREDICTIONS PER IMAGE:\n")
        f.write("-" * 60 + "\n")
        counts = list(predictions_per_image.values())
        f.write(f"  Mean: {np.mean(counts):.2f}\n")
        f.write(f"  Median: {np.median(counts):.2f}\n")
        f.write(f"  Min: {np.min(counts)}\n")
        f.write(f"  Max: {np.max(counts)}\n\n")
        
        f.write("BOUNDING BOX STATISTICS:\n")
        f.write("-" * 60 + "\n")
        f.write(f"  Mean area: {np.mean(areas):.1f} pixels²\n")
        f.write(f"  Median area: {np.median(areas):.1f} pixels²\n")
        f.write(f"  Min area: {np.min(areas):.1f} pixels²\n")
        f.write(f"  Max area: {np.max(areas):.1f} pixels²\n")
    
    print(f"  [OK] Summary report saved: {report_path}")

def main():
    print("=" * 60)
    print("COCO Results Visualization")
    print("=" * 60)
    
    # Load results
    results = load_results()
    
    if len(results) == 0:
        print("ERROR: No results found!")
        return
    
    print(f"\nGenerating visualizations...")
    print("-" * 60)
    
    # Create all visualizations
    visualize_score_distribution(results)
    visualize_category_distribution(results)
    visualize_predictions_per_image(results)
    visualize_bbox_sizes(results)
    visualize_score_vs_category(results)
    create_summary_report(results)
    
    print("\n" + "=" * 60)
    print("Visualization Complete!")
    print("=" * 60)
    print(f"\nAll outputs saved to: {OUTPUT_DIR}")
    print("\nGenerated files:")
    print("  - score_distribution.png")
    print("  - category_distribution.png")
    print("  - predictions_per_image.png")
    print("  - bbox_sizes.png")
    print("  - score_vs_category.png")
    print("  - summary_report.txt")

if __name__ == "__main__":
    main()

