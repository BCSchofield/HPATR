"""The scenario's settings file: one commented YAML per scenario, read into SI units (PLAN.md, "The settings file").

Every number that describes the rig is tagged with how it is known:

    flow_sccm: !measured 8995       measured on the rig, or in a dated measurement
    speed_m_s: !estimated 6         an estimate or a literature value, until it is measured
    diameter_mm: !design 6          a design choice (Ben's, or a placeholder to sweep)

The tags go into Scenario.basis (dotted path -> (basis, value)), so the report lists every estimated input.
Untagged numbers are run controls (time step, droplets per size, seed), not claims about the rig.

Coordinates (Ben, 2026-10-23): x along the 300 mm length, 0 at the left wall (the outlet), up to the right wall (the
inlet); y across the 200 mm; z up from the floor. Walls: left / right (x), front / back (y), floor / lid (z).

A sweep is a list of {path, values}: one run per combination, e.g. path: inlets.0.diameter_mm (the first inlet).
"""
from __future__ import annotations

import copy
import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from . import physics
from .flow import _dot

ROOT = Path(__file__).resolve().parents[1]          # the Flow Visualisation folder: relative paths start here
BASES = {"!measured": "measured", "!estimated": "estimated", "!design": "design choice"}
WALLS = {"left": (0, 0), "right": (0, 1), "front": (1, 0), "back": (1, 1), "floor": (2, 0), "lid": (2, 1)}
AXES = "xyz"


class SettingsError(ValueError):
    pass


class Tagged:
    __slots__ = ("value", "basis")

    def __init__(self, value, basis):
        self.value, self.basis = value, basis


class _Loader(yaml.SafeLoader):
    pass


def _tag_constructor(basis):
    def construct(loader, node):
        if isinstance(node, yaml.ScalarNode):
            value = yaml.safe_load(node.value) if node.value.strip() else None
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        else:
            value = loader.construct_mapping(node, deep=True)
        return Tagged(value, basis)
    return construct


for _tag, _basis in BASES.items():
    _Loader.add_constructor(_tag, _tag_constructor(_basis))


def _strip(obj, path, basis):
    """The plain values, with each tagged value's basis recorded under its dotted path."""
    if isinstance(obj, Tagged):
        basis[path] = (obj.basis, _strip(obj.value, path, {}))
        return basis[path][1]
    if isinstance(obj, dict):
        return {k: _strip(v, f"{path}.{k}" if path else str(k), basis) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip(v, f"{path}.{i}", basis) for i, v in enumerate(obj)]
    return obj


def _replaced(over: dict, path: str = ""):
    """The paths a file replaces outright when merged over its base (a value that is not a mapping)."""
    for k, v in over.items():
        p = f"{path}.{k}" if path else str(k)
        if isinstance(v, dict):
            yield from _replaced(v, p)
        else:
            yield p


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def read_yaml(path: Path, _seen=()) -> tuple[dict, dict]:
    """(plain settings, basis) from a settings file. A file may start from another with `base: <file>` (relative
    to it) and give only what differs: mappings merge, anything else (a number, a list) replaces the base's."""
    path = Path(path).resolve()
    if path in _seen:
        raise SettingsError(f"{path.name}: its base files loop back to it")
    with open(path, encoding="utf-8") as fh:
        raw = yaml.load(fh, Loader=_Loader)
    if not isinstance(raw, dict):
        raise SettingsError(f"{path}: not a settings file (expected a mapping at the top)")
    basis: dict = {}
    plain = _strip(raw, "", basis)
    base = plain.pop("base", None)
    if base is None:
        return plain, basis
    b_plain, b_basis = read_yaml(path.parent / str(base), _seen + (path,))
    gone = list(_replaced(plain))
    b_basis = {k: v for k, v in b_basis.items() if not any(k == g or k.startswith(g + ".") for g in gone)}
    return _merge(b_plain, plain), {**b_basis, **basis}


def base_files(path: Path) -> list[Path]:
    """The chain of base files a settings file starts from (nearest first)."""
    out, p = [], Path(path).resolve()
    while True:
        with open(p, encoding="utf-8") as fh:
            raw = yaml.load(fh, Loader=_Loader) or {}
        b = raw.get("base") if isinstance(raw, dict) else None
        if b is None:
            return out
        p = (p.parent / str(b)).resolve()
        out.append(p)


# ---- the scenario ----------------------------------------------------------------------------------------------

@dataclass
class Port:
    """An inlet or outlet: a round or slot patch on a wall (drawn from the settings, not the CAD)."""
    name: str
    wall: str
    centre: np.ndarray          # (3,) m, on the wall
    normal: np.ndarray          # inward unit normal of the wall
    shape: str                  # round | slot
    diameter: float = 0.0       # m (round)
    width: float = 0.0          # m (slot, across)
    length: float = 0.0         # m (slot, along long_axis)
    long_axis: np.ndarray = field(default_factory=lambda: np.zeros(3))
    direction: np.ndarray = field(default_factory=lambda: np.zeros(3))   # the jet's direction (inlets)
    flow_sccm: float = 0.0      # inlets

    @property
    def area(self) -> float:
        return math.pi / 4.0 * self.diameter ** 2 if self.shape == "round" else self.width * self.length

    def contains(self, points) -> np.ndarray:
        """Which of `points` (on this port's wall) fall inside the patch."""
        d = np.asarray(points, float) - self.centre
        d = d - np.outer(_dot(d, self.normal), self.normal)
        if self.shape == "round":
            return np.linalg.norm(d, axis=1) <= self.diameter / 2.0
        across = np.cross(self.normal, self.long_axis)
        return (np.abs(_dot(d, self.long_axis)) <= self.length / 2.0) & (np.abs(_dot(d, across)) <= self.width / 2.0)


@dataclass
class Spray:
    nozzle: np.ndarray          # (3,) m
    axis: np.ndarray            # unit vector the nozzle points along
    gas_flow_sccm: float
    orifice_mm: float
    orifice_cd: float
    liquid_flow_ml_min: float | None
    standoff: float             # m, orifice exit to the shadowgraph image centre, along the axis
    start_radius: float         # m
    cone_half_angle: float      # rad
    speed: object               # m/s: a number, or [[size_um, m/s], ...] interpolated by size
    sizes_um: np.ndarray        # the sizes fired
    per_size: int
    distribution: Path | None   # a measured size distribution (import_sizes.py), or None
    below_dmin_from_um: float   # the counted-not-sized droplets go in spread from here up to d_min

    @property
    def start_centre(self) -> np.ndarray:
        return self.nozzle + self.standoff * self.axis


@dataclass
class Scenario:
    name: str
    box: np.ndarray             # (3,) m
    gas: physics.Gas
    standard_density: float
    rho_d: float
    inlets: list
    outlets: list
    spray: Spray
    target_outlet: str | None
    target_box: tuple | None    # ((3,), (3,)) m
    band_um: tuple
    planes: list                # [(axis index, position m, name)]
    gravity: bool
    drag: str
    entrainment: bool
    jets: dict                  # round_B, round_S, slot_B, slot_S
    random_walk: dict           # on, intensity, time_scale_s
    run: dict
    basis: dict
    plain: dict                 # the settings as read (after a sweep's change)
    source: Path | None = None
    label: str = ""             # a sweep's combination, '' for a single run

    def target_label(self) -> str:
        return self.target_outlet if self.target_outlet else "target box"

    def with_inlets_off(self) -> "Scenario":
        s = copy.copy(self)
        s.inlets = [copy.copy(p) for p in self.inlets]
        for p in s.inlets:
            p.flow_sccm = 0.0
        return s


def _num(value, what: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{what}: expected a number, got {value!r}") from None


def _vec(value, what: str, n: int = 3) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or len(value) != n:
        raise SettingsError(f"{what}: expected {n} numbers, got {value!r}")
    return np.array([_num(v, what) for v in value])


def _port(d: dict, box: np.ndarray, what: str, inlet: bool) -> Port:
    if not isinstance(d, dict):
        raise SettingsError(f"{what}: expected a mapping")
    name = str(d.get("name") or what)
    wall = str(d.get("wall", "")).lower()
    if wall not in WALLS:
        raise SettingsError(f"{what} ({name}): wall {d.get('wall')!r}: use one of {', '.join(WALLS)}")
    k, side = WALLS[wall]
    inplane = [a for a in range(3) if a != k]
    centre_mm = d.get("centre_mm")
    want = {AXES[a] for a in inplane}
    if not isinstance(centre_mm, dict) or set(centre_mm) != want:
        raise SettingsError(f"{what} ({name}): centre_mm on the {wall} wall needs exactly "
                            f"{{{', '.join(sorted(want))}}} in mm, got {centre_mm!r}")
    centre = np.zeros(3)
    centre[k] = box[k] * side
    for a in inplane:
        centre[a] = _num(centre_mm[AXES[a]], f"{what} ({name}) centre_mm.{AXES[a]}") / 1000.0
    normal = np.zeros(3)
    normal[k] = 1.0 if side == 0 else -1.0
    shape = str(d.get("shape", "round")).lower()
    p = Port(name, wall, centre, normal, shape)
    if shape == "round":
        p.diameter = _num(d.get("diameter_mm"), f"{what} ({name}) diameter_mm") / 1000.0
        half = {a: p.diameter / 2.0 for a in inplane}
    elif shape == "slot":
        p.width = _num(d.get("width_mm"), f"{what} ({name}) width_mm") / 1000.0
        p.length = _num(d.get("length_mm"), f"{what} ({name}) length_mm") / 1000.0
        along = str(d.get("long_side_along", AXES[inplane[1]])).lower()
        if along not in want:
            raise SettingsError(f"{what} ({name}): long_side_along must be one of {sorted(want)} on the {wall} wall")
        p.long_axis = np.eye(3)[AXES.index(along)]
        half = {a: (p.length if AXES[a] == along else p.width) / 2.0 for a in inplane}
    else:
        raise SettingsError(f"{what} ({name}): shape {shape!r}: use round or slot")
    if min(p.diameter, p.width, p.length) < 0 or p.area <= 0:
        raise SettingsError(f"{what} ({name}): its size must be positive")
    for a in inplane:
        if centre[a] - half[a] < -1e-9 or centre[a] + half[a] > box[a] + 1e-9:
            raise SettingsError(f"{what} ({name}) does not fit on the {wall} wall along {AXES[a]} "
                                f"(centre {centre[a] * 1000:g} mm, half-size {half[a] * 1000:g} mm, wall "
                                f"0-{box[a] * 1000:g} mm)")
    if inlet:
        p.flow_sccm = _num(d.get("flow_sccm"), f"{what} ({name}) flow_sccm")
        if p.flow_sccm < 0:
            raise SettingsError(f"{what} ({name}): flow_sccm must not be negative")
        if d.get("direction") is not None:
            v = _vec(d["direction"], f"{what} ({name}) direction")
            if np.linalg.norm(v) == 0 or v @ normal <= 0:
                raise SettingsError(f"{what} ({name}): direction must point into the chamber")
            p.direction = v / np.linalg.norm(v)
        else:
            p.direction = normal.copy()
    return p


def _sizes(spec, what: str) -> np.ndarray:
    if isinstance(spec, dict):
        lo, hi, step = (_num(spec.get(k), f"{what}.{k}") for k in ("from", "to", "step"))
        if not 0 < lo <= hi or step <= 0:
            raise SettingsError(f"{what}: need 0 < from <= to and step > 0")
        return np.round(np.arange(lo, hi + step / 2.0, step), 6)
    if isinstance(spec, (list, tuple)) and spec:
        out = np.array(sorted({_num(v, what) for v in spec}))
        if out[0] <= 0:
            raise SettingsError(f"{what}: sizes must be positive")
        return out
    raise SettingsError(f"{what}: a list of sizes, or {{from, to, step}} in um")


def build(plain: dict, basis: dict, source: Path | None = None, label: str = "") -> Scenario:
    """The validated scenario, in SI units."""
    S = plain
    box = _vec((S.get("chamber") or {}).get("size_mm"), "chamber.size_mm") / 1000.0
    if (box <= 0).any():
        raise SettingsError("chamber.size_mm: every side must be positive")
    g = S.get("gas") or {}
    gas = physics.air(_num(g.get("temperature_C", 20), "gas.temperature_C"),
                      _num(g.get("pressure_Pa", 101325), "gas.pressure_Pa"))
    rho_std = _num(g.get("standard_density_kg_m3", 1.184), "gas.standard_density_kg_m3")
    rho_d = _num((S.get("liquid") or {}).get("density_kg_m3"), "liquid.density_kg_m3")

    inlets = [_port(d, box, f"inlets.{i}", True) for i, d in enumerate(S.get("inlets") or [])]
    outlets = [_port(d, box, f"outlets.{i}", False) for i, d in enumerate(S.get("outlets") or [])]
    names = [p.name for p in inlets + outlets]
    if len(set(names)) != len(names):
        raise SettingsError(f"inlets and outlets need different names: {names}")
    if not outlets:
        raise SettingsError("outlets: at least one (the gas has to leave)")

    sp = S.get("spray") or {}
    dr = sp.get("droplets") or {}
    tilt = math.radians(_num(sp.get("tilt_deg", 0), "spray.tilt_deg"))
    lean = math.radians(_num(sp.get("lean_toward_deg", 0), "spray.lean_toward_deg"))
    axis = np.array([math.sin(tilt) * math.cos(lean), math.sin(tilt) * math.sin(lean), -math.cos(tilt)])
    dist = dr.get("distribution")
    dist = None if dist in (None, "", "none") else (Path(dist) if Path(dist).is_absolute() else ROOT / dist)
    speed = dr.get("speed_m_s")
    if isinstance(speed, list):
        speed = np.array([_vec(p, "spray.droplets.speed_m_s", 2) for p in speed])
        speed = speed[np.argsort(speed[:, 0])]
    else:
        speed = _num(speed, "spray.droplets.speed_m_s")
    spray = Spray(
        nozzle=_vec(sp.get("nozzle_mm"), "spray.nozzle_mm") / 1000.0, axis=axis,
        gas_flow_sccm=_num(sp.get("gas_flow_sccm"), "spray.gas_flow_sccm"),
        orifice_mm=_num(sp.get("orifice_mm"), "spray.orifice_mm"),
        orifice_cd=_num(sp.get("orifice_cd", 1.0), "spray.orifice_cd"),
        liquid_flow_ml_min=(None if sp.get("liquid_flow_ml_min") is None
                            else _num(sp["liquid_flow_ml_min"], "spray.liquid_flow_ml_min")),
        standoff=_num(dr.get("standoff_mm"), "spray.droplets.standoff_mm") / 1000.0,
        start_radius=_num(dr.get("start_radius_mm", 0), "spray.droplets.start_radius_mm") / 1000.0,
        cone_half_angle=math.radians(_num(dr.get("cone_half_angle_deg", 0), "spray.droplets.cone_half_angle_deg")),
        speed=speed, sizes_um=_sizes(dr.get("sizes_um"), "spray.droplets.sizes_um"),
        per_size=int(_num(dr.get("per_size", 100), "spray.droplets.per_size")),
        distribution=dist,
        below_dmin_from_um=_num(dr.get("below_d_min_from_um", 10), "spray.droplets.below_d_min_from_um"))
    if not (np.zeros(3) <= spray.nozzle).all() or not (spray.nozzle <= box).all():
        raise SettingsError(f"spray.nozzle_mm {spray.nozzle * 1000} is outside the chamber")
    if spray.per_size < 1 or not 0 < spray.orifice_cd <= 1 or spray.orifice_mm <= 0 or spray.gas_flow_sccm < 0:
        raise SettingsError("spray: per_size >= 1, 0 < orifice_cd <= 1, orifice_mm > 0, gas_flow_sccm >= 0")
    c, R = spray.start_centre, spray.start_radius
    if ((c - R) < 0).any() or ((c + R) > box).any():
        raise SettingsError(f"the droplets' start (nozzle + standoff {spray.standoff * 1000:g} mm along the axis, "
                            f"radius {R * 1000:g} mm) is not inside the chamber: {np.round(c * 1000, 1)} mm")

    t = S.get("target") or {}
    band = _vec(t.get("band_um"), "target.band_um", 2)
    if not 0 <= band[0] < band[1]:
        raise SettingsError("target.band_um: [low, high] with low < high")
    target_outlet = target_box = None
    if t.get("outlet") is not None:
        target_outlet = str(t["outlet"])
        if target_outlet not in [p.name for p in outlets]:
            raise SettingsError(f"target.outlet {target_outlet!r} is not one of the outlets "
                                f"{[p.name for p in outlets]}")
    elif t.get("box_mm") is not None:
        b = t["box_mm"]
        lo, hi = (_vec(b.get(k), f"target.box_mm.{k}") / 1000.0 for k in ("from", "to"))
        if (lo >= hi).any():
            raise SettingsError("target.box_mm: 'from' must be below 'to' on every axis")
        target_box = (lo, hi)
    else:
        raise SettingsError("target: give 'outlet: <name>' or 'box_mm: {from: [x, y, z], to: [x, y, z]}'")

    planes = []
    for i, p in enumerate(S.get("planes") or []):
        ax = str(p.get("axis", "")).lower()
        if ax not in AXES:
            raise SettingsError(f"planes.{i}.axis: x, y or z")
        at = _num(p.get("at_mm"), f"planes.{i}.at_mm") / 1000.0
        if not 0 < at < box[AXES.index(ax)]:
            raise SettingsError(f"planes.{i}: {ax} = {at * 1000:g} mm is not inside the chamber")
        planes.append((AXES.index(ax), at, str(p.get("name") or f"{ax} = {at * 1000:g} mm")))

    ph = S.get("physics") or {}
    drag = str(ph.get("drag", "schiller_naumann"))
    if drag not in physics.DRAG_LAWS:
        raise SettingsError(f"physics.drag {drag!r}: use one of {physics.DRAG_LAWS}")
    jets = {k: _num((ph.get("jets") or {}).get(k, v), f"physics.jets.{k}")
            for k, v in (("round_B", 5.8), ("round_S", 0.094), ("slot_B", 2.4), ("slot_S", 0.10))}
    rw = ph.get("random_walk") or {}
    random_walk = {"on": bool(rw.get("on", False)),
                   "intensity": _num(rw.get("intensity", 0.25), "physics.random_walk.intensity"),
                   "time_scale_s": _num(rw.get("time_scale_s", 0.005), "physics.random_walk.time_scale_s")}
    if random_walk["on"] and (random_walk["intensity"] < 0 or random_walk["time_scale_s"] <= 0):
        raise SettingsError("physics.random_walk: intensity >= 0 and time_scale_s > 0")

    r = S.get("run") or {}
    run = {"step_mm": _num(r.get("step_mm", 0.5), "run.step_mm"),
           "max_step_s": _num(r.get("max_step_s", 0.01), "run.max_step_s"),
           "max_time_s": _num(r.get("max_time_s", 30), "run.max_time_s"),
           "seed": int(_num(r.get("seed", 1), "run.seed")),
           "compare_without_inlets": bool(r.get("compare_without_inlets", True)),
           "paths_per_size": int(_num(r.get("paths_per_size", 12), "run.paths_per_size")),
           "path_sizes_um": [_num(v, "run.path_sizes_um") for v in (r.get("path_sizes_um") or [])]}
    if min(run["step_mm"], run["max_step_s"], run["max_time_s"]) <= 0:
        raise SettingsError("run: step_mm, max_step_s and max_time_s must be positive")

    return Scenario(name=str(S.get("name") or (source.stem if source else "scenario")), box=box, gas=gas,
                    standard_density=rho_std, rho_d=rho_d, inlets=inlets, outlets=outlets, spray=spray,
                    target_outlet=target_outlet, target_box=target_box, band_um=(float(band[0]), float(band[1])),
                    planes=planes, gravity=bool(ph.get("gravity", True)), drag=drag,
                    entrainment=bool(ph.get("entrainment", True)), jets=jets, random_walk=random_walk, run=run,
                    basis=basis, plain=plain, source=source, label=label)


# ---- sweeps ----------------------------------------------------------------------------------------------------

# every key build() reads: a sweep may set one the file leaves at its default, but not a misspelt one
KNOWN_KEYS = {"size_mm", "temperature_C", "pressure_Pa", "standard_density_kg_m3", "density_kg_m3", "name", "wall",
              "centre_mm", "shape", "diameter_mm", "width_mm", "length_mm", "long_side_along", "flow_sccm", "direction",
              "nozzle_mm", "tilt_deg", "lean_toward_deg", "gas_flow_sccm", "orifice_mm", "orifice_cd",
              "liquid_flow_ml_min", "droplets", "standoff_mm", "start_radius_mm", "cone_half_angle_deg", "speed_m_s",
              "sizes_um", "per_size", "distribution", "below_d_min_from_um", "outlet", "box_mm", "band_um", "gravity",
              "drag", "entrainment", "jets", "round_B", "round_S", "slot_B", "slot_S", "random_walk", "on",
              "intensity", "time_scale_s", "step_mm", "max_step_s", "max_time_s", "seed", "compare_without_inlets",
              "paths_per_size", "path_sizes_um"}


def _set_path(obj, path: str, value):
    keys = path.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    last = keys[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        if last not in cur and last not in KNOWN_KEYS:
            raise KeyError(last)
        cur[last] = value


def _label_value(v) -> str:
    return "x".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v) if isinstance(v, list) \
        else (f"{v:g}" if isinstance(v, (int, float)) else str(v))


def load(path: Path) -> list[Scenario]:
    """Every scenario a settings file describes: one, or one per combination of its sweep."""
    path = Path(path)
    plain, basis = read_yaml(path)
    sweep = plain.pop("sweep", None) or []
    if not sweep:
        return [build(plain, basis, path)]
    axes = []
    for i, s in enumerate(sweep):
        if not isinstance(s, dict) or "path" not in s or not isinstance(s.get("values"), list) or not s["values"]:
            raise SettingsError(f"sweep.{i}: needs a path and a non-empty list of values")
        axes.append((str(s["path"]), s["values"]))
    out = []
    for combo in itertools.product(*[v for _p, v in axes]):
        p2, b2 = copy.deepcopy(plain), dict(basis)
        parts = []
        for (p, _vals), v in zip(axes, combo):
            try:
                _set_path(p2, p, copy.deepcopy(v))
            except (KeyError, IndexError, ValueError, TypeError):
                raise SettingsError(f"sweep: no setting at {p!r} (e.g. inlets.0.diameter_mm)") from None
            b2[p] = (f"{basis[p][0]} (swept)" if p in basis else "swept", v)
            parts.append(f"{p}={_label_value(v)}")
        out.append(build(p2, b2, path, ", ".join(parts)))
    return out


def sweep_axes(path: Path) -> list[tuple[str, list]]:
    plain, _b = read_yaml(Path(path))
    return [(str(s["path"]), s["values"]) for s in (plain.get("sweep") or [])]


def compact(v) -> str:
    """A short label for a swept value: 90/80/0 for a list, 'from-to' for a box."""
    if isinstance(v, dict) and set(v) == {"from", "to"}:
        return f"{compact(v['from'])} to {compact(v['to'])}"
    if isinstance(v, dict):
        return ", ".join(f"{k} {compact(x)}" for k, x in v.items())
    if isinstance(v, list):
        return "/".join(compact(x) for x in v)
    return f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def sweep_shown(path: Path) -> list[tuple[str, list]]:
    """Each swept setting with what to show for its values: the numbers themselves, or (anything else) the sweep's
    own `labels:` list when it has one, else a compact label."""
    plain, _b = read_yaml(Path(path))
    out = []
    for s in plain.get("sweep") or []:
        vals = s["values"]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals) and not s.get("labels"):
            out.append((str(s["path"]), list(vals)))
            continue
        labels = s.get("labels")
        if not isinstance(labels, list) or len(labels) != len(vals):
            labels = [compact(v) for v in vals]
        out.append((str(s["path"]), [str(x) for x in labels]))
    return out
