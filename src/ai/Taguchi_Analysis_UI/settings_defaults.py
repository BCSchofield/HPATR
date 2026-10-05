"""settings_defaults.py -- what every Settings field should contain, asked of the pipeline.

THE RULE: no default is typed in here. Each one is read LIVE from the pipeline (or, for the
two bin settings this app invented, from size_bins), so changing a default upstream changes
what the Settings tab proposes with no edit to this app. Each function returns a `Default`
(value + where it came from + anything the user should know), never a bare value, so the
tab can show WHY a field holds what it holds.

    score threshold   process_capture.DEFAULT_SCORE_THRESH
    stride            process_capture.DEFAULT_STRIDE        (+ what it means at each run's fps)
    CI stride         process_capture.auto_ci_stride()      PER RUN, from each run's own fps
    device            tiled_inference.auto_device()         (the pipeline's own choice)
    model folder      tiled_inference.default_model_dir()   + find_weights() + the iteration note
    bin width / max   size_bins (this app's own feature: no upstream default exists)

No Qt in here. Functions that ask the pipeline can raise SystemExit (the scripts exit on a
missing LaCie drive or weights); every one is caught and returned as `ok=False` with the
reason, never allowed to kill the window.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import eta, size_bins
from . import pipeline_spec as spec

UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Default:
    value: Any
    note: str = ""          # where it comes from / what it means for the selected runs
    warn: str = ""          # something the user should know before running
    ok: bool = True         # False: the pipeline could not be asked (value is a placeholder)


def _pc():
    return spec.rdc_module("process_capture")


def _ti():
    return spec.rdc_module("tiled_inference")


# ---- score threshold -----------------------------------------------------------------------------

def score_threshold() -> Default:
    v = _pc().DEFAULT_SCORE_THRESH
    return Default(v, "the pipeline's default (process_capture.DEFAULT_SCORE_THRESH). Results are written "
                      f"to droplets_{v:.2f}/, so a different value is a different set of folders.")


# ---- stride --------------------------------------------------------------------------------------------

def independent_stride(fps: float) -> int:
    """Smallest stride whose frames are at least one decorrelation time apart."""
    return max(1, math.ceil(_pc().DECORRELATION_S * fps - 1e-9))


def stride(fps_values: Iterable[float] = (), chosen: int | None = None) -> Default:
    """The pipeline's default stride, with what it means at the selected runs' frame rates."""
    pc = _pc()
    value = pc.DEFAULT_STRIDE
    use = chosen if chosen is not None else value
    decor_ms = pc.DECORRELATION_S * 1000
    notes, warn = [], ""
    fps_list = sorted({float(f) for f in fps_values if f})
    if fps_list:
        parts = []
        for f in fps_list:
            gap_ms = use / f * 1000
            need = independent_stride(f)
            parts.append(f"{f:g} fps: frames {gap_ms:.1f} ms apart"
                         + ("" if use >= need else f" (< {decor_ms:.1f} ms; stride {need} would be independent)"))
            if use < need and not warn:
                warn = (f"At {f:g} fps a stride of {use} puts frames closer than the {decor_ms:.1f} ms "
                        f"decorrelation time, so neighbouring frames share droplets. The confidence "
                        f"intervals adjust (CI stride), but the batch does more work for the same information.")
        notes.append("; ".join(parts))
    notes.append(f"decorrelation time {decor_ms:.1f} ms (process_capture.DECORRELATION_S)")
    return Default(value, "the pipeline's default (process_capture.DEFAULT_STRIDE). " + "; ".join(notes), warn)


# ---- CI stride -----------------------------------------------------------------------------------------

def ci_stride(fps_values: Iterable[float], stride_value: int) -> Default:
    """'auto' -- resolved PER RUN by process_capture.auto_ci_stride from that run's own fps,
    so there is no single global number to show; show what it comes to for the selected runs."""
    pc = _pc()
    fps_list = [float(f) for f in fps_values if f]
    if not fps_list:
        return Default("auto", "chosen per run from its frame rate (process_capture.auto_ci_stride); "
                               "select runs to see the values")
    counts: dict[int, int] = {}
    for f in fps_list:
        k = pc.auto_ci_stride(f, stride_value)
        counts[k] = counts.get(k, 0) + 1
    shown = ", ".join(f"{k} for {n} run{'s' if n != 1 else ''}" for k, n in sorted(counts.items()))
    return Default("auto", f"chosen per run from its frame rate (process_capture.auto_ci_stride): {shown}")


# ---- device --------------------------------------------------------------------------------------------

def cpu_inference_estimate(os_name: str | None = None) -> tuple[float, float] | None:
    """(seconds per frame, minutes per reference run) of CPU inference, from the ETA module's
    measured priors for this OS -- only where CPU is what was measured (macOS)."""
    os_name = os_name or platform.system()
    if os_name != "Darwin":
        return None
    typ = eta.priors_for(os_name)[("inference", None)][1]
    return typ / eta.REF_FRAMES, typ / 60


def device_warning(chosen: str | None, auto: str, os_name: str | None = None) -> str:
    """What the user should know about running inference on `chosen` (None = the pipeline's
    own choice, `auto`)."""
    os_name = os_name or platform.system()
    dev = chosen or auto
    if dev == "cpu":
        est = cpu_inference_estimate(os_name)
        if est:
            return (f"Inference on the CPU is slow: measured at about {est[0]:.1f} s/frame on a MacBook Air "
                    f"(~{est[1]:.0f} min per {eta.REF_FRAMES}-frame run, one light condition; heavier "
                    f"sprays will be slower). A campaign of 27 runs takes the best part of a day.")
        return ("No usable CUDA GPU was found, so inference runs on the CPU, which is several times "
                "slower. If this machine has a GPU, check the PyTorch install.")
    if dev == "mps":
        return ("MPS is experimental here: detectron2's support is patchy, and the pipeline never picks "
                "it automatically because a wrong answer is worse than a slow one. Compare a few frames "
                "against CPU before trusting a campaign to it.")
    if dev == "cuda" and chosen and auto != "cuda":
        return "The pipeline found no usable CUDA GPU on this machine, so choosing cuda will probably fail."
    return ""


def device(os_name: str | None = None) -> Default:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            v = _ti().auto_device()
    except BaseException as exc:                     # noqa: BLE001 -- SystemExit included
        return Default("cpu", f"could not ask tiled_inference.auto_device(): {type(exc).__name__}: {exc}",
                       ok=False)
    note = ("the pipeline's own choice (tiled_inference.auto_device): CUDA when a working GPU is present, "
            "otherwise CPU. MPS is never chosen automatically.")
    return Default(v, note, device_warning(None, v, os_name))


# ---- model folder --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelInfo:
    folder: Path | None
    weights: Path | None = None
    iteration: Any = None
    segm_ap: float | None = None
    note: str = ""
    warn: str = ""
    ok: bool = True


def _model_meta(folder: Path) -> dict:
    """The same two files tiled_inference itself reads for its provenance line:
    <Name>_summary.json (a promoted model) or model_best.json (a raw training output)."""
    for p in (folder / f"{folder.name}_summary.json", folder / "model_best.json"):
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
    return {}


def inspect_model(folder: Path) -> ModelInfo:
    """Describe a model folder, using the pipeline's own find_weights()."""
    folder = Path(folder)
    if not folder.is_dir():
        return ModelInfo(folder, note=f"{folder} is not a folder", ok=False)
    ti = _ti()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            weights = ti.find_weights(folder)
    except BaseException as exc:                     # noqa: BLE001 -- SystemExit
        return ModelInfo(folder, note=str(exc), ok=False)
    meta = _model_meta(folder)
    prod = getattr(ti, "PRODUCTION_MODEL", None)
    warn = (f"Not the promoted production model ({prod}): check this is the one you mean."
            if prod and folder.name != prod else "")
    ap = meta.get("segm_AP")
    return ModelInfo(folder, weights, meta.get("iteration"), float(ap) if isinstance(ap, (int, float)) else None,
                     note=f"weights: {weights.name}", warn=warn)


def model() -> ModelInfo:
    """The model the pipeline would use if none were chosen."""
    ti = _ti()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            folder = ti.default_model_dir()
    except BaseException as exc:                     # noqa: BLE001 -- SystemExit
        return ModelInfo(None, note=f"{exc} -- choose a model folder yourself", ok=False)
    info = inspect_model(folder)
    fell_back = buf.getvalue().strip()
    if fell_back:
        info = ModelInfo(info.folder, info.weights, info.iteration, info.segm_ap, info.note,
                         (info.warn + " " if info.warn else "") + fell_back.strip("() "), info.ok)
    return info


def describe_model(m: ModelInfo) -> str:
    if m.folder is None:
        return m.note
    bits = [m.note] if m.note else []
    if m.iteration is not None:
        bits.append(f"best checkpoint at iteration {m.iteration}")
    if m.segm_ap is not None:
        bits.append(f"segm AP {m.segm_ap:.1f} on composites (not on real frames)")
    return "; ".join(bits)


# ---- size bins (this app's own feature) --------------------------------------------------------------------

def bin_width() -> Default:
    return Default(size_bins.DEFAULT_WIDTH_UM, "this app's own default (no upstream value exists), "
                                                f"{size_bins.DEFAULT_WIDTH_UM:g} µm")


def bin_max() -> Default:
    return Default(size_bins.DEFAULT_MAX_UM, "this app's own default: one open-ended bin above it")


# ---- parsing what the user types ----------------------------------------------------------------------------

class Invalid(ValueError):
    pass


def parse_threshold(text: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise Invalid("a number between 0 and 1, e.g. 0.30") from None
    if not (0 < v <= 1):
        raise Invalid("between 0 (exclusive) and 1")
    return v


def parse_positive_int(text: str, what: str = "a whole number of frames, 1 or more") -> int:
    try:
        f = float(text)
    except ValueError:
        raise Invalid(what) from None
    if f != int(f) or f < 1:
        raise Invalid(what)
    return int(f)


def parse_ci_stride(text: str) -> int | None:
    """Blank or 'auto' -> None (the pipeline decides per run)."""
    t = text.strip().lower()
    return None if t in ("", "auto") else parse_positive_int(t)


def parse_um(text: str, what: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise Invalid(f"{what}: a number of micrometres") from None
    if not math.isfinite(v) or v <= 0:
        raise Invalid(f"{what}: more than 0")
    return v
