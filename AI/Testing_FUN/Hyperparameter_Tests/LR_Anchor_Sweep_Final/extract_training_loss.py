"""
Extract training loss vs iteration data from all sweep runs
Outputs a CSV file with columns: run_name, iteration, training_loss
"""

import json
import csv
from pathlib import Path
from datetime import datetime

def extract_training_loss_from_metrics(metrics_file: Path):
    """Extract training loss and iteration data from metrics.json file"""
    training_data = []
    
    with metrics_file.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                record = json.loads(line)
                
                # Only extract training entries (those with total_loss)
                if "total_loss" in record and "iteration" in record:
                    iteration = record["iteration"]
                    total_loss = record["total_loss"]
                    training_data.append({
                        "iteration": iteration,
                        "training_loss": total_loss
                    })
            except json.JSONDecodeError:
                continue
    
    return training_data

def main():
    # Directory containing all sweep runs
    # This script should be run from the sweep directory
    sweep_dir = Path("/Users/benschofield/Documents/GitHub/HPATR/AI/Testing_FUN/Hyperparameter_Tests/LR_Anchor_Sweep_Final")
    
    # Output CSV file
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    output_csv = sweep_dir / f"training_loss_all_runs_{timestamp}.csv"
    
    all_data = []
    
    print("Extracting training loss data from all runs...")
    
    # Find all run directories (folders starting with "lr")
    run_dirs = [d for d in sweep_dir.iterdir() 
                if d.is_dir() and d.name.startswith("lr")]
    
    print(f"Found {len(run_dirs)} run directories")
    
    for run_dir in sorted(run_dirs):
        run_name = run_dir.name
        metrics_file = run_dir / "metrics.json"
        
        if not metrics_file.exists():
            print(f"  Warning: {run_name} - metrics.json not found, skipping")
            continue
        
        print(f"  Processing: {run_name}")
        
        try:
            training_data = extract_training_loss_from_metrics(metrics_file)
            
            if not training_data:
                print(f"    Warning: No training loss data found in {run_name}")
                continue
            
            # Add run_name to each entry
            for entry in training_data:
                entry["run_name"] = run_name
            
            all_data.extend(training_data)
            print(f"    Extracted {len(training_data)} training loss entries")
            
        except Exception as e:
            print(f"    Error processing {run_name}: {e}")
            continue
    
    # Write to CSV in wide format (better for Excel line charts)
    if not all_data:
        print("No training loss data found in any run!")
        return
    
    print(f"\nOrganizing data into wide format for Excel...")
    
    # Group data by run_name
    runs_data = {}
    for entry in all_data:
        run_name = entry["run_name"]
        if run_name not in runs_data:
            runs_data[run_name] = []
        runs_data[run_name].append((entry["iteration"], entry["training_loss"]))
    
    # Sort each run's data by iteration
    for run_name in runs_data:
        runs_data[run_name].sort(key=lambda x: x[0])
    
    # Get all unique iterations across all runs
    all_iterations = set()
    for run_data in runs_data.values():
        all_iterations.update(iter for iter, _ in run_data)
    all_iterations = sorted(all_iterations)
    
    print(f"  Found {len(all_iterations)} unique iterations")
    print(f"  Found {len(runs_data)} runs")
    
    # Create wide format: iteration column + one column per run
    print(f"\nWriting to CSV in wide format...")
    
    with output_csv.open("w", newline="") as f:
        # Create header: iteration + run names
        fieldnames = ["iteration"] + sorted(runs_data.keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # Write data row by row (one iteration per row)
        for iteration in all_iterations:
            row = {"iteration": iteration}
            
            # Add training loss for each run at this iteration (or empty if not available)
            for run_name in sorted(runs_data.keys()):
                # Find loss for this iteration in this run
                loss_value = None
                for iter_val, loss_val in runs_data[run_name]:
                    if iter_val == iteration:
                        loss_value = loss_val
                        break
                
                row[run_name] = loss_value if loss_value is not None else ""
            
            writer.writerow(row)
    
    print(f"✓ Successfully created: {output_csv}")
    print(f"  Total entries: {len(all_data)}")
    print(f"  Unique runs: {len(set(d['run_name'] for d in all_data))}")

if __name__ == "__main__":
    main()
