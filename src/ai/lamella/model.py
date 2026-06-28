"""
Model factory for lamella segmentation.

  build_model("smp")  → segmentation_models_pytorch U-Net (MobileNetV2, ImageNet)
  build_model("tiny") → hand-written lightweight U-Net (no pretrained weights)

Both return an nn.Module with:
  input:  (B, 1, H, W) float32, normalised [0, 1]
  output: (B, 1, H, W) raw logits (apply sigmoid for probability)
"""
from __future__ import annotations
import torch
import torch.nn as nn
import torch.nn.functional as F


def build_model(arch: str = "smp") -> nn.Module:
    arch = arch.lower()
    if arch == "smp":
        return _build_smp()
    elif arch == "tiny":
        return _build_tiny()
    else:
        raise ValueError(f"Unknown arch '{arch}'. Choose 'smp' or 'tiny'.")


# ── smp U-Net (transfer learning) ────────────────────────────────────────────

def _build_smp() -> nn.Module:
    try:
        import segmentation_models_pytorch as smp
    except ImportError as e:
        raise ImportError(
            "segmentation_models_pytorch not installed. "
            "Run: pip install segmentation-models-pytorch"
        ) from e

    model = smp.Unet(
        encoder_name="mobilenet_v2",
        encoder_weights="imagenet",
        in_channels=1,         # grayscale shadowgraph input
        classes=1,             # binary: liquid vs gas
        activation=None,       # raw logits — sigmoid applied at inference time
    )
    return model


# ── Tiny hand-written U-Net ───────────────────────────────────────────────────

class _ConvBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.block(x)


class _TinyUNet(nn.Module):
    """Lightweight U-Net: 4-level encoder/decoder, channels 16→32→64→128."""

    def __init__(self):
        super().__init__()
        # Encoder
        self.enc1 = _ConvBlock(1,   16)
        self.enc2 = _ConvBlock(16,  32)
        self.enc3 = _ConvBlock(32,  64)
        self.enc4 = _ConvBlock(64, 128)
        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = _ConvBlock(128, 256)

        # Decoder
        self.up4 = nn.ConvTranspose2d(256, 128, 2, stride=2)
        self.dec4 = _ConvBlock(256, 128)
        self.up3 = nn.ConvTranspose2d(128, 64,  2, stride=2)
        self.dec3 = _ConvBlock(128, 64)
        self.up2 = nn.ConvTranspose2d(64,  32,  2, stride=2)
        self.dec2 = _ConvBlock(64,  32)
        self.up1 = nn.ConvTranspose2d(32,  16,  2, stride=2)
        self.dec1 = _ConvBlock(32,  16)

        self.out_conv = nn.Conv2d(16, 1, 1)  # 1×1 → raw logit

    def forward(self, x):
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        e4 = self.enc4(self.pool(e3))

        b = self.bottleneck(self.pool(e4))

        d4 = self.dec4(torch.cat([self.up4(b),  e4], dim=1))
        d3 = self.dec3(torch.cat([self.up3(d4), e3], dim=1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))

        return self.out_conv(d1)


def _build_tiny() -> nn.Module:
    return _TinyUNet()
