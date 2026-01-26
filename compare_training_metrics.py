"""
Compare training metrics from Dennis and Claudia models.
Extracts key statistics and outputs a CSV for graphing.
"""

import json
import csv
from pathlib import Path
from typing import Dict, List, Optional

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

def extract_key_metrics(records: List[Dict]) -> List[Dict]:
    """Extract key metrics from records for comparison."""
    extracted = []
    for record in records:
        iteration = record.get('iteration')
        if iteration is None:
            continue
        
        metrics = {
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
        extracted.append(metrics)
    return extracted

def create_comparison_csv(dennis_records: List[Dict], claudia_records: List[Dict], output_path: Path):
    """Create CSV comparing both models."""
    dennis_metrics = extract_key_metrics(dennis_records)
    claudia_metrics = extract_key_metrics(claudia_records)
    
    # Create dictionaries for quick lookup by iteration
    dennis_dict = {m['iteration']: m for m in dennis_metrics}
    claudia_dict = {m['iteration']: m for m in claudia_metrics}
    
    # Get all unique iterations
    all_iterations = sorted(set(list(dennis_dict.keys()) + list(claudia_dict.keys())))
    
    # Prepare CSV rows
    rows = []
    for iteration in all_iterations:
        dennis = dennis_dict.get(iteration, {})
        claudia = claudia_dict.get(iteration, {})
        
        row = {
            'iteration': iteration,
            # Dennis metrics
            'Dennis_total_loss': dennis.get('total_loss'),
            'Dennis_loss_box_reg': dennis.get('loss_box_reg'),
            'Dennis_loss_cls': dennis.get('loss_cls'),
            'Dennis_loss_mask': dennis.get('loss_mask'),
            'Dennis_loss_rpn_cls': dennis.get('loss_rpn_cls'),
            'Dennis_loss_rpn_loc': dennis.get('loss_rpn_loc'),
            'Dennis_lr': dennis.get('lr'),
            'Dennis_mask_rcnn_accuracy': dennis.get('mask_rcnn_accuracy'),
            'Dennis_fast_rcnn_cls_accuracy': dennis.get('fast_rcnn_cls_accuracy'),
            'Dennis_segm_AP': dennis.get('segm_AP'),
            'Dennis_segm_AP_droplet': dennis.get('segm_AP_droplet'),
            'Dennis_segm_AP_ligament': dennis.get('segm_AP_ligament'),
            'Dennis_segm_AP50': dennis.get('segm_AP50'),
            'Dennis_segm_AP75': dennis.get('segm_AP75'),
            'Dennis_bbox_AP': dennis.get('bbox_AP'),
            'Dennis_bbox_AP_droplet': dennis.get('bbox_AP_droplet'),
            'Dennis_bbox_AP_ligament': dennis.get('bbox_AP_ligament'),
            'Dennis_bbox_AP50': dennis.get('bbox_AP50'),
            'Dennis_bbox_AP75': dennis.get('bbox_AP75'),
            # Claudia metrics
            'Claudia_total_loss': claudia.get('total_loss'),
            'Claudia_loss_box_reg': claudia.get('loss_box_reg'),
            'Claudia_loss_cls': claudia.get('loss_cls'),
            'Claudia_loss_mask': claudia.get('loss_mask'),
            'Claudia_loss_rpn_cls': claudia.get('loss_rpn_cls'),
            'Claudia_loss_rpn_loc': claudia.get('loss_rpn_loc'),
            'Claudia_lr': claudia.get('lr'),
            'Claudia_mask_rcnn_accuracy': claudia.get('mask_rcnn_accuracy'),
            'Claudia_fast_rcnn_cls_accuracy': claudia.get('fast_rcnn_cls_accuracy'),
            'Claudia_segm_AP': claudia.get('segm_AP'),
            'Claudia_segm_AP_droplet': claudia.get('segm_AP_droplet'),
            'Claudia_segm_AP_ligament': claudia.get('segm_AP_ligament'),
            'Claudia_segm_AP50': claudia.get('segm_AP50'),
            'Claudia_segm_AP75': claudia.get('segm_AP75'),
            'Claudia_bbox_AP': claudia.get('bbox_AP'),
            'Claudia_bbox_AP_droplet': claudia.get('bbox_AP_droplet'),
            'Claudia_bbox_AP_ligament': claudia.get('bbox_AP_ligament'),
            'Claudia_bbox_AP50': claudia.get('bbox_AP50'),
            'Claudia_bbox_AP75': claudia.get('bbox_AP75'),
        }
        rows.append(row)
    
    # Write CSV
    fieldnames = [
        'iteration',
        # Dennis columns
        'Dennis_total_loss', 'Dennis_loss_box_reg', 'Dennis_loss_cls', 'Dennis_loss_mask',
        'Dennis_loss_rpn_cls', 'Dennis_loss_rpn_loc', 'Dennis_lr',
        'Dennis_mask_rcnn_accuracy', 'Dennis_fast_rcnn_cls_accuracy',
        'Dennis_segm_AP', 'Dennis_segm_AP_droplet', 'Dennis_segm_AP_ligament',
        'Dennis_segm_AP50', 'Dennis_segm_AP75',
        'Dennis_bbox_AP', 'Dennis_bbox_AP_droplet', 'Dennis_bbox_AP_ligament',
        'Dennis_bbox_AP50', 'Dennis_bbox_AP75',
        # Claudia columns
        'Claudia_total_loss', 'Claudia_loss_box_reg', 'Claudia_loss_cls', 'Claudia_loss_mask',
        'Claudia_loss_rpn_cls', 'Claudia_loss_rpn_loc', 'Claudia_lr',
        'Claudia_mask_rcnn_accuracy', 'Claudia_fast_rcnn_cls_accuracy',
        'Claudia_segm_AP', 'Claudia_segm_AP_droplet', 'Claudia_segm_AP_ligament',
        'Claudia_segm_AP50', 'Claudia_segm_AP75',
        'Claudia_bbox_AP', 'Claudia_bbox_AP_droplet', 'Claudia_bbox_AP_ligament',
        'Claudia_bbox_AP50', 'Claudia_bbox_AP75',
    ]
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"Comparison CSV created: {output_path}")
    print(f"  Dennis records: {len(dennis_metrics)}")
    print(f"  Claudia records: {len(claudia_metrics)}")
    print(f"  Total rows: {len(rows)}")
    
    # Print summary statistics
    dennis_final_segm = [m for m in dennis_metrics if m.get('segm_AP') is not None]
    claudia_final_segm = [m for m in claudia_metrics if m.get('segm_AP') is not None]
    
    if dennis_final_segm:
        dennis_best = max(dennis_final_segm, key=lambda x: x.get('segm_AP', 0))
        print(f"\nDennis - Best segm/AP: {dennis_best.get('segm_AP'):.2f} @ iteration {dennis_best.get('iteration')}")
    
    if claudia_final_segm:
        claudia_best = max(claudia_final_segm, key=lambda x: x.get('segm_AP', 0))
        print(f"Claudia - Best segm/AP: {claudia_best.get('segm_AP'):.2f} @ iteration {claudia_best.get('iteration')}")

if __name__ == "__main__":
    dennis_path = Path(r"D:\Experiments\AI\Dennis\metrics.json")
    claudia_path = Path(r"D:\Experiments\AI\Claudia\metrics.json")
    output_path = Path(r"D:\Experiments\AI\Dennis_vs_Claudia_Numbers.csv")
    
    print("Loading metrics files...")
    dennis_records = load_metrics_jsonl(dennis_path)
    claudia_records = load_metrics_jsonl(claudia_path)
    
    print(f"Loaded {len(dennis_records)} records from Dennis")
    print(f"Loaded {len(claudia_records)} records from Claudia")
    
    print("\nCreating comparison CSV...")
    create_comparison_csv(dennis_records, claudia_records, output_path)
    
    print(f"\nDone! CSV saved to: {output_path}")
