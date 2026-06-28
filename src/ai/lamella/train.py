"""
Lamella segmentation training script.

Trains either the smp (transfer-learning) or tiny (from-scratch) U-Net
on annotated outlet-channel crops. Run with --arch smp or --arch tiny
to produce lamella_smp.pt or lamella_tiny.pt for the thesis comparison.

Usage (Windows GPU machine, "Detectron" conda env):
    python -m src.ai.lamella.train --arch smp --data D:\\Experiments\\LaminaData\\
    python -m src.ai.lamella.train --arch tiny --data D:\\Experiments\\LaminaData\\

TODO (Phase 4 — at home, with training data):
  - Confirm data directory structure (images/ + masks/ subfolders).
  - Set --epochs and --lr; start with defaults (30 epochs, lr=1e-3 for smp, 5e-4 for tiny).
  - The ProgressTracker below mirrors AI/Training_Analysis/train_detectron2.py conventions.
"""
from __future__ import annotations
import argparse
import os
import json
import time
import datetime
import numpy as np

# Training implementation deferred to Phase 4.
# Skeleton only — do not run yet.

DEFAULTS = {
    "smp":  {"lr": 1e-3,  "epochs": 40, "batch_size": 8},
    "tiny": {"lr": 5e-4,  "epochs": 60, "batch_size": 8},
}


class ProgressTracker:
    """Mirrors train_detectron2.py ProgressTracker: logs loss + val IoU, saves plots."""

    def __init__(self, output_dir: str, arch: str):
        self.output_dir = output_dir
        self.arch = arch
        self.train_losses: list[float] = []
        self.val_ious:     list[float] = []
        self._start = time.time()
        os.makedirs(os.path.join(output_dir, "plots"), exist_ok=True)

    def update(self, epoch: int, loss: float):
        self.train_losses.append(loss)
        elapsed = time.time() - self._start
        print(f"  Epoch {epoch:3d} | loss={loss:.4f} | elapsed={elapsed:.0f}s")

    def update_val(self, epoch: int, iou: float):
        self.val_ious.append(iou)
        print(f"  Epoch {epoch:3d} | val_iou={iou:.4f}")

    def save_metrics(self):
        path = os.path.join(self.output_dir, "metrics.json")
        with open(path, "w") as f:
            json.dump({"train_loss": self.train_losses, "val_iou": self.val_ious}, f, indent=2)

    def save_plot(self):
        try:
            import matplotlib.pyplot as plt
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
            ax1.plot(self.train_losses); ax1.set_title("Train Loss"); ax1.set_xlabel("Epoch")
            ax2.plot(self.val_ious);     ax2.set_title("Val IoU");    ax2.set_xlabel("Epoch")
            plt.tight_layout()
            plt.savefig(os.path.join(self.output_dir, "plots", "loss_curve.png"))
            plt.close()
        except Exception:
            pass  # matplotlib optional at train time


def dice_loss(pred, target, smooth=1.0):
    """Soft Dice loss (combined with BCE for stable training)."""
    import torch
    pred   = torch.sigmoid(pred)
    inter  = (pred * target).sum(dim=(2, 3))
    total  = (pred + target).sum(dim=(2, 3))
    return 1 - (2 * inter + smooth) / (total + smooth)


def combined_loss(pred, target):
    import torch
    import torch.nn.functional as F
    bce  = F.binary_cross_entropy_with_logits(pred, target, reduction="mean")
    dice = dice_loss(pred, target).mean()
    return 0.5 * bce + 0.5 * dice


def compute_iou(pred_logits, target):
    import torch
    pred_bin = (torch.sigmoid(pred_logits) > 0.5).float()
    inter = (pred_bin * target).sum().item()
    union = (pred_bin + target).clamp(0, 1).sum().item()
    return inter / (union + 1e-6)


def train(
    arch: str,
    data_dir: str,
    output_dir: str,
    epochs: int,
    lr: float,
    batch_size: int,
    device: str,
    resume: str | None = None,
):
    import torch
    from torch.utils.data import DataLoader, random_split
    from .model import build_model
    from .dataset import LamellaDataset

    print(f"\n=== Lamella Training | arch={arch} | device={device} ===")
    print(f"    data:   {data_dir}")
    print(f"    output: {output_dir}")
    print(f"    epochs={epochs}, lr={lr}, batch={batch_size}\n")

    os.makedirs(output_dir, exist_ok=True)

    ds = LamellaDataset(data_dir, augment=True)
    val_size  = max(1, int(len(ds) * 0.1))
    train_size = len(ds) - val_size
    train_ds, val_ds = random_split(ds, [train_size, val_size],
                                    generator=torch.Generator().manual_seed(42))
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,  num_workers=2)
    val_loader   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False, num_workers=2)

    model = build_model(arch).to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    tracker = ProgressTracker(output_dir, arch)

    start_epoch = 1
    if resume:
        ckpt = torch.load(resume, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        optimiser.load_state_dict(ckpt["optimizer_state_dict"])
        start_epoch = ckpt.get("epoch", 0) + 1
        print(f"Resumed from {resume} at epoch {start_epoch}")

    best_iou = 0.0
    for epoch in range(start_epoch, epochs + 1):
        model.train()
        epoch_loss = 0.0
        for imgs, masks in train_loader:
            imgs, masks = imgs.to(device), masks.to(device)
            optimiser.zero_grad()
            loss = combined_loss(model(imgs), masks)
            loss.backward()
            optimiser.step()
            epoch_loss += loss.item()
        tracker.update(epoch, epoch_loss / len(train_loader))

        # Validation every 5 epochs
        if epoch % 5 == 0 or epoch == epochs:
            model.eval()
            ious = []
            with torch.no_grad():
                for imgs, masks in val_loader:
                    imgs, masks = imgs.to(device), masks.to(device)
                    ious.append(compute_iou(model(imgs), masks))
            val_iou = float(np.mean(ious))
            tracker.update_val(epoch, val_iou)

            if val_iou > best_iou:
                best_iou = val_iou
                torch.save({
                    "epoch": epoch,
                    "arch": arch,
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimiser.state_dict(),
                    "val_iou": val_iou,
                }, os.path.join(output_dir, f"lamella_{arch}_best.pt"))

        # Checkpoint every 10 epochs
        if epoch % 10 == 0:
            torch.save({
                "epoch": epoch,
                "arch": arch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimiser.state_dict(),
            }, os.path.join(output_dir, f"lamella_{arch}_epoch{epoch}.pt"))

    # Save final model
    final_path = os.path.join(output_dir, f"lamella_{arch}.pt")
    torch.save({
        "epoch": epochs,
        "arch": arch,
        "model_state_dict": model.state_dict(),
    }, final_path)

    tracker.save_metrics()
    tracker.save_plot()
    print(f"\nTraining complete. Best val IoU: {best_iou:.4f}")
    print(f"Final model: {final_path}")
    return final_path


def _main():
    parser = argparse.ArgumentParser(description="Train lamella segmentation U-Net.")
    parser.add_argument("--arch",       default="smp",  choices=["smp", "tiny"])
    parser.add_argument("--data",       required=True,  help="Data dir with images/ and masks/.")
    parser.add_argument("--output",     default=None,   help="Output dir (default: auto-timestamped).")
    parser.add_argument("--epochs",     type=int,       default=None)
    parser.add_argument("--lr",         type=float,     default=None)
    parser.add_argument("--batch-size", type=int,       default=None)
    parser.add_argument("--resume",     default=None,   help="Resume from checkpoint .pt.")
    args = parser.parse_args()

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"

    defaults = DEFAULTS[args.arch]
    epochs     = args.epochs     or defaults["epochs"]
    lr         = args.lr         or defaults["lr"]
    batch_size = args.batch_size or defaults["batch_size"]

    ts = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    output_dir = args.output or os.path.join(args.data, f"lamella_{args.arch}_{ts}")

    train(
        arch=args.arch,
        data_dir=args.data,
        output_dir=output_dir,
        epochs=epochs,
        lr=lr,
        batch_size=batch_size,
        device=device,
        resume=args.resume,
    )


if __name__ == "__main__":
    _main()
