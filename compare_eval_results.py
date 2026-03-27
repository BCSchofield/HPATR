"""
Visualise evaluation results from evaluate_multiple_models.py CSV output.

Run this AFTER evaluate_multiple_models.py to get comparison charts.
Reads the CSV and training metrics.json files and produces:
  1. Bar chart of all key evaluation metrics (segm/AP, AP50, AP75, per-class, precision, recall)
  2. Training curves (loss + LR + validation AP) from metrics.json
  3. Summary table image

Output: D:\Experiments\AI\Dennis_vs_Claudia_Visualization\eval_comparison_<timestamp>\
"""

import json
import csv
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ============================================================================
# PATHS — edit these if your layout differs
# ============================================================================

CSV_PATH = Path(r"D:\Experiments\Validation_100\Evaluation\model_comparison_results.csv")
OUTPUT_DIR = Path(r"D:\Experiments\AI\Dennis_vs_Claudia_Visualization")

TRAINING_METRICS = {
    "Dennis":  Path(r"D:\Experiments\AI\Dennis\metrics.json"),
    "Claudia": Path(r"D:\Experiments\AI\Claudia\metrics.json"),
}

# Which models to include in the comparison (must match model_name column in CSV)
MODELS_TO_COMPARE = ["Dennis", "Claudia"]

# Colour palette
COLORS = {
    "Dennis":  "#FF6B6B",
    "Claudia": "#4ECDC4",
}

# ============================================================================
# HELPERS
# ============================================================================

def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    return df[df["model_name"].isin(MODELS_TO_COMPARE)].copy()


def load_training_metrics(json_path: Path) -> pd.DataFrame:
    """Load a Detectron2 JSONL metrics file into a DataFrame."""
    rows = []
    with open(json_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


# ============================================================================
# FIGURE 1 — Evaluation metrics bar chart
# ============================================================================

def plot_eval_metrics(df: pd.DataFrame, out_dir: Path):
    """
    Grouped bar charts of all useful evaluation metrics side-by-side.
    Layout: 3 sub-plots
      Top-left:  Segmentation AP suite (AP, AP50, AP75, AP-droplet, AP-ligament)
      Top-right: Precision & Recall
      Bottom:    BBox AP suite (secondary — mask model, but useful sanity check)
    """
    fig = plt.figure(figsize=(18, 10))
    fig.suptitle("Dennis vs Claudia — Validation_100 Evaluation", fontsize=15, fontweight="bold", y=1.01)

    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)
    ax_segm  = fig.add_subplot(gs[0, 0])
    ax_pr    = fig.add_subplot(gs[0, 1])
    ax_bbox  = fig.add_subplot(gs[1, 0])
    ax_notes = fig.add_subplot(gs[1, 1])
    ax_notes.axis("off")

    models = MODELS_TO_COMPARE
    x = np.arange(len(models))
    w = 0.55 / max(len(models) - 1, 1)  # bar width scales with model count
    colors = [COLORS.get(m, "#888888") for m in models]

    def grouped_bars(ax, metric_cols, labels, title, ylabel="AP (0–100)"):
        n = len(metric_cols)
        group_w = 0.7
        bar_w = group_w / n
        offsets = np.linspace(-(group_w - bar_w) / 2, (group_w - bar_w) / 2, n)
        x_pos = np.arange(len(models))

        alphas = np.linspace(0.30, 0.95, n)
        for i, (col, lbl) in enumerate(zip(metric_cols, labels)):
            vals = [float(df.loc[df["model_name"] == m, col].values[0])
                    if col in df.columns and not df.loc[df["model_name"] == m, col].empty
                    else 0.0
                    for m in models]
            bars = ax.bar(x_pos + offsets[i], vals, bar_w, label=lbl,
                          color=[COLORS.get(m, "#888") for m in models],
                          alpha=alphas[i])
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                        f"{v:.1f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

        ax.set_xticks(x_pos)
        ax.set_xticklabels(models, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.legend(fontsize=8, loc="lower right")
        ax.set_ylim(0, 100)
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # ── Segmentation AP ──────────────────────────────────────────────────────
    grouped_bars(
        ax_segm,
        ["segm/AP", "segm/AP50", "segm/AP75", "segm/AP-droplet", "segm/AP-ligament"],
        ["AP", "AP50", "AP75", "AP-droplet", "AP-ligament"],
        "Segmentation AP",
    )

    # ── Precision & Recall ───────────────────────────────────────────────────
    pr_cols  = ["precision", "recall"]
    pr_labels = ["Precision", "Recall"]
    n = len(pr_cols)
    group_w = 0.6
    bar_w = group_w / n
    offsets = np.linspace(-(group_w - bar_w) / 2, (group_w - bar_w) / 2, n)
    x_pos = np.arange(len(models))
    for i, (col, lbl) in enumerate(zip(pr_cols, pr_labels)):
        vals = [float(df.loc[df["model_name"] == m, col].values[0]) * 100
                if col in df.columns and not df.loc[df["model_name"] == m, col].empty
                else 0.0
                for m in models]
        bars = ax_pr.bar(x_pos + offsets[i], vals, bar_w, label=lbl,
                         color=[COLORS.get(m, "#888") for m in models],
                         alpha=0.75 + 0.1 * i, hatch=["", "//"][i])
        for bar, v in zip(bars, vals):
            ax_pr.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                       f"{v:.1f}", ha="center", va="bottom", fontsize=8, fontweight="bold")
    ax_pr.set_xticks(x_pos)
    ax_pr.set_xticklabels(models, fontsize=10)
    ax_pr.set_ylabel("Score × 100", fontsize=9)
    ax_pr.set_title("Precision & Recall\n(×100 for readability)", fontsize=11, fontweight="bold")
    ax_pr.legend(fontsize=9)
    ax_pr.set_ylim(0, 60)
    ax_pr.grid(axis="y", alpha=0.3)
    ax_pr.spines["top"].set_visible(False)
    ax_pr.spines["right"].set_visible(False)
    note = ("NOTE: Recall is the fraction of real\n"
            "objects actually detected. Critical\n"
            "for SMD/D10/D90 accuracy — missing\n"
            "droplets skew the size distribution.")
    ax_pr.text(0.98, 0.97, note, transform=ax_pr.transAxes, fontsize=7.5,
               va="top", ha="right", style="italic",
               bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

    # ── BBox AP (secondary) ──────────────────────────────────────────────────
    grouped_bars(
        ax_bbox,
        ["bbox/AP", "bbox/AP50", "bbox/AP75", "bbox/AP-droplet", "bbox/AP-ligament"],
        ["AP", "AP50", "AP75", "AP-droplet", "AP-ligament"],
        "Bounding Box AP  (secondary — sanity check)",
    )

    # ── Notes panel ──────────────────────────────────────────────────────────
    def _row(m, col, mult=1.0):
        try:
            return float(df.loc[df["model_name"] == m, col].values[0]) * mult
        except Exception:
            return float("nan")

    table_rows = []
    for m in models:
        table_rows.append([
            m,
            f"{_row(m, 'segm/AP'):.2f}",
            f"{_row(m, 'segm/AP50'):.2f}",
            f"{_row(m, 'segm/AP75'):.2f}",
            f"{_row(m, 'segm/AP-droplet'):.2f}",
            f"{_row(m, 'segm/AP-ligament'):.2f}",
            f"{_row(m, 'precision', 100):.1f}",
            f"{_row(m, 'recall', 100):.1f}",
        ])

    cols = ["Model", "AP", "AP50", "AP75", "AP-drop", "AP-lig", "Prec×100", "Rec×100"]
    tbl = ax_notes.table(cellText=table_rows, colLabels=cols,
                         cellLoc="center", loc="upper center",
                         bbox=[0, 0.45, 1.0, 0.5])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    for j in range(len(cols)):
        tbl[(0, j)].set_facecolor("#2C3E50")
        tbl[(0, j)].set_text_props(color="white", weight="bold")
    for i, m in enumerate(models, start=1):
        tbl[(i, 0)].set_facecolor(COLORS.get(m, "#eee"))
        tbl[(i, 0)].set_text_props(weight="bold")

    ax_notes.text(0.5, 0.35,
                  "What each metric means:\n\n"
                  "AP     — avg precision, IoU 0.5→0.95 (primary metric)\n"
                  "AP50   — IoU ≥ 0.5  (lenient; good if just 'finding' objects)\n"
                  "AP75   — IoU ≥ 0.75 (strict; mask shape accuracy)\n"
                  "AP-drop — AP for droplet class only\n"
                  "AP-lig  — AP for ligament class only\n"
                  "Prec   — fraction of detections that are real\n"
                  "Recall — fraction of real objects that are found",
                  transform=ax_notes.transAxes,
                  fontsize=8.5, va="top", ha="center",
                  fontfamily="monospace",
                  bbox=dict(boxstyle="round,pad=0.4", facecolor="#f8f8f8", alpha=0.9))

    plt.savefig(out_dir / "eval_metrics.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[OK] eval_metrics.png")


# ============================================================================
# FIGURE 2 — Training curves from metrics.json
# ============================================================================

def plot_training_curves(out_dir: Path):
    """
    4-panel training curves:
      TL: Total loss vs iteration
      TR: Validation segm/AP vs iteration (sparse — only logged at eval intervals)
      BL: Learning rate schedule
      BR: Mask R-CNN accuracy vs iteration
    """
    dfs = {}
    for name, path in TRAINING_METRICS.items():
        if name not in MODELS_TO_COMPARE:
            continue
        if not path.exists():
            print(f"[WARN] metrics.json not found for {name}: {path}")
            continue
        dfs[name] = load_training_metrics(path)

    if not dfs:
        print("[SKIP] No training metrics found — skipping training curves.")
        return

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("Dennis vs Claudia — Training Curves", fontsize=14, fontweight="bold")

    # Note: Claudia was fine-tuned from a checkpoint (~250 iters, tiny LR ~2.8e-7)
    # Dennis trained from COCO pretrained backbone for 78,000 iters
    # They are NOT directly comparable on training length
    caveat = ("Note: Claudia was fine-tuned from a checkpoint (~250 iters, LR ~3e-7).\n"
              "Dennis trained from scratch for 78,000 iters. Training length is NOT comparable.")
    fig.text(0.5, 0.97, caveat, ha="center", fontsize=8.5, style="italic", color="#555555")

    panel_cfg = [
        ("total_loss",          "Total Loss",              "Loss",      False, axes[0, 0]),
        ("lr",                  "Learning Rate Schedule",  "LR",        True,  axes[1, 0]),
        ("mask_rcnn/accuracy",  "Mask R-CNN Accuracy",     "Accuracy",  False, axes[1, 1]),
    ]

    for col, title, ylabel, log_scale, ax in panel_cfg:
        for name, df in dfs.items():
            if col not in df.columns:
                continue
            sub = df[["iteration", col]].dropna()
            if sub.empty:
                continue
            ax.plot(sub["iteration"], sub[col],
                    label=name, color=COLORS.get(name, "#888"),
                    linewidth=1.8, alpha=0.85)
        ax.set_xlabel("Iteration", fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        if log_scale:
            ax.set_yscale("log")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # Validation AP panel (may be empty or sparse)
    ax_ap = axes[0, 1]
    ap_cols = [("segm/AP", "segm/AP"), ("segm/AP-droplet", "AP-droplet"), ("segm/AP-ligament", "AP-ligament")]
    has_data = False
    for name, df in dfs.items():
        for col, label in ap_cols:
            if col not in df.columns:
                continue
            sub = df[["iteration", col]].dropna()
            if sub.empty:
                continue
            has_data = True
            ls = "-" if col == "segm/AP" else ("--" if "droplet" in col else ":")
            ax_ap.plot(sub["iteration"], sub[col],
                       label=f"{name} — {label}",
                       color=COLORS.get(name, "#888"),
                       linestyle=ls, linewidth=2, marker="o", markersize=4, alpha=0.85)
    ax_ap.set_xlabel("Iteration", fontsize=9)
    ax_ap.set_ylabel("AP", fontsize=9)
    ax_ap.set_title("Validation segm/AP over Training\n(logged at eval checkpoints)", fontsize=10, fontweight="bold")
    ax_ap.legend(fontsize=8)
    ax_ap.grid(alpha=0.3)
    ax_ap.spines["top"].set_visible(False)
    ax_ap.spines["right"].set_visible(False)
    if not has_data:
        ax_ap.text(0.5, 0.5, "No in-training validation AP found\nin metrics.json\n\nSee eval_metrics.png for\nfinal evaluation results.",
                   ha="center", va="center", transform=ax_ap.transAxes,
                   fontsize=10, color="#888888", style="italic")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(out_dir / "training_curves.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[OK] training_curves.png")


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 60)
    print("Model Comparison Visualiser")
    print("=" * 60)

    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found: {CSV_PATH}")
        print("Run evaluate_multiple_models.py first.")
        return

    ts = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    out_dir = OUTPUT_DIR / f"eval_comparison_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output → {out_dir}")

    df = load_csv(CSV_PATH)
    if df.empty:
        print(f"ERROR: No rows for models {MODELS_TO_COMPARE} found in CSV.")
        return

    print(f"\nModels found in CSV: {df['model_name'].tolist()}")
    print("\nKey metrics:")
    print(df[["model_name", "segm/AP", "segm/AP50", "segm/AP75",
              "segm/AP-droplet", "segm/AP-ligament", "precision", "recall"]].to_string(index=False))

    print("\nGenerating eval_metrics.png ...")
    plot_eval_metrics(df, out_dir)

    print("Generating training_curves.png ...")
    plot_training_curves(out_dir)

    print(f"\nDone. Charts saved to:\n  {out_dir}")


if __name__ == "__main__":
    main()
