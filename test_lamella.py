"""
Quick visual test for a trained lamella model.

Takes a FULL camera frame (TIFF or PNG), applies the outlet channel crop
automatically, runs inference, and saves a result image.

Usage:
    conda activate phantom
    python test_lamella.py --model <path/to/lamella_tiny_best.pt> --arch tiny --image <full_frame.tif>
    python test_lamella.py --model <path/to/lamella_smp_best.pt>  --arch smp  --image <full_frame.tif>

Output: saves  <image_stem>_result.png  next to the input image.
        Left panel: full frame with crop box drawn on it.
        Right panels: cropped region → mask → probability heatmap → overlay.
"""
import argparse
import os
import numpy as np
import cv2
from PIL import Image as PILImage

# Outlet channel crop — must match what was used during training
CROP_X, CROP_Y, CROP_W, CROP_H = 860, 829, 307, 583


def _load_any(path: str) -> np.ndarray:
    """Load TIFF (16-bit) or PNG/JPG, always return 8-bit grayscale."""
    img = np.array(PILImage.open(path))
    if img.dtype != np.uint8:
        lo, hi = img.min(), img.max()
        img = ((img.astype(np.float32) - lo) / max(hi - lo, 1) * 255).astype(np.uint8)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return img


def run(model_path: str, arch: str, image_path: str, threshold: float = 0.5):
    import torch
    from src.ai.lamella.model import build_model

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        else "cpu"
    )
    print(f"Device: {device}")

    # Load model
    model = build_model(arch).to(device)
    ckpt = torch.load(model_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    print(f"Loaded {arch} from {model_path}")
    print(f"  epoch {ckpt.get('epoch','?')}  best val IoU={ckpt.get('val_iou','?')}")

    # Load full frame
    full = _load_any(image_path)
    fh, fw = full.shape
    print(f"Full frame: {fw}×{fh}  |  crop: x={CROP_X} y={CROP_Y} w={CROP_W} h={CROP_H}")

    # Apply crop
    crop = full[CROP_Y:CROP_Y + CROP_H, CROP_X:CROP_X + CROP_W].copy()
    ch, cw = crop.shape

    # Inference
    img_256 = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LINEAR)
    tensor = torch.from_numpy(img_256.astype(np.float32) / 255.0).unsqueeze(0).unsqueeze(0).to(device)
    with torch.no_grad():
        prob = torch.sigmoid(model(tensor)).squeeze().cpu().numpy()

    # Binary mask + heatmap at crop size
    mask_256  = (prob > threshold).astype(np.uint8) * 255
    mask_crop = cv2.resize(mask_256, (cw, ch), interpolation=cv2.INTER_NEAREST)
    heat_crop = cv2.resize((prob * 255).astype(np.uint8), (cw, ch), interpolation=cv2.INTER_LINEAR)
    heat_color = cv2.applyColorMap(heat_crop, cv2.COLORMAP_INFERNO)

    # Overlay: green tint on liquid pixels
    crop_bgr = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    overlay   = crop_bgr.copy()
    overlay[mask_crop > 0] = (
        overlay[mask_crop > 0] * 0.45 + np.array([0, 200, 80]) * 0.55
    ).astype(np.uint8)

    # Full frame thumbnail with crop box drawn (scaled to crop height for alignment)
    scale     = ch / fh
    thumb_w   = int(fw * scale)
    thumb     = cv2.resize(cv2.cvtColor(full, cv2.COLOR_GRAY2BGR), (thumb_w, ch))
    bx, by    = int(CROP_X * scale), int(CROP_Y * scale)
    bx2, by2  = int((CROP_X + CROP_W) * scale), int((CROP_Y + CROP_H) * scale)
    cv2.rectangle(thumb, (bx, by), (bx2, by2), (0, 220, 255), 2)
    cv2.putText(thumb, "crop", (bx + 3, by + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1, cv2.LINE_AA)

    # Build panel: full-thumb | crop | mask | heatmap | overlay
    mask_bgr = cv2.cvtColor(mask_crop, cv2.COLOR_GRAY2BGR)
    panel = np.hstack([thumb, crop_bgr, mask_bgr, heat_color, overlay])

    labels = ["Full frame", "Crop (input)", "Mask", "Probability", "Overlay"]
    widths = [thumb_w, cw, cw, cw, cw]
    x = 0
    for label, w in zip(labels, widths):
        cv2.putText(panel, label, (x + 5, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        x += w

    stem    = os.path.splitext(os.path.basename(image_path))[0]
    out_dir = os.path.dirname(os.path.abspath(image_path))
    out     = os.path.join(out_dir, f"{stem}_{arch}_result.png")
    cv2.imwrite(out, panel)
    print(f"\nSaved: {out}")
    liquid_pct = mask_256.sum() / (255 * 256 * 256) * 100
    print(f"Liquid coverage: {liquid_pct:.1f}% of crop area")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test lamella model on a full camera frame (crop applied automatically)."
    )
    parser.add_argument("--model",     required=True,  help="Path to .pt checkpoint")
    parser.add_argument("--arch",      default="tiny", choices=["smp", "tiny"])
    parser.add_argument("--image",     required=True,  help="Full frame TIFF or PNG")
    parser.add_argument("--threshold", type=float,     default=0.5,
                        help="Sigmoid threshold for liquid/gas (default 0.5)")
    args = parser.parse_args()
    run(args.model, args.arch, args.image, args.threshold)
