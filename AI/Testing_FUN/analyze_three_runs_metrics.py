import json
import re
from datetime import datetime
from pathlib import Path

import matplotlib

# Use non-interactive backend so this works both in GUI and headless runs
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def load_metrics(json_path: Path):
    """
    Load Detectron2-style JSONL metrics file and separate:
    - training iterations / total_loss / mask_rcnn accuracy
    - validation iterations / segm.AP / bbox.AP
    """
    train_iters = []
    train_loss = []
    train_mask_acc = []

    val_iters = []
    val_segm_ap = []
    val_bbox_ap = []
    val_segm_ap_droplet = []
    val_segm_ap_ligament = []

    with json_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)

            it = record.get("iteration")

            # Training stats
            if "total_loss" in record:
                train_iters.append(it)
                train_loss.append(float(record.get("total_loss", 0.0)))
                train_mask_acc.append(float(record.get("mask_rcnn/accuracy", 0.0)))

            # Validation stats are the entries which contain AP metrics
            if "segm/AP" in record or "bbox/AP" in record:
                if it is None:
                    continue
                val_iters.append(it)
                val_segm_ap.append(float(record.get("segm/AP", 0.0)))
                val_bbox_ap.append(float(record.get("bbox/AP", 0.0)))
                val_segm_ap_droplet.append(float(record.get("segm/AP-droplet", 0.0)))
                val_segm_ap_ligament.append(float(record.get("segm/AP-ligament", 0.0)))

    return {
        "train_iters": train_iters,
        "train_loss": train_loss,
        "train_mask_acc": train_mask_acc,
        "val_iters": val_iters,
        "val_segm_ap": val_segm_ap,
        "val_bbox_ap": val_bbox_ap,
        "val_segm_ap_droplet": val_segm_ap_droplet,
        "val_segm_ap_ligament": val_segm_ap_ligament,
    }


def discover_runs(script_dir: Path):
    """
    Discover all hyperparameter run folders in the script directory.
    Pattern: lr0_{lr}_anchors{anchors}_{timestamp}
    Examples:
      - lr0_0025_anchors8_16_32_64_128_2026_01_20_02_19_54
      - lr0_0010_anchors8_16_32_64_2026_01_20_00_12_21
    Returns: dict[label] -> Path to metrics.json
    """
    runs = {}
    # Match: lr0_{4-digit-lr}_anchors{numbers}_YYYY_MM_DD_HH_MM_SS
    pattern = re.compile(r"^lr0_(\d{4})_anchors(.+?)_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}$")

    for folder in script_dir.iterdir():
        if not folder.is_dir():
            continue

        # Skip hidden directories and plots folder
        if folder.name.startswith(".") or folder.name == "plots":
            continue

        match = pattern.match(folder.name)
        if not match:
            # Try alternative pattern in case format differs
            alt_pattern = re.compile(r"^lr0?\.?(\d+)_anchors(.+?)_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}$")
            match = alt_pattern.match(folder.name)
            if not match:
                continue

        metrics_file = folder / "metrics.json"
        if not metrics_file.exists():
            print(f"Warning: {folder.name} found but metrics.json missing, skipping")
            continue

        # Parse learning rate
        lr_str = match.group(1)
        if len(lr_str) == 4:
            # 4 digits: e.g., "0025" -> 0.0025, "0010" -> 0.001, "0100" -> 0.01
            lr = float(lr_str) / 10000.0
        elif len(lr_str) == 3:
            # 3 digits: e.g., "005" -> 0.005
            lr = float(lr_str) / 1000.0
        else:
            # Fallback: assume it's already in the right format or divide by 1000
            lr = float(lr_str) / 1000.0

        # Parse anchors (e.g., "8_16_32_64" -> [8, 16, 32, 64])
        anchors_str = match.group(2)
        anchors = [int(x) for x in anchors_str.split("_") if x.isdigit()]

        if not anchors:
            print(f"Warning: Could not parse anchors from {folder.name}, skipping")
            continue

        # Create clean label
        anchors_display = ",".join(map(str, anchors))
        label = f"lr{lr:.4f}_anchors[{anchors_display}]"

        runs[label] = metrics_file

    return runs


def summarize_validation(stats):
    """Return simple summary dict for best validation APs."""
    val_iters = stats["val_iters"]
    segm_ap = stats["val_segm_ap"]
    bbox_ap = stats["val_bbox_ap"]
    segm_ap_d = stats["val_segm_ap_droplet"]
    segm_ap_l = stats["val_segm_ap_ligament"]

    if not val_iters:
        return None

    best_idx = max(range(len(segm_ap)), key=lambda i: segm_ap[i])

    return {
        "best_iter": val_iters[best_idx],
        "best_segm_ap": segm_ap[best_idx],
        "best_bbox_ap": bbox_ap[best_idx],
        "best_segm_ap_droplet": segm_ap_d[best_idx],
        "best_segm_ap_ligament": segm_ap_l[best_idx],
        "final_segm_ap": segm_ap[-1] if segm_ap else 0.0,
        "final_bbox_ap": bbox_ap[-1] if bbox_ap else 0.0,
    }


def plot_runs(run_stats, out_path: Path):
    """
    run_stats: dict[label] -> metrics dict from load_metrics
    Creates comprehensive plots for all runs, using colormap for many runs.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    num_runs = len(run_stats)
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
        ax_loss.plot(
            stats["train_iters"],
            stats["train_loss"],
            label=label,
            linewidth=1.5,
            color=color,
            alpha=0.8,
        )
        ax_mask_acc.plot(
            stats["train_iters"],
            stats["train_mask_acc"],
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
        if stats["val_iters"]:
            ax_val_segm.plot(
                stats["val_iters"],
                stats["val_segm_ap"],
                marker="o",
                linestyle="-",
                label=label,
                color=color,
                alpha=0.8,
                markersize=6,
            )
            ax_val_bbox.plot(
                stats["val_iters"],
                stats["val_bbox_ap"],
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


def save_summary_csv(run_stats, summaries, out_path: Path):
    """Save summary to CSV file for easy analysis in Excel."""
    import csv

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Configuration",
            "Best_Iter",
            "Best_segm_AP",
            "Best_bbox_AP",
            "Best_segm_AP_droplet",
            "Best_segm_AP_ligament",
            "Final_segm_AP",
            "Final_bbox_AP",
        ])

        for label in sorted(run_stats.keys()):
            summary = summaries.get(label)
            if summary is None:
                writer.writerow([label, "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"])
            else:
                writer.writerow([
                    label,
                    summary["best_iter"],
                    f"{summary['best_segm_ap']:.4f}",
                    f"{summary['best_bbox_ap']:.4f}",
                    f"{summary['best_segm_ap_droplet']:.4f}",
                    f"{summary['best_segm_ap_ligament']:.4f}",
                    f"{summary['final_segm_ap']:.4f}",
                    f"{summary['final_bbox_ap']:.4f}",
                ])


def main():
    # Directory containing the sweep results (LR + Anchor sweep)
    input_dir = Path(r"d:\Experiments\AI\Hyperparameters\LR_Anchor_Sweep_Final")

    # Timestamp for output files
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    # Save outputs in the same folder as the input data
    output_root = input_dir

    # Automatically discover all run folders
    print("Discovering hyperparameter runs...")
    runs = discover_runs(input_dir)

    if not runs:
        print("No run folders found! Expected pattern: lr*_anchors*_YYYY_MM_DD_HH_MM_SS")
        return

    print(f"Found {len(runs)} run(s)")

    run_stats = {}
    print("\nLoading metrics:")
    for label, path in sorted(runs.items()):
        print(f"  {label}")
        try:
            stats = load_metrics(path)
            run_stats[label] = stats
        except Exception as e:
            print(f"    ERROR loading {path}: {e}")
            continue

    if not run_stats:
        print("No valid metrics files found!")
        return

    # Create comparison plot in this sweep's folder
    out_plot = output_root / f"hyperparameter_sweep_comparison_{timestamp}.png"
    plot_runs(run_stats, out_plot)
    print(f"\nSaved comparison plot to: {out_plot}")

    # Generate summaries
    summaries = {}
    for label, stats in run_stats.items():
        summary = summarize_validation(stats)
        summaries[label] = summary

    # Save CSV summary alongside the plot
    csv_path = output_root / f"hyperparameter_sweep_summary_{timestamp}.csv"
    save_summary_csv(run_stats, summaries, csv_path)
    print(f"Saved summary CSV to: {csv_path}")

    # Print ranked summary
    print("\n" + "=" * 80)
    print("BEST VALIDATION METRICS (ranked by segm/AP):")
    print("=" * 80)

    # Sort by best segm/AP
    ranked = sorted(
        summaries.items(),
        key=lambda x: x[1]["best_segm_ap"] if x[1] else -1,
        reverse=True,
    )

    for rank, (label, summary) in enumerate(ranked, 1):
        if summary is None:
            print(f"{rank:2d}. {label}: no validation entries found")
            continue

        print(
            f"{rank:2d}. {label}\n"
            f"    Best segm/AP: {summary['best_segm_ap']:.4f} (iter {summary['best_iter']})\n"
            f"    Best bbox/AP: {summary['best_bbox_ap']:.4f}\n"
            f"    Droplet AP:   {summary['best_segm_ap_droplet']:.4f}\n"
            f"    Ligament AP:  {summary['best_segm_ap_ligament']:.4f}\n"
        )

    # Print best overall
    if ranked and ranked[0][1]:
        best_label, best_summary = ranked[0]
        print("=" * 80)
        print(f"RECOMMENDED CONFIGURATION: {best_label}")
        print(f"  Best segm/AP: {best_summary['best_segm_ap']:.4f}")
        print("=" * 80)


if __name__ == "__main__":
    main()

