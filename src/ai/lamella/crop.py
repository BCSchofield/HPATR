from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class OutletCrop:
    """Pixel coordinates of the outlet channel region in a full camera frame."""
    x: int = 0
    y: int = 0
    w: int = 256
    h: int = 256

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """Return the cropped sub-image (copy) clamped to frame bounds."""
        fh, fw = frame.shape[:2]
        x0 = max(0, self.x)
        y0 = max(0, self.y)
        x1 = min(fw, self.x + self.w)
        y1 = min(fh, self.y + self.h)
        return frame[y0:y1, x0:x1].copy()

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, d: dict) -> "OutletCrop":
        return cls(x=int(d.get("x", 0)), y=int(d.get("y", 0)),
                   w=int(d.get("w", 256)), h=int(d.get("h", 256)))
