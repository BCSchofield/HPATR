"""
PyTorch Dataset for lamella segmentation training.

Expects a directory pair:
    images/   — grayscale PNG/TIFF frames (or crops)
    masks/    — binary PNG masks (0=gas, 255=liquid), same filename stem

Usage:
    from src.ai.lamella.dataset import LamellaDataset
    ds = LamellaDataset("path/to/data", augment=True)
"""
from __future__ import annotations
import os
import glob
import random
import numpy as np
import cv2

try:
    import torch
    from torch.utils.data import Dataset
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    Dataset = object   # type: ignore


class LamellaDataset(Dataset if _TORCH_AVAILABLE else object):
    """Pairs cropped outlet-channel images with their binary liquid masks."""

    def __init__(
        self,
        data_dir: str,
        image_subdir: str = "images",
        mask_subdir: str = "masks",
        augment: bool = True,
        target_size: tuple = (256, 256),
    ):
        self.augment = augment
        self.target_size = target_size  # (H, W)

        img_dir  = os.path.join(data_dir, image_subdir)
        mask_dir = os.path.join(data_dir, mask_subdir)

        exts = ("*.png", "*.tif", "*.tiff", "*.PNG", "*.TIF", "*.TIFF")
        img_files: list[str] = []
        for ext in exts:
            img_files.extend(glob.glob(os.path.join(img_dir, ext)))
        img_files = sorted(set(img_files))

        self.pairs: list[tuple[str, str]] = []
        for img_path in img_files:
            stem = os.path.splitext(os.path.basename(img_path))[0]
            # Accept mask as .png (preferred output of labelme_to_masks.py)
            mask_path = os.path.join(mask_dir, stem + ".png")
            if os.path.exists(mask_path):
                self.pairs.append((img_path, mask_path))

        if not self.pairs:
            raise FileNotFoundError(
                f"No matched image/mask pairs found in {data_dir}. "
                "Ensure images/ and masks/ subdirectories exist."
            )

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        import torch
        img_path, mask_path = self.pairs[idx]

        img  = cv2.imread(img_path,  cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)

        if img is None:
            raise IOError(f"Cannot read image: {img_path}")
        if mask is None:
            raise IOError(f"Cannot read mask: {mask_path}")

        # Resize to fixed target
        h, w = self.target_size
        img  = cv2.resize(img,  (w, h), interpolation=cv2.INTER_LINEAR)
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)

        if self.augment:
            img, mask = _augment(img, mask)

        # Normalise image to [0,1]; binarise mask to {0,1}
        img_t  = torch.from_numpy(img.astype(np.float32) / 255.0).unsqueeze(0)  # [1,H,W]
        mask_t = torch.from_numpy((mask > 127).astype(np.float32)).unsqueeze(0)  # [1,H,W]

        return img_t, mask_t


def _augment(img: np.ndarray, mask: np.ndarray):
    """Light augmentations: horizontal flip, brightness jitter, small rotation."""
    # Horizontal flip
    if random.random() < 0.5:
        img  = cv2.flip(img,  1)
        mask = cv2.flip(mask, 1)

    # Brightness jitter (image only)
    factor = random.uniform(0.8, 1.2)
    img = np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)

    # Small rotation (±5°)
    if random.random() < 0.3:
        h, w = img.shape
        angle = random.uniform(-5, 5)
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        img  = cv2.warpAffine(img,  M, (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REFLECT_101)
        mask = cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_NEAREST,
                               borderMode=cv2.BORDER_REFLECT_101)

    return img, mask
