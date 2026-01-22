"""
Extract validation metrics (segm/AP and bbox/AP) from completed hyperparameter sweep runs.

This script reads metrics from:
1. metrics.json files (Detectron2's JSONL format)
2. *_live.csv files (live tracking CSV)
3. validation_eval/coco_instances_results.json (final validation results)

And creates/updates a summary CSV with all the validation metrics.
Also creates comparison plots similar to analyze_three_runs_metrics.py
"""

import json
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np


def load_metrics_from_jsonl(json_path: Path) -> Dict:
    """Load Detectron2-style JSONL metrics file and extract all metrics"""
    data = {
        'train_iters': [],
        'train_loss': [],
        'train_mask_acc': [],
        'val_iters': [],
        'val_segm_aps': [],
        'val_bbox_aps': []
    }
    
    if not json_path.exists():
        return data
    
    try:
        with json_path.open('r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                
                iteration = record.get('iteration')
                if iteration is None:
                    continue
                
                # Training stats
                if 'total_loss' in record:
                    data['train_iters'].append(iteration)
                    data['train_loss'].append(float(record.get('total_loss', 0.0)))
                    data['train_mask_acc'].append(float(record.get('mask_rcnn/accuracy', 0.0)))
                
                # Validation stats (has AP metrics)
                if 'segm/AP' in record or 'bbox/AP' in record:
                    data['val_iters'].append(iteration)
                    data['val_segm_aps'].append(float(record.get('segm/AP', 0.0)))
                    data['val_bbox_aps'].append(float(record.get('bbox/AP', 0.0)))
    except Exception as e:
        print(f"  [WARNING] Error reading {json_path}: {e}")
    
    return data


def load_metrics_from_live_csv(csv_path: Path) -> Dict:
    """Load metrics from live CSV file"""
    val_data = {
        'iterations': [],
        'segm_aps': [],
        'bbox_aps': []
    }
    
    if not csv_path.exists():
        return val_data
    
    try:
        with csv_path.open('r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            print(f"    CSV headers: {headers}")
            
            for row in reader:
                iteration = row.get('iteration')
                # Try multiple possible column names
                segm_ap = (row.get('validation_segm_ap') or 
                          row.get('validation_ap') or 
                          row.get('segm/AP') or '')
                bbox_ap = (row.get('validation_bbox_ap') or 
                          row.get('bbox/AP') or '')
                
                # Only add if we have at least one AP value
                if iteration and (segm_ap.strip() or bbox_ap.strip()):
                    try:
                        iter_val = int(iteration)
                        segm_val = float(segm_ap) if segm_ap.strip() else 0.0
                        bbox_val = float(bbox_ap) if bbox_ap.strip() else 0.0
                        
                        val_data['iterations'].append(iter_val)
                        val_data['segm_aps'].append(segm_val)
                        val_data['bbox_aps'].append(bbox_val)
                    except (ValueError, TypeError) as e:
                        # Skip invalid rows
                        continue
    except Exception as e:
        print(f"  [WARNING] Error reading {csv_path}: {e}")
        import traceback
        traceback.print_exc()
    
    return val_data


def load_final_validation_results(validation_eval_dir: Path) -> Dict:
    """Load final validation results from COCO evaluator output"""
    results_file = validation_eval_dir / "coco_instances_results.json"
    
    if not results_file.exists():
        return {}
    
    try:
        with results_file.open('r') as f:
            data = json.load(f)
            # COCO results format: nested dict with 'segm' and 'bbox' keys
            results = {}
            if isinstance(data, dict):
                if 'segm' in data and isinstance(data['segm'], dict):
                    for key, value in data['segm'].items():
                        results[f'segm/{key}'] = value
                if 'bbox' in data and isinstance(data['bbox'], dict):
                    for key, value in data['bbox'].items():
                        results[f'bbox/{key}'] = value
            return results
    except Exception as e:
        print(f"  [WARNING] Error reading {results_file}: {e}")
        return {}


def extract_run_metrics(run_folder: Path) -> Optional[Dict]:
    """Extract all validation metrics from a single run folder"""
    if not run_folder.is_dir():
        return None
    
    # Try to parse run name for learning rate and anchors
    run_name = run_folder.name
    match = re.match(r'^lr0_(\d{4})_anchors(.+?)_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}$', run_name)
    if not match:
        return None
    
    lr_str = match.group(1)
    if len(lr_str) == 4:
        learning_rate = float(lr_str) / 10000.0
    else:
        learning_rate = float(lr_str) / 1000.0
    
    anchors_str = match.group(2)
    anchor_sizes = [int(x) for x in anchors_str.split("_") if x.isdigit()]
    
    # Load metrics from different sources
    metrics_json = run_folder / "metrics.json"
    live_csv = None
    for csv_file in run_folder.glob("*_live.csv"):
        live_csv = csv_file
        break
    
    validation_eval_dir = run_folder / "validation_eval"
    
    # Try to get metrics from JSONL first (most complete)
    json_metrics = load_metrics_from_jsonl(metrics_json)
    
    # Always also check live CSV (it's more reliable for validation data)
    csv_metrics = None
    if live_csv:
        csv_metrics = load_metrics_from_live_csv(live_csv)
        # If CSV has validation data, use it (it's more complete)
        if len(csv_metrics['iterations']) > 0:
            print(f"    Found {len(csv_metrics['iterations'])} validations in live CSV")
            json_metrics['val_iters'] = csv_metrics['iterations']
            json_metrics['val_segm_aps'] = csv_metrics['segm_aps']
            json_metrics['val_bbox_aps'] = csv_metrics['bbox_aps']
        elif len(json_metrics['val_iters']) > 0:
            print(f"    Found {len(json_metrics['val_iters'])} validations in metrics.json")
    elif len(json_metrics['val_iters']) > 0:
        print(f"    Found {len(json_metrics['val_iters'])} validations in metrics.json")
    
    # Get final validation results from validation_eval folder
    final_results = load_final_validation_results(validation_eval_dir)
    
    # If bbox/AP is missing from CSV/JSONL but we have validation iterations,
    # try to get bbox/AP from the final validation results
    # Note: This only gives us the final bbox/AP, not the history
    if len(json_metrics['val_iters']) > 0 and all(ap == 0.0 for ap in json_metrics['val_bbox_aps']):
        # We have validation iterations but no bbox/AP data
        # Try to get from final results (at least we'll have the final value)
        if 'bbox/AP' in final_results:
            final_bbox_ap = float(final_results['bbox/AP'])
            # Use final value for all validations (not ideal, but better than 0)
            print(f"    [INFO] bbox/AP missing from CSV, using final value from validation_eval: {final_bbox_ap:.4f}")
            json_metrics['val_bbox_aps'] = [final_bbox_ap] * len(json_metrics['val_iters'])
    
    # Calculate best and final metrics
    if len(json_metrics['val_segm_aps']) > 0:
        best_segm_idx = max(range(len(json_metrics['val_segm_aps'])), 
                           key=lambda i: json_metrics['val_segm_aps'][i])
        best_segm_ap = json_metrics['val_segm_aps'][best_segm_idx]
        best_segm_iter = json_metrics['val_iters'][best_segm_idx]
        final_segm_ap = json_metrics['val_segm_aps'][-1]
    else:
        # Try to get from final results
        best_segm_ap = final_results.get('segm/AP', 0.0)
        final_segm_ap = best_segm_ap
        best_segm_iter = 0
    
    if len(json_metrics['val_bbox_aps']) > 0 and any(ap > 0.0 for ap in json_metrics['val_bbox_aps']):
        # We have real bbox/AP data
        best_bbox_idx = max(range(len(json_metrics['val_bbox_aps'])), 
                           key=lambda i: json_metrics['val_bbox_aps'][i])
        best_bbox_ap = json_metrics['val_bbox_aps'][best_bbox_idx]
        best_bbox_iter = json_metrics['val_iters'][best_bbox_idx]
        final_bbox_ap = json_metrics['val_bbox_aps'][-1]
    else:
        # Try to get from final results
        best_bbox_ap = final_results.get('bbox/AP', 0.0)
        final_bbox_ap = best_bbox_ap
        best_bbox_iter = 0
        if best_bbox_ap > 0:
            print(f"    [INFO] Using bbox/AP from final validation results: {best_bbox_ap:.4f}")
    
    # Create label for plotting
    anchors_display = ",".join(map(str, anchor_sizes))
    label = f"lr{learning_rate:.4f}_anchors[{anchors_display}]"
    
    return {
        'run_name': run_name,
        'label': label,
        'learning_rate': learning_rate,
        'anchor_sizes': str(anchor_sizes),
        'final_val_segm_ap': final_segm_ap,
        'final_val_bbox_ap': final_bbox_ap,
        'best_val_segm_ap': best_segm_ap,
        'best_val_bbox_ap': best_bbox_ap,
        'best_val_iter': max(best_segm_iter, best_bbox_iter) if json_metrics['val_iters'] else 0,
        'num_validations': len(json_metrics['val_iters']),
        # Full metrics for plotting
        'train_iters': json_metrics['train_iters'],
        'train_loss': json_metrics['train_loss'],
        'train_mask_acc': json_metrics['train_mask_acc'],
        'val_iters': json_metrics['val_iters'],
        'val_segm_aps': json_metrics['val_segm_aps'],
        'val_bbox_aps': json_metrics['val_bbox_aps']
    }


def plot_runs(run_stats: Dict[str, Dict], out_path: Path):
    """
    Create comparison plots similar to analyze_three_runs_metrics.py
    run_stats: dict[label] -> metrics dict with train/val data
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    num_runs = len(run_stats)
    if num_runs == 0:
        print("  [WARNING] No runs to plot!")
        return
    
    # Use colormap for many runs, or distinct colors for few
    if num_runs <= 10:
        colors = plt.cm.tab10(np.linspace(0, 1, num_runs))
    else:
        colors = plt.cm.tab20(np.linspace(0, 1, num_runs))
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 12), sharex="col")
    
    ax_loss, ax_mask_acc = axes[0]
    ax_val_segm, ax_val_bbox = axes[1]
    
    # Training curves
    for (label, stats), color in zip(run_stats.items(), colors):
        if stats.get('train_iters') and len(stats['train_iters']) > 0:
            ax_loss.plot(
                stats['train_iters'],
                stats['train_loss'],
                label=label,
                linewidth=1.5,
                color=color,
                alpha=0.8,
            )
            ax_mask_acc.plot(
                stats['train_iters'],
                stats['train_mask_acc'],
                label=label,
                linewidth=1.5,
                color=color,
                alpha=0.8,
            )
    
    ax_loss.set_title("Training total_loss vs iteration", fontsize=12)
    ax_loss.set_xlabel("Iteration")
    ax_loss.set_ylabel("Total loss")
    ax_loss.set_xlim(left=0)
    ax_loss.grid(True, linestyle="--", alpha=0.4)
    
    ax_mask_acc.set_title("Mask R-CNN accuracy vs iteration", fontsize=12)
    ax_mask_acc.set_xlabel("Iteration")
    ax_mask_acc.set_ylabel("mask_rcnn/accuracy")
    ax_mask_acc.set_xlim(left=0)
    ax_mask_acc.grid(True, linestyle="--", alpha=0.4)
    
    # Validation AP curves (discrete points)
    for (label, stats), color in zip(run_stats.items(), colors):
        if stats.get('val_iters') and len(stats['val_iters']) > 0:
            ax_val_segm.plot(
                stats['val_iters'],
                stats['val_segm_aps'],
                marker="o",
                linestyle="-",
                label=label,
                color=color,
                alpha=0.8,
                markersize=6,
            )
            ax_val_bbox.plot(
                stats['val_iters'],
                stats['val_bbox_aps'],
                marker="o",
                linestyle="-",
                label=label,
                color=color,
                alpha=0.8,
                markersize=6,
            )
    
    ax_val_segm.set_title("Validation segm/AP vs iteration", fontsize=12)
    ax_val_segm.set_xlabel("Iteration")
    ax_val_segm.set_ylabel("segm/AP")
    ax_val_segm.set_xlim(left=0)
    ax_val_segm.grid(True, linestyle="--", alpha=0.4)
    
    ax_val_bbox.set_title("Validation bbox/AP vs iteration", fontsize=12)
    ax_val_bbox.set_xlabel("Iteration")
    ax_val_bbox.set_ylabel("bbox/AP")
    ax_val_bbox.set_xlim(left=0)
    ax_val_bbox.grid(True, linestyle="--", alpha=0.4)
    
    # Place legends - use smaller font and outside if many runs
    if num_runs <= 8:
        ax_loss.legend(loc="upper right", fontsize=8)
        ax_mask_acc.legend(loc="lower right", fontsize=8)
        ax_val_segm.legend(loc="upper left", fontsize=8)
        ax_val_bbox.legend(loc="upper left", fontsize=8)
    else:
        # For many runs, put legend outside or use compact format
        ax_loss.legend(loc="upper right", fontsize=6, ncol=1)
        ax_mask_acc.legend(loc="lower right", fontsize=6, ncol=1)
        ax_val_segm.legend(loc="upper left", fontsize=6, ncol=1)
        ax_val_bbox.legend(loc="upper left", fontsize=6, ncol=1)
    
    plt.tight_layout()
    fig.suptitle(f"Hyperparameter Sweep Comparison ({num_runs} runs)", fontsize=14, y=0.995)
    fig.subplots_adjust(top=0.92)
    
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Comparison plot saved: {out_path}")


def main():
    """Extract metrics from all runs in a sweep folder"""
    sweep_folder = Path(r"D:\Experiments\AI\Hyperparameters\sweep_2026_01_21_21_39_37")
    
    if not sweep_folder.exists():
        print(f"ERROR: Sweep folder not found: {sweep_folder}")
        return
    
    print(f"Extracting metrics from: {sweep_folder}")
    print("="*80)
    
    # Find all run folders
    run_folders = [d for d in sweep_folder.iterdir() 
                   if d.is_dir() and d.name.startswith('lr0_')]
    
    if not run_folders:
        print("No run folders found!")
        return
    
    print(f"Found {len(run_folders)} run folder(s)\n")
    
    # Extract metrics from each run
    all_metrics = []
    for run_folder in sorted(run_folders):
        print(f"Processing: {run_folder.name}")
        metrics = extract_run_metrics(run_folder)
        if metrics:
            all_metrics.append(metrics)
            print(f"  ✓ Final segm/AP: {metrics['final_val_segm_ap']:.4f}")
            print(f"  ✓ Final bbox/AP: {metrics['final_val_bbox_ap']:.4f}")
            print(f"  ✓ Best segm/AP: {metrics['best_val_segm_ap']:.4f}")
            print(f"  ✓ Best bbox/AP: {metrics['best_val_bbox_ap']:.4f}")
            print(f"  ✓ Validations: {metrics['num_validations']}")
            if metrics['num_validations'] > 0:
                print(f"  ✓ Val iterations: {metrics['val_iters'][:5]}..." if len(metrics['val_iters']) > 5 else f"  ✓ Val iterations: {metrics['val_iters']}")
                print(f"  ✓ Val segm/APs: {[f'{x:.2f}' for x in metrics['val_segm_aps'][:5]]}..." if len(metrics['val_segm_aps']) > 5 else f"  ✓ Val segm/APs: {[f'{x:.2f}' for x in metrics['val_segm_aps']]}")
                print(f"  ✓ Val bbox/APs: {[f'{x:.2f}' for x in metrics['val_bbox_aps'][:5]]}..." if len(metrics['val_bbox_aps']) > 5 else f"  ✓ Val bbox/APs: {[f'{x:.2f}' for x in metrics['val_bbox_aps']]}")
        else:
            print(f"  ✗ Could not extract metrics")
        print()
    
    if not all_metrics:
        print("No metrics extracted!")
        return
    
    # Prepare data for plotting (convert to format expected by plot_runs)
    run_stats = {}
    for metrics in all_metrics:
        label = metrics['label']
        run_stats[label] = {
            'train_iters': metrics.get('train_iters', []),
            'train_loss': metrics.get('train_loss', []),
            'train_mask_acc': metrics.get('train_mask_acc', []),
            'val_iters': metrics.get('val_iters', []),
            'val_segm_aps': metrics.get('val_segm_aps', []),
            'val_bbox_aps': metrics.get('val_bbox_aps', [])
        }
    
    # Create comparison plot
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    plot_path = sweep_folder / f"extracted_metrics_comparison_{timestamp}.png"
    print("\nCreating comparison plot...")
    plot_runs(run_stats, plot_path)
    
    # Save to CSV (use append mode if file exists and is locked)
    output_csv = sweep_folder / "extracted_metrics.csv"
    fieldnames = [
        'run_name', 'learning_rate', 'anchor_sizes',
        'final_val_segm_ap', 'final_val_bbox_ap',
        'best_val_segm_ap', 'best_val_bbox_ap', 'best_val_iter',
        'num_validations'
    ]
    
    try:
        with open(output_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for metrics in all_metrics:
                row = {k: v for k, v in metrics.items() if k in fieldnames}
                writer.writerow(row)
    except PermissionError:
        # File might be open in Excel or another program
        print(f"\n[WARNING] Could not write to {output_csv} (file may be open in another program)")
        print(f"  Please close the file and run the script again, or the CSV will be skipped.")
        print(f"  The plot was still created successfully.")
    
    print("="*80)
    print(f"✓ Extracted metrics from {len(all_metrics)} runs")
    print(f"✓ Saved CSV to: {output_csv}")
    print(f"✓ Saved plot to: {plot_path}")
    print("\nSummary:")
    print("-"*80)
    
    # Print summary sorted by best segm/AP
    sorted_metrics = sorted(all_metrics, key=lambda x: x['best_val_segm_ap'], reverse=True)
    for i, metrics in enumerate(sorted_metrics, 1):
        print(f"{i}. {metrics['run_name']}")
        print(f"   LR: {metrics['learning_rate']:.4f}, Anchors: {metrics['anchor_sizes']}")
        print(f"   Best segm/AP: {metrics['best_val_segm_ap']:.4f}, Best bbox/AP: {metrics['best_val_bbox_ap']:.4f}")
        print(f"   Final segm/AP: {metrics['final_val_segm_ap']:.4f}, Final bbox/AP: {metrics['final_val_bbox_ap']:.4f}")
        print()


if __name__ == "__main__":
    main()
