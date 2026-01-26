"""
Visualize and compare Dennis vs Claudia training metrics.
Creates comprehensive plots showing the differences between the two models.
"""

import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional

# Set style for better-looking plots
plt.style.use('seaborn-v0_8-darkgrid')
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['font.size'] = 10

def load_metrics_jsonl(json_path: Path) -> List[Dict]:
    """Load JSONL metrics file and return list of records."""
    records = []
    with open(json_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError:
                continue
    return records

def extract_metrics(records: List[Dict], model_name: str) -> pd.DataFrame:
    """Extract key metrics from records into a DataFrame."""
    data = []
    for record in records:
        iteration = record.get('iteration')
        if iteration is None:
            continue
        
        row = {
            'iteration': iteration,
            'total_loss': record.get('total_loss'),
            'loss_box_reg': record.get('loss_box_reg'),
            'loss_cls': record.get('loss_cls'),
            'loss_mask': record.get('loss_mask'),
            'loss_rpn_cls': record.get('loss_rpn_cls'),
            'loss_rpn_loc': record.get('loss_rpn_loc'),
            'lr': record.get('lr'),
            'mask_rcnn_accuracy': record.get('mask_rcnn/accuracy'),
            'fast_rcnn_cls_accuracy': record.get('fast_rcnn/cls_accuracy'),
            'segm_AP': record.get('segm/AP'),
            'segm_AP_droplet': record.get('segm/AP-droplet'),
            'segm_AP_ligament': record.get('segm/AP-ligament'),
            'segm_AP50': record.get('segm/AP50'),
            'segm_AP75': record.get('segm/AP75'),
            'bbox_AP': record.get('bbox/AP'),
            'bbox_AP_droplet': record.get('bbox/AP-droplet'),
            'bbox_AP_ligament': record.get('bbox/AP-ligament'),
            'bbox_AP50': record.get('bbox/AP50'),
            'bbox_AP75': record.get('bbox/AP75'),
        }
        data.append(row)
    
    df = pd.DataFrame(data)
    df['model'] = model_name
    return df

def create_comparison_plots(dennis_df: pd.DataFrame, claudia_df: pd.DataFrame, output_dir: Path):
    """Create comprehensive comparison plots."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Combine dataframes for easier plotting
    combined_df = pd.concat([dennis_df, claudia_df], ignore_index=True)
    
    # ============================================================================
    # 1. Total Loss Comparison
    # ============================================================================
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Dennis vs Claudia: Training Loss Comparison', fontsize=16, fontweight='bold')
    
    # Total loss
    ax = axes[0, 0]
    for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
        loss_data = df[['iteration', 'total_loss']].dropna()
        if len(loss_data) > 0:
            ax.plot(loss_data['iteration'], loss_data['total_loss'], 
                   label=model, linewidth=2, alpha=0.8)
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Total Loss')
    ax.set_title('Total Loss Over Training')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Individual loss components
    ax = axes[0, 1]
    loss_components = ['loss_cls', 'loss_mask', 'loss_box_reg', 'loss_rpn_cls', 'loss_rpn_loc']
    for component in loss_components:
        for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
            data = df[['iteration', component]].dropna()
            if len(data) > 0:
                ax.plot(data['iteration'], data[component], 
                       label=f'{model} - {component}', linewidth=1.5, alpha=0.7)
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Loss')
    ax.set_title('Individual Loss Components')
    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=8)
    ax.grid(True, alpha=0.3)
    
    # Learning rate comparison
    ax = axes[1, 0]
    for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
        lr_data = df[['iteration', 'lr']].dropna()
        if len(lr_data) > 0:
            ax.plot(lr_data['iteration'], lr_data['lr'], 
                   label=model, linewidth=2, alpha=0.8)
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Learning Rate')
    ax.set_title('Learning Rate Schedule')
    ax.legend()
    ax.set_yscale('log')
    ax.grid(True, alpha=0.3)
    
    # Accuracy comparison
    ax = axes[1, 1]
    for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
        acc_data = df[['iteration', 'mask_rcnn_accuracy']].dropna()
        if len(acc_data) > 0:
            ax.plot(acc_data['iteration'], acc_data['mask_rcnn_accuracy'], 
                   label=f'{model} - Mask R-CNN Accuracy', linewidth=2, alpha=0.8)
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Accuracy')
    ax.set_title('Mask R-CNN Accuracy')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'loss_comparison.png', dpi=300, bbox_inches='tight')
    print(f"Saved: {output_dir / 'loss_comparison.png'}")
    plt.close()
    
    # ============================================================================
    # 2. Validation Metrics (AP scores)
    # ============================================================================
    # Check if we have validation metrics
    dennis_has_val = dennis_df['segm_AP'].notna().any()
    claudia_has_val = claudia_df['segm_AP'].notna().any()
    
    if dennis_has_val or claudia_has_val:
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Dennis vs Claudia: Validation Metrics (AP Scores)', fontsize=16, fontweight='bold')
        
        # Segmentation AP
        ax = axes[0, 0]
        for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
            ap_data = df[['iteration', 'segm_AP']].dropna()
            if len(ap_data) > 0:
                ax.plot(ap_data['iteration'], ap_data['segm_AP'], 
                       label=f'{model} - segm/AP', linewidth=2, marker='o', markersize=4, alpha=0.8)
        ax.set_xlabel('Iteration')
        ax.set_ylabel('AP Score')
        ax.set_title('Segmentation AP (Overall)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Segmentation AP by class
        ax = axes[0, 1]
        for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
            for ap_type, label in [('segm_AP_droplet', 'Droplet'), ('segm_AP_ligament', 'Ligament')]:
                ap_data = df[['iteration', ap_type]].dropna()
                if len(ap_data) > 0:
                    ax.plot(ap_data['iteration'], ap_data[ap_type], 
                           label=f'{model} - {label}', linewidth=2, marker='o', markersize=4, alpha=0.8)
        ax.set_xlabel('Iteration')
        ax.set_ylabel('AP Score')
        ax.set_title('Segmentation AP by Class')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Bounding Box AP
        ax = axes[1, 0]
        for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
            ap_data = df[['iteration', 'bbox_AP']].dropna()
            if len(ap_data) > 0:
                ax.plot(ap_data['iteration'], ap_data['bbox_AP'], 
                       label=f'{model} - bbox/AP', linewidth=2, marker='o', markersize=4, alpha=0.8)
        ax.set_xlabel('Iteration')
        ax.set_ylabel('AP Score')
        ax.set_title('Bounding Box AP (Overall)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # AP50 and AP75
        ax = axes[1, 1]
        for model, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
            for ap_type, label in [('segm_AP50', 'AP50'), ('segm_AP75', 'AP75')]:
                ap_data = df[['iteration', ap_type]].dropna()
                if len(ap_data) > 0:
                    ax.plot(ap_data['iteration'], ap_data[ap_type], 
                           label=f'{model} - {label}', linewidth=2, marker='o', markersize=4, alpha=0.8)
        ax.set_xlabel('Iteration')
        ax.set_ylabel('AP Score')
        ax.set_title('Segmentation AP50 and AP75')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_dir / 'validation_metrics.png', dpi=300, bbox_inches='tight')
        print(f"Saved: {output_dir / 'validation_metrics.png'}")
        plt.close()
    else:
        print("Warning: No validation metrics found for either model")
    
    # ============================================================================
    # 3. Summary Statistics Table
    # ============================================================================
    fig, ax = plt.subplots(figsize=(14, 8))
    ax.axis('tight')
    ax.axis('off')
    
    # Calculate summary statistics
    summary_data = []
    
    for model_name, df in [('Dennis', dennis_df), ('Claudia', claudia_df)]:
        # Training loss stats
        train_losses = df['total_loss'].dropna()
        if len(train_losses) > 0:
            summary_data.append({
                'Model': model_name,
                'Metric': 'Training Loss (Final)',
                'Value': f"{train_losses.iloc[-1]:.4f}",
                'Min': f"{train_losses.min():.4f}",
                'Max': f"{train_losses.max():.4f}"
            })
        
        # Validation AP stats
        val_ap = df['segm_AP'].dropna()
        if len(val_ap) > 0:
            summary_data.append({
                'Model': model_name,
                'Metric': 'Validation segm/AP (Best)',
                'Value': f"{val_ap.max():.2f}",
                'Min': f"{val_ap.min():.2f}",
                'Max': f"{val_ap.max():.2f}"
            })
            summary_data.append({
                'Model': model_name,
                'Metric': 'Validation segm/AP (Final)',
                'Value': f"{val_ap.iloc[-1]:.2f}",
                'Min': f"{val_ap.min():.2f}",
                'Max': f"{val_ap.max():.2f}"
            })
        
        # Learning rate stats
        lrs = df['lr'].dropna()
        if len(lrs) > 0:
            summary_data.append({
                'Model': model_name,
                'Metric': 'Learning Rate (Initial)',
                'Value': f"{lrs.iloc[0]:.2e}",
                'Min': f"{lrs.min():.2e}",
                'Max': f"{lrs.max():.2e}"
            })
            summary_data.append({
                'Model': model_name,
                'Metric': 'Learning Rate (Final)',
                'Value': f"{lrs.iloc[-1]:.2e}",
                'Min': f"{lrs.min():.2e}",
                'Max': f"{lrs.max():.2e}"
            })
        
        # Iterations
        summary_data.append({
            'Model': model_name,
            'Metric': 'Total Iterations',
            'Value': f"{df['iteration'].max()}",
            'Min': f"{df['iteration'].min()}",
            'Max': f"{df['iteration'].max()}"
        })
    
    summary_df = pd.DataFrame(summary_data)
    table = ax.table(cellText=summary_df.values, colLabels=summary_df.columns,
                    cellLoc='center', loc='center', bbox=[0, 0, 1, 1])
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2)
    
    # Style the header
    for i in range(len(summary_df.columns)):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')
    
    plt.title('Summary Statistics: Dennis vs Claudia', fontsize=14, fontweight='bold', pad=20)
    plt.savefig(output_dir / 'summary_statistics.png', dpi=300, bbox_inches='tight')
    print(f"Saved: {output_dir / 'summary_statistics.png'}")
    plt.close()
    
    # ============================================================================
    # 4. Key Differences Highlight
    # ============================================================================
    fig, ax = plt.subplots(figsize=(14, 10))
    
    # Create a side-by-side comparison of key metrics
    metrics_to_compare = [
        ('total_loss', 'Final Training Loss', 'lower is better'),
        ('segm_AP', 'Best Validation segm/AP', 'higher is better'),
        ('lr', 'Initial Learning Rate', 'scale'),
    ]
    
    y_pos = np.arange(len(metrics_to_compare))
    bar_width = 0.35
    
    dennis_values = []
    claudia_values = []
    labels = []
    
    for metric_key, label, _ in metrics_to_compare:
        labels.append(label)
        dennis_val = dennis_df[metric_key].dropna()
        claudia_val = claudia_df[metric_key].dropna()
        
        if metric_key == 'total_loss':
            dennis_values.append(dennis_val.iloc[-1] if len(dennis_val) > 0 else np.nan)
            claudia_values.append(claudia_val.iloc[-1] if len(claudia_val) > 0 else np.nan)
        elif metric_key == 'segm_AP':
            dennis_values.append(dennis_val.max() if len(dennis_val) > 0 else np.nan)
            claudia_values.append(claudia_val.max() if len(claudia_val) > 0 else np.nan)
        elif metric_key == 'lr':
            dennis_values.append(dennis_val.iloc[0] if len(dennis_val) > 0 else np.nan)
            claudia_values.append(claudia_val.iloc[0] if len(claudia_val) > 0 else np.nan)
    
    # Normalize for display (since scales are very different)
    dennis_norm = []
    claudia_norm = []
    for i, (metric_key, _, _) in enumerate(metrics_to_compare):
        if metric_key == 'lr':
            # Log scale for LR
            dennis_norm.append(np.log10(dennis_values[i]) if not np.isnan(dennis_values[i]) else np.nan)
            claudia_norm.append(np.log10(claudia_values[i]) if not np.isnan(claudia_values[i]) else np.nan)
        else:
            # Normalize to 0-1 for comparison
            max_val = max(dennis_values[i], claudia_values[i]) if not (np.isnan(dennis_values[i]) or np.isnan(claudia_values[i])) else 1
            min_val = min(dennis_values[i], claudia_values[i]) if not (np.isnan(dennis_values[i]) or np.isnan(claudia_values[i])) else 0
            range_val = max_val - min_val if max_val != min_val else 1
            dennis_norm.append((dennis_values[i] - min_val) / range_val if not np.isnan(dennis_values[i]) else np.nan)
            claudia_norm.append((claudia_values[i] - min_val) / range_val if not np.isnan(claudia_values[i]) else np.nan)
    
    # Plot bars
    bars1 = ax.barh(y_pos - bar_width/2, dennis_norm, bar_width, label='Dennis', alpha=0.8, color='#FF6B6B')
    bars2 = ax.barh(y_pos + bar_width/2, claudia_norm, bar_width, label='Claudia', alpha=0.8, color='#4ECDC4')
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlabel('Normalized Value (for comparison)')
    ax.set_title('Key Differences: Dennis vs Claudia (Normalized Comparison)', fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='x')
    
    # Add value annotations
    for i, (d_val, c_val) in enumerate(zip(dennis_values, claudia_values)):
        if not np.isnan(d_val):
            ax.text(dennis_norm[i], y_pos[i] - bar_width/2, f'{d_val:.2e}' if d_val < 1 else f'{d_val:.2f}', 
                   va='center', ha='right' if dennis_norm[i] > claudia_norm[i] else 'left', fontsize=8)
        if not np.isnan(c_val):
            ax.text(claudia_norm[i], y_pos[i] + bar_width/2, f'{c_val:.2e}' if c_val < 1 else f'{c_val:.2f}', 
                   va='center', ha='right' if claudia_norm[i] > dennis_norm[i] else 'left', fontsize=8)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'key_differences.png', dpi=300, bbox_inches='tight')
    print(f"Saved: {output_dir / 'key_differences.png'}")
    plt.close()

def print_analysis(dennis_df: pd.DataFrame, claudia_df: pd.DataFrame):
    """Print detailed analysis of differences."""
    print("\n" + "="*80)
    print("DETAILED ANALYSIS: Dennis vs Claudia")
    print("="*80)
    
    # Training loss comparison
    print("\n1. TRAINING LOSS:")
    print("-" * 80)
    dennis_loss = dennis_df['total_loss'].dropna()
    claudia_loss = claudia_df['total_loss'].dropna()
    
    if len(dennis_loss) > 0:
        print(f"  Dennis:")
        print(f"    Initial: {dennis_loss.iloc[0]:.4f}")
        print(f"    Final:   {dennis_loss.iloc[-1]:.4f}")
        print(f"    Range:   {dennis_loss.min():.4f} - {dennis_loss.max():.4f}")
    
    if len(claudia_loss) > 0:
        print(f"  Claudia:")
        print(f"    Initial: {claudia_loss.iloc[0]:.4f}")
        print(f"    Final:   {claudia_loss.iloc[-1]:.4f}")
        print(f"    Range:   {claudia_loss.min():.4f} - {claudia_loss.max():.4f}")
    
    if len(dennis_loss) > 0 and len(claudia_loss) > 0:
        ratio = claudia_loss.iloc[-1] / dennis_loss.iloc[-1]
        print(f"  Ratio (Claudia/Dennis final loss): {ratio:.2f}x")
        if ratio < 0.5:
            print(f"  WARNING: Claudia's loss is {1/ratio:.1f}x LOWER than Dennis - this is a HUGE difference!")
    
    # Learning rate comparison
    print("\n2. LEARNING RATE:")
    print("-" * 80)
    dennis_lr = dennis_df['lr'].dropna()
    claudia_lr = claudia_df['lr'].dropna()
    
    if len(dennis_lr) > 0:
        print(f"  Dennis:")
        print(f"    Initial: {dennis_lr.iloc[0]:.2e}")
        print(f"    Final:   {dennis_lr.iloc[-1]:.2e}")
        print(f"    Range:   {dennis_lr.min():.2e} - {dennis_lr.max():.2e}")
    
    if len(claudia_lr) > 0:
        print(f"  Claudia:")
        print(f"    Initial: {claudia_lr.iloc[0]:.2e}")
        print(f"    Final:   {claudia_lr.iloc[-1]:.2e}")
        print(f"    Range:   {claudia_lr.min():.2e} - {claudia_lr.max():.2e}")
    
    if len(dennis_lr) > 0 and len(claudia_lr) > 0:
        ratio = dennis_lr.iloc[0] / claudia_lr.iloc[0]
        print(f"  Ratio (Dennis/Claudia initial LR): {ratio:.1f}x")
        if ratio > 100:
            print(f"  WARNING: Dennis uses {ratio:.0f}x HIGHER learning rate than Claudia!")
            print(f"     This could explain the performance difference.")
    
    # Validation metrics
    print("\n3. VALIDATION METRICS:")
    print("-" * 80)
    dennis_ap = dennis_df['segm_AP'].dropna()
    claudia_ap = claudia_df['segm_AP'].dropna()
    
    if len(dennis_ap) > 0:
        print(f"  Dennis - segm/AP:")
        print(f"    Best:  {dennis_ap.max():.2f}")
        print(f"    Final: {dennis_ap.iloc[-1]:.2f}")
    else:
        print(f"  Dennis - segm/AP: NO VALIDATION DATA")
    
    if len(claudia_ap) > 0:
        print(f"  Claudia - segm/AP:")
        print(f"    Best:  {claudia_ap.max():.2f}")
        print(f"    Final: {claudia_ap.iloc[-1]:.2f}")
    else:
        print(f"  Claudia - segm/AP: NO VALIDATION DATA")
    
    if len(dennis_ap) > 0 and len(claudia_ap) > 0:
        ratio = claudia_ap.max() / dennis_ap.max()
        print(f"  Ratio (Claudia/Dennis best AP): {ratio:.2f}x")
    
    # Key findings
    print("\n4. KEY FINDINGS:")
    print("-" * 80)
    findings = []
    
    # Training length comparison
    dennis_max_iter = dennis_df['iteration'].max()
    claudia_max_iter = claudia_df['iteration'].max()
    if dennis_max_iter > claudia_max_iter * 10:
        findings.append(f"Dennis trained MUCH longer: {dennis_max_iter} iterations vs Claudia's {claudia_max_iter}")
        findings.append("This makes direct comparison difficult - they're at different training stages")
    
    # Early training comparison
    if len(dennis_ap) > 0 and len(claudia_ap) > 0:
        # Find Dennis's AP at similar iteration to Claudia's first validation
        claudia_first_iter_idx = claudia_ap.index[0]
        claudia_first_iter = claudia_df.loc[claudia_first_iter_idx, 'iteration']
        claudia_first_ap = claudia_df.loc[claudia_first_iter_idx, 'segm_AP']
        
        # Find Dennis AP closest to Claudia's first validation iteration
        dennis_early = dennis_df[dennis_df['iteration'] <= claudia_first_iter]
        if len(dennis_early) > 0 and dennis_early['segm_AP'].notna().any():
            dennis_early_ap = dennis_early['segm_AP'].dropna().iloc[-1]
            dennis_early_iter = dennis_early[dennis_early['segm_AP'].notna()]['iteration'].iloc[-1]
            findings.append(f"Early training comparison:")
            findings.append(f"  At iteration ~{claudia_first_iter:.0f}: Claudia AP={claudia_first_ap:.2f} vs Dennis AP={dennis_early_ap:.2f} (at iter {dennis_early_iter:.0f})")
            if claudia_first_ap > dennis_early_ap + 20:
                findings.append(f"  -> Claudia performs MUCH better early in training ({claudia_first_ap - dennis_early_ap:.1f} AP points higher!)")
                findings.append(f"  -> This is why Dennis appears to underperform - it's much worse in early training")
        else:
            # Dennis hasn't been evaluated yet at this point
            findings.append(f"Early training: At iteration {claudia_first_iter:.0f}, Claudia already has AP={claudia_first_ap:.2f}")
            findings.append(f"  -> Dennis hasn't been evaluated yet at this stage (first eval at {dennis_df[dennis_df['segm_AP'].notna()]['iteration'].min():.0f})")
            findings.append(f"  -> This explains why Dennis appears to underperform - no early validation data")
    
    # Final performance
    if len(dennis_ap) > 0 and len(claudia_ap) > 0:
        dennis_best = dennis_ap.max()
        claudia_best = claudia_ap.max()
        findings.append(f"Best validation AP: Dennis={dennis_best:.2f}, Claudia={claudia_best:.2f}")
        if claudia_best > dennis_best:
            findings.append(f"  -> Claudia outperforms Dennis by {claudia_best - dennis_best:.2f} AP points")
        elif dennis_best > claudia_best:
            findings.append(f"  -> Dennis outperforms Claudia by {dennis_best - claudia_best:.2f} AP points (but trained much longer)")
    
    if len(dennis_loss) > 0 and len(claudia_loss) > 0:
        if claudia_loss.iloc[0] < dennis_loss.iloc[0] * 0.5:
            findings.append("Claudia starts with MUCH lower training loss (better initialization or different starting point)")
    
    if len(dennis_lr) > 0 and len(claudia_lr) > 0:
        if dennis_lr.iloc[0] > claudia_lr.iloc[0] * 100:
            findings.append(f"Dennis uses {dennis_lr.iloc[0]/claudia_lr.iloc[0]:.0f}x HIGHER learning rate than Claudia")
            findings.append("  -> High LR can cause instability, slower convergence, or worse final performance")
            findings.append("  -> This is likely the MAIN reason for the performance difference")
    
    if len(dennis_ap) == 0:
        findings.append("Dennis has NO validation metrics in training log - may need separate evaluation")
    
    for i, finding in enumerate(findings, 1):
        print(f"  {i}. {finding}")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    dennis_path = Path(r"D:\Experiments\AI\Dennis\metrics.json")
    claudia_path = Path(r"D:\Experiments\AI\Claudia\metrics.json")
    output_dir = Path(r"D:\Experiments\AI\Dennis_vs_Claudia_Visualization")
    
    print("Loading metrics files...")
    dennis_records = load_metrics_jsonl(dennis_path)
    claudia_records = load_metrics_jsonl(claudia_path)
    
    print(f"Loaded {len(dennis_records)} records from Dennis")
    print(f"Loaded {len(claudia_records)} records from Claudia")
    
    print("\nExtracting metrics...")
    dennis_df = extract_metrics(dennis_records, 'Dennis')
    claudia_df = extract_metrics(claudia_records, 'Claudia')
    
    print("\nCreating visualizations...")
    create_comparison_plots(dennis_df, claudia_df, output_dir)
    
    print("\nGenerating analysis...")
    print_analysis(dennis_df, claudia_df)
    
    print(f"\nDone! All visualizations saved to: {output_dir}")
