"""Quick script to check sweep progress"""
import csv
from pathlib import Path

# Find the most recent sweep folder
sweep_base = Path(r"D:\Experiments\AI\Hyperparameters")
sweep_folders = sorted([d for d in sweep_base.iterdir() if d.is_dir() and d.name.startswith("sweep_")], reverse=True)

if not sweep_folders:
    print("No sweep folders found!")
    exit(1)

latest_sweep = sweep_folders[0]
csv_path = latest_sweep / "sweep_results.csv"

print(f"Checking: {latest_sweep.name}")
print(f"CSV path: {csv_path}\n")

if not csv_path.exists():
    print("CSV file doesn't exist yet - no runs completed")
    exit(0)

rows = list(csv.DictReader(open(csv_path)))
print(f"Total runs in CSV: {len(rows)}\n")

for i, r in enumerate(rows, 1):
    print(f"{i}. {r['run_name'][:60]}")
    print(f"   LR={r['learning_rate']}, Final AP={r.get('final_val_ap', 'N/A')}, Best AP={r.get('best_val_ap', 'N/A')}")

print(f"\n{'='*60}")
print(f"Progress: {len(rows)} / 16 runs completed")
print(f"Remaining: {16 - len(rows)} runs")
