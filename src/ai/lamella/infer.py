"""
Lamella segmenter — core inference interface.

Both StubSegmenter (used during GUI plumbing) and LamellaSegmenter (real model)
expose identical methods so all downstream code is arch-agnostic.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from .crop import OutletCrop


# ── Result contracts ──────────────────────────────────────────────────────────

@dataclass
class ThicknessResult:
    thickness_px: float
    thickness_mm: Optional[float]       # None when px/mm calibration not available
    probe_lines: list                   # [(y, x_left, x_right), ...] in crop coords
    ok: bool                            # False when mask has no detectable liquid


@dataclass
class Result:
    mask: np.ndarray                    # binary uint8, crop-sized (0=gas, 255=liquid)
    thickness: ThicknessResult
    crop_box: tuple                     # (x, y, w, h) in full-frame coords


# ── Thickness geometry ─────────────────────────────────────────────────────────

def thickness_from_mask(
    mask: np.ndarray,
    px_per_mm: float = 0.0,
    n_probes: int = 7,
) -> ThicknessResult:
    """
    Measure lamella thickness from a binary mask via median of horizontal probe rows.

    The outlet channel carries annular flow: liquid near both walls, gas core in
    the centre. On each probe row, we count all liquid pixels (both sides of the
    annulus). The median across N evenly-spaced rows gives a robust thickness_px.

    Args:
        mask:       Binary uint8 array (crop-sized). Non-zero = liquid.
        px_per_mm:  Calibration scale. 0.0 = skip mm conversion.
        n_probes:   Number of horizontal probe rows to sample.

    Returns:
        ThicknessResult with thickness_px, thickness_mm, probe_lines, ok.
    """
    h, w = mask.shape[:2]
    binary = (mask > 0).astype(np.uint8)

    # Sample rows evenly through the middle 60 % of the crop height to avoid
    # edge artefacts from the crop boundary itself.
    margin = int(h * 0.20)
    row_ys = np.linspace(margin, h - margin - 1, n_probes, dtype=int)

    widths: list[float] = []
    probe_lines: list[tuple] = []

    for y in row_ys:
        row = binary[y, :]
        liquid_cols = np.where(row > 0)[0]
        if liquid_cols.size == 0:
            continue
        # Total liquid width on this row (handles both sides of the annulus)
        x_left = int(liquid_cols[0])
        x_right = int(liquid_cols[-1])
        # Sum all liquid pixels to capture both walls properly
        total_liquid_px = float(np.sum(row))
        widths.append(total_liquid_px)
        probe_lines.append((int(y), x_left, x_right))

    if not widths:
        return ThicknessResult(
            thickness_px=0.0,
            thickness_mm=None,
            probe_lines=[],
            ok=False,
        )

    thickness_px = float(np.median(widths))
    thickness_mm = (thickness_px / px_per_mm) if px_per_mm > 0 else None

    return ThicknessResult(
        thickness_px=thickness_px,
        thickness_mm=thickness_mm,
        probe_lines=probe_lines,
        ok=True,
    )


# ── Stub segmenter (plausible fake mask — no model needed) ────────────────────

class StubSegmenter:
    """
    Returns a synthetic annular-flow mask for pipeline testing.
    Produces two vertical liquid bands (left and right walls of outlet channel)
    with a gas-core gap in the middle — mimics real lamella geometry.
    """

    def __init__(self, band_fraction: float = 0.18):
        # Each liquid band occupies this fraction of the crop width on each side
        self._band = band_fraction

    def segment(self, crop: np.ndarray) -> np.ndarray:
        """Return a binary uint8 mask same shape as crop."""
        h, w = crop.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        band_w = max(1, int(w * self._band))
        mask[:, :band_w] = 255           # left wall liquid
        mask[:, w - band_w:] = 255       # right wall liquid
        return mask

    def analyse_frame(
        self,
        frame: np.ndarray,
        crop_box: OutletCrop,
        px_per_mm: float = 0.0,
    ) -> Result:
        crop = crop_box.apply(frame)
        mask = self.segment(crop)
        thickness = thickness_from_mask(mask, px_per_mm)
        return Result(
            mask=mask,
            thickness=thickness,
            crop_box=(crop_box.x, crop_box.y, crop_box.w, crop_box.h),
        )


# ── Real segmenter (shell — populated in Phase 4) ─────────────────────────────

class LamellaSegmenter:
    """
    Wraps the trained U-Net model (smp or tiny arch).
    Interface identical to StubSegmenter.
    """

    def __init__(self):
        self._model = None
        self._device = "cpu"
        self._arch = "smp"

    @classmethod
    def load(cls, model_path: str, arch: str = "smp", device: str = "cpu") -> "LamellaSegmenter":
        """Load a trained model from a .pt checkpoint."""
        # Deferred import so the GUI side doesn't require torch at startup
        import torch
        from .model import build_model

        seg = cls()
        seg._arch = arch
        seg._device = device
        model = build_model(arch)
        checkpoint = torch.load(model_path, map_location=device)
        state = checkpoint.get("model_state_dict", checkpoint)
        model.load_state_dict(state)
        model.eval()
        model.to(device)
        seg._model = model
        return seg

    def segment(self, crop: np.ndarray) -> np.ndarray:
        """Run model inference on a crop. Returns binary uint8 mask."""
        if self._model is None:
            raise RuntimeError("Model not loaded — call LamellaSegmenter.load() first.")
        import torch
        import torch.nn.functional as F

        h, w = crop.shape[:2]
        # Normalise to float32 [0,1], add batch+channel dims
        img = crop.astype(np.float32)
        if img.max() > 1.0:
            img = img / (img.max() + 1e-6)
        tensor = torch.from_numpy(img).unsqueeze(0).unsqueeze(0).to(self._device)  # [1,1,H,W]

        with torch.no_grad():
            logits = self._model(tensor)           # [1,1,H,W]
            prob = torch.sigmoid(logits)
            pred = (prob > 0.5).squeeze().cpu().numpy().astype(np.uint8) * 255

        return pred

    def analyse_frame(
        self,
        frame: np.ndarray,
        crop_box: OutletCrop,
        px_per_mm: float = 0.0,
    ) -> Result:
        crop = crop_box.apply(frame)
        mask = self.segment(crop)
        thickness = thickness_from_mask(mask, px_per_mm)
        return Result(
            mask=mask,
            thickness=thickness,
            crop_box=(crop_box.x, crop_box.y, crop_box.w, crop_box.h),
        )
