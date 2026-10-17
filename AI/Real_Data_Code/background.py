"""Sizer 3.1.0's rolling background (plan 2026-10-17, Phase 2). numpy + OpenCV only (the lab PC has no scipy).

The background up to 3.0.0 is ONE per-pixel median over the whole run (raw/background_median.tiff). A drop that lands
on the window part-way through stays in every later frame as dark "liquid" (CCD 123534: a far-out-of-focus drop from
frame ~300 on, and the specks inside it read 332-358 um). Here each block of BLOCK frames gets its own background,
the per-pixel median of the frames within +/- HALF of the block's centre (51 frames, ~1.3 s at 390 fps / stride 10),
so a drop that lands is divided out within about HALF frames of landing, and slow changes in the light go with it.
Spray is transient and medians away exactly as in the whole-run median.

Stored in the run's ANALYSIS folder (never raw/): <run>/shadowgraph/analysis/background_rolling/
    bg_000.png ...   16-bit lossless (the median of 51 integer frames is an integer)
    index.json       the blocks, which frames each covers, and the window events: places where the background
                     darkened (a drop landed on the window) or cleared between one block and the next
The AI is not affected (it is fed the raw 8-bit renders), so a run moves to it by re-measuring only."""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

ROLLING_VERSION = "1.0"
DIRNAME = "background_rolling"
BLOCK = 25          # frames per background (0.64 s at 390 fps / stride 10)
HALF = 25           # each block's background: the median of the frames within +/- HALF of its centre
EVENT_DARKER = 0.85  # a window event: the background darkens to this share of the block before (a drop landed) ...
EVENT_CLEARER = 1.15  # ... or brightens by this much (one slid off or dried)
EVENT_MIN_PX = 50   # ... over at least this many connected pixels
EVENT_MAX_EXTENT = 400  # ... and compact (a drop, not the spray's own edge moving): at most this many px across


def frame_stems(sb_dir: Path) -> list[str]:
    """The run's frames in time order (frame_0000_n-1, frame_0001_n9, ...: their names sort in time)."""
    return sorted(p.stem for p in Path(sb_dir).glob("*.tiff") if not p.name.startswith("._"))


def rolling_dir_for(run_root: Path) -> Path:
    return Path(run_root) / "shadowgraph" / "analysis" / DIRNAME


def _events(prev: np.ndarray, cur: np.ndarray, k: int, first_stem: str) -> list[dict]:
    r = cur.astype(np.float32) / np.maximum(prev.astype(np.float32), 1.0)
    out = []
    for kind, m in (("landed", r < EVENT_DARKER), ("cleared", r > EVENT_CLEARER)):
        n, lab, st, _c = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        for i in range(1, n):
            x, y, w, h, a = (int(v) for v in st[i])
            if a < EVENT_MIN_PX or max(w, h) > EVENT_MAX_EXTENT:
                continue
            out.append({"block": k, "from_frame": first_stem, "kind": kind, "x": x + w // 2, "y": y + h // 2,
                        "w": w, "h": h, "area_px": a, "ratio": round(float(np.median(r[lab == i])), 3)})
    return out


DROP_SAME_PX = 80   # landed events this close (centre to centre) are one drop growing over several blocks


def window_drops(events: list[dict]) -> list[dict]:
    """The landed events grouped into drops: one drop that grows over several blocks is one entry, with where it
    is, the frame it was first seen from, and how many blocks it grew in."""
    drops: list[dict] = []
    for e in sorted((e for e in events if e["kind"] == "landed"), key=lambda e: e["block"]):
        for d in drops:
            if (d["x"] - e["x"]) ** 2 + (d["y"] - e["y"]) ** 2 <= DROP_SAME_PX ** 2:
                d["blocks"] += 1
                d["area_px"] = max(d["area_px"], e["area_px"])
                d["darkest_ratio"] = min(d["darkest_ratio"], e["ratio"])
                break
        else:
            drops.append({"x": e["x"], "y": e["y"], "first_frame": e["from_frame"], "blocks": 1,
                          "area_px": e["area_px"], "darkest_ratio": e["ratio"]})
    return drops


def build_rolling(sb_dir: Path, out_dir: Path, block: int = BLOCK, half: int = HALF, log=print) -> dict:
    """Write the block backgrounds and index.json; returns the index. Reads every frame once (a sliding window of at
    most 2 * half + 1 frames is held in memory, ~240 MB at 2048 x 1152)."""
    sb_dir, out_dir = Path(sb_dir), Path(out_dir)
    stems = frame_stems(sb_dir)
    n = len(stems)
    if not n:
        raise RuntimeError(f"no 16-bit frames in {sb_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    nb = math.ceil(n / block)
    held: dict[int, np.ndarray] = {}
    blocks, events, prev = [], [], None
    for k in range(nb):
        first, last = k * block, min(n, (k + 1) * block) - 1
        centre = (first + last) // 2
        lo, hi = max(0, centre - half), min(n, centre + half + 1)
        for i in [i for i in held if i < lo]:
            del held[i]
        for i in range(lo, hi):
            if i not in held:
                f = cv2.imread(str(sb_dir / f"{stems[i]}.tiff"), cv2.IMREAD_UNCHANGED)
                if f is None:
                    raise RuntimeError(f"unreadable frame {stems[i]}")
                held[i] = f
        bg = np.median(np.stack([held[i] for i in range(lo, hi)]), axis=0)
        bg16 = np.clip(np.rint(bg), 0, 65535).astype(np.uint16)
        name = f"bg_{k:03d}.png"
        cv2.imwrite(str(out_dir / name), bg16)
        if prev is not None:
            events += _events(prev, bg16, k, stems[first])
        prev = bg16
        blocks.append({"k": k, "first": stems[first], "last": stems[last], "centre": stems[centre],
                       "frames_in_median": hi - lo, "file": name})
        log(f"  rolling background {k + 1}/{nb}: frames {first}-{last}, median of {hi - lo}")
    index = {"version": ROLLING_VERSION, "block": block, "half": half, "n_frames": n, "stems": stems,
             "blocks": blocks, "window_events": events, "window_drops": window_drops(events),
             "definition": f"per-pixel median of the frames within +/- {half} of each block of {block} frames' centre; "
                           f"a window event is a compact place (>= {EVENT_MIN_PX} px, <= {EVENT_MAX_EXTENT} px across) "
                           f"where the background darkened below {EVENT_DARKER:g}x (landed) or brightened above "
                           f"{EVENT_CLEARER:g}x (cleared) from one block to the next"}
    (out_dir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    drops = index["window_drops"]
    log(f"  rolling background: {nb} blocks of {block} frames written to {out_dir}; drops landed on the window: "
        f"{len(drops)}" + (" (first seen from " + ", ".join(d["first_frame"] for d in drops) + ")" if drops else ""))
    return index


class Rolling:
    """The run's rolling background: for_stem(stem) is the background to divide that frame by."""

    def __init__(self, out_dir: Path):
        self.dir = Path(out_dir)
        self.index = json.loads((self.dir / "index.json").read_text(encoding="utf-8"))
        b = self.index["block"]
        self.block_of = {s: i // b for i, s in enumerate(self.index["stems"])}
        self._k: int | None = None
        self._bg = np.zeros((1, 1), np.float32)

    def for_stem(self, stem: str) -> np.ndarray:
        k = self.block_of[stem]
        if self._k != k:
            bg = cv2.imread(str(self.dir / self.index["blocks"][k]["file"]), cv2.IMREAD_UNCHANGED)
            if bg is None:
                raise RuntimeError(f"unreadable rolling background {self.index['blocks'][k]['file']} in {self.dir}")
            self._k, self._bg = k, bg.astype(np.float32)
        return self._bg

    def provenance(self) -> dict:
        ev = self.index.get("window_events", [])
        drops = self.index.get("window_drops", window_drops(ev))
        return {"background_kind": "rolling", "background_rolling": str(self.dir),
                "background_block": self.index["block"], "background_half": self.index["half"],
                "background_rolling_version": self.index["version"],
                "window_events_landed": sum(e["kind"] == "landed" for e in ev),
                "window_events_cleared": sum(e["kind"] == "cleared" for e in ev),
                "window_drops": len(drops),
                "window_drops_first_frames": [d["first_frame"] for d in drops]}


def ensure_rolling(sb_dir: Path, out_dir: Path, log=print) -> Rolling:
    """The run's rolling background, built if it is missing or no longer matches the frames (another frame set, or
    another BLOCK / HALF / version)."""
    out_dir = Path(out_dir)
    idx_path = out_dir / "index.json"
    stems = frame_stems(sb_dir)
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            if (idx.get("version") == ROLLING_VERSION and idx.get("block") == BLOCK and idx.get("half") == HALF
                    and idx.get("stems") == stems
                    and all((out_dir / b["file"]).exists() for b in idx["blocks"])):
                log(f"  rolling background: reusing {out_dir}")
                return Rolling(out_dir)
        except (OSError, ValueError, KeyError):
            pass
    build_rolling(sb_dir, out_dir, log=log)
    return Rolling(out_dir)


def auto_dir(run_root: Path, sb_dir: Path) -> Path | None:
    """Where a run's rolling background lives when the frames are that run's own extracted sequence; None for a set
    of frames that is not a time series (the hand-labelled validation frames), which keeps the static background."""
    run_root, sb_dir = Path(run_root), Path(sb_dir)
    own = run_root / "shadowgraph" / "raw" / "frames" / "16bit"
    if (run_root / "shadowgraph" / "raw" / "extraction_metadata.json").exists() and own.exists() \
            and sb_dir.resolve() == own.resolve():
        return rolling_dir_for(run_root)
    return None
