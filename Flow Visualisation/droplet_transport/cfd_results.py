"""Phase 3a: where each droplet of an OpenFOAM particle run ended up (PLAN.md, Phase 3a, outputs).

Two records from the case: every wall hit (the particlePostProcessing files: which patch, when, where, which
droplet), and the cloud at a frame (every droplet still in the air: OpenFOAM drops one from the tracking at its
first wall touch). A droplet's fate is the first wall it touched (named by where on the chamber it is), or airborne
if it never did. Droplets are identified by (origProcId, origId). add_landed puts the landed ones back into the
saved frames for ParaView, inactive (active 0) where they landed.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import sizes
from .cfd_droplets import CloudScenario, Variant, foam_file, time_dirs

AIRBORNE = "airborne"
OBJECTS = "atomiser / nozzle block / arm"
PORT_MESH = "port mesh"
PORT_TUBE = "port tube"
SPRAY_HOLE = "back up the spray hole"
WALL_TOL = 0.5e-3                                    # m: a hit this close to a wall plane is on that wall
BANDS_UM = ((0, 10), (10, 20), (20, 30), (30, 60), (60, None))
NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def fates(scn: CloudScenario) -> list[str]:
    """Every fate, in the order the tables show them."""
    sides = [scn.wall_name(a, h) for a in range(3) if a != scn.up for h in (False, True)]
    return ["floor", *sides, "lid", OBJECTS, PORT_MESH, PORT_TUBE, SPRAY_HOLE, AIRBORNE]


def where(scn: CloudScenario, patch: str, p) -> str:
    """The fate of a hit on `patch` at point p (m)."""
    if patch == scn.spray_patch:
        return SPRAY_HOLE
    if patch in scn.port_patches:
        return PORT_MESH
    p = np.asarray(p, float)
    lo, hi = scn.inside[:, 0], scn.inside[:, 1]
    if (p < lo - WALL_TOL).any() or (p > hi + WALL_TOL).any():
        return PORT_TUBE                                 # beyond the chamber's walls: inside a port's stub
    u = scn.up
    floor_high = scn.up_sign < 0
    if abs(p[u] - scn.inside[u, int(floor_high)]) <= WALL_TOL:
        return "floor"
    if abs(p[u] - scn.inside[u, int(not floor_high)]) <= WALL_TOL:
        return "lid"
    for a in range(3):
        if a == u:
            continue
        for high in (False, True):
            if abs(p[a] - scn.inside[a, int(high)]) <= WALL_TOL:
                return scn.wall_name(a, high)
    return OBJECTS


# ---- reading OpenFOAM's files ------------------------------------------------------------------------------------

def _body(text: str) -> str:
    """A field file's content after its FoamFile header, comments removed."""
    i = text.find("FoamFile")
    if i >= 0:
        text = text[text.index("}", i) + 1:]
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def read_list(path: Path) -> np.ndarray:
    """A lagrangian scalar or label list: `N ( a b ... )`, or uniform `N{a}`."""
    s = _body(Path(path).read_text()).strip()
    m = re.match(r"(\d+)\s*\{\s*(" + NUM + r")\s*\}", s)
    if m:
        return np.full(int(m.group(1)), float(m.group(2)))
    m = re.match(r"(\d+)\s*\(", s)
    if not m:
        raise ValueError(f"{path}: not a list")
    n = int(m.group(1))
    vals = np.array(s[m.end(): s.rindex(")")].split(), float) if n else np.zeros(0)
    if vals.size != n:
        raise ValueError(f"{path}: {vals.size} values, header says {n}")
    return vals


def read_positions(path: Path) -> np.ndarray:
    """The `positions` file (old format, written alongside the barycentric coordinates): `(x y z) celli` per line."""
    s = _body(Path(path).read_text())
    rows = re.findall(r"\(\s*(" + NUM + r")\s+(" + NUM + r")\s+(" + NUM + r")\s*\)\s*-?\d+", s)
    return np.array(rows, float).reshape(-1, 3)


def read_cloud(time_dir: Path, cloud: str = "kinematicCloud") -> pd.DataFrame:
    """Every droplet in the domain at one frame: proc, id, d (m), active, x, y, z (m)."""
    L = Path(time_dir) / "lagrangian" / cloud
    cols = ["proc", "id", "d", "active", "x", "y", "z"]
    if not (L / "d").exists():
        return pd.DataFrame(columns=cols)
    pos = read_positions(L / "positions")
    df = pd.DataFrame({"proc": read_list(L / "origProcId").astype(int), "id": read_list(L / "origId").astype(int),
                       "d": read_list(L / "d"), "active": read_list(L / "active").astype(int)})
    if len(pos) != len(df):
        raise ValueError(f"{L}: {len(pos)} positions for {len(df)} droplets")
    df[["x", "y", "z"]] = pos
    return df[cols]


def _columns(header: str) -> list[str]:
    """The column names of a particlePostProcessing file: '(a0 a1 a2)' groups flattened."""
    h = header.lstrip("#").replace('"', " ").replace("(", " ").replace(")", " ")
    return h.split()


def read_hits(case: Path, cloud: str = "kinematicCloud") -> pd.DataFrame:
    """Every wall hit: patch, t (s), x, y, z (m), proc, id, d (m), in time order."""
    rows = []
    for f in sorted((Path(case) / "postProcessing" / "lagrangian" / cloud / "hits").glob("*/*.dat")):
        cols = None
        for line in f.read_text().splitlines():
            if line.startswith("#"):
                cols = _columns(line)
                continue
            if not line.strip():
                continue
            if cols is None:
                raise ValueError(f"{f}: no header line")
            vals = line.replace("(", " ").replace(")", " ").split()
            if len(vals) != len(cols):
                raise ValueError(f"{f}: {len(vals)} values for {len(cols)} columns")
            r = dict(zip(cols, vals))
            rows.append((f.stem, float(r["Time"]), float(r["position0"]), float(r["position1"]),
                         float(r["position2"]), int(r["origProc"]), int(r["origId"]), float(r["d"])))
    df = pd.DataFrame(rows, columns=["patch", "t", "x", "y", "z", "proc", "id", "d"])
    return df.sort_values("t", kind="stable").reset_index(drop=True)


# ---- each droplet's fate -----------------------------------------------------------------------------------------

def frame_at(case: Path, t: float, tol: float) -> Path | None:
    best = min(time_dirs(case), key=lambda td: abs(td[0] - t), default=None)
    return best[1] if best is not None and abs(best[0] - t) <= tol else None


def droplets(scn: CloudScenario, v: Variant, case: Path) -> pd.DataFrame:
    """One row per droplet fired: its size, fate, when and where it landed (or where it is at the end), and
    whether it was still in the air at switch-off."""
    case = Path(case)
    hits = read_hits(case)
    end = read_cloud(time_dirs(case)[-1][1])
    off_dir = frame_at(case, scn.exposure_s, scn.dt / 2)
    off = read_cloud(off_dir) if off_dir is not None else None

    first = hits.drop_duplicates(["proc", "id"], keep="first")
    rec = {}
    for r in first.itertuples(index=False):
        rec[(r.proc, r.id)] = (r.d, where(scn, r.patch, (r.x, r.y, r.z)), r.t, r.x, r.y, r.z)
    for r in end.itertuples(index=False):
        k = (r.proc, r.id)
        if k not in rec:
            # never touched a wall: airborne (an inactive droplet with no hit record would be a lost one)
            rec[k] = (r.d, AIRBORNE if r.active else "stopped, no wall hit", np.nan, r.x, r.y, r.z)
    airborne_off = set()
    if off is not None:
        airborne_off = {(p, i) for p, i, a in zip(off.proc, off.id, off.active) if a}
    keys = sorted(rec)
    d = np.array([rec[k][0] for k in keys]) * 1e6
    sizes = scn.sizes_um
    near = sizes[np.argmin(np.abs(d[:, None] - sizes[None, :]), axis=1)] if len(keys) else d
    return pd.DataFrame({
        "variant": v.key, "id": [f"{p}:{i}" for p, i in keys], "d_um": near,
        "fate": [rec[k][1] for k in keys], "landed_s": [rec[k][2] for k in keys],
        "x_mm": [rec[k][3] * 1000 for k in keys], "y_mm": [rec[k][4] * 1000 for k in keys],
        "z_mm": [rec[k][5] * 1000 for k in keys],
        "airborne_at_switch_off": [int(k in airborne_off) for k in keys] if off is not None else np.nan})


LANDED_CLASSES = {"positions": "Cloud<basicKinematicCollidingParcel>", "d": "scalarField", "active": "labelField",
                  "origId": "labelField", "origProcId": "labelField", "U": "vectorField"}
LANDED_FIELDS = tuple(LANDED_CLASSES)


def _entries(text: str, field: str) -> tuple[str, list[str]]:
    """A lagrangian field file split into its header (to the end of the FoamFile block) and its entries, one per
    droplet, as written. Long lists have one entry a line, short ones are on one line (`3(1 1 1)`), and a uniform
    one is `N{v}`."""
    j = text.index("}", text.index("FoamFile")) + 1
    head, body = text[:j], re.sub(r"//[^\n]*", "", text[j:])
    m = re.match(r"\s*(\d+)\s*\{(.*)\}", body, re.S)
    if m and "(" not in body[: m.start(2)]:
        return head, [m.group(2).strip()] * int(m.group(1))
    m = re.match(r"\s*(\d+)\s*\((.*)\)", body, re.S)
    if not m:
        raise ValueError(f"{field}: not a lagrangian list")
    inner = m.group(2)
    if field == "positions":
        rows = [r.group(0) for r in re.finditer(r"\([^()]*\)\s*-?\d+", inner)]
    elif field == "U":
        rows = [r.group(0) for r in re.finditer(r"\([^()]*\)", inner)]
    else:
        rows = inner.split()
    if len(rows) != int(m.group(1)):
        raise ValueError(f"{field}: {len(rows)} entries, header says {m.group(1)}")
    return head, rows


def add_landed(case: Path, df: pd.DataFrame, cloud: str = "kinematicCloud") -> int:
    """Put every droplet that has landed by each saved frame back into that frame, where it landed, inactive and
    still, so ParaView shows the deposit building up (OpenFOAM drops a droplet from the tracking at its first wall
    touch). Run once, after the results are read. Returns the number of frames changed."""
    marker = Path(case) / "landed_added"
    landed = df[df.landed_s.notna()].sort_values("landed_s", kind="stable")
    if landed.empty or marker.exists():                             # once only
        return 0
    proc_id = landed.id.str.split(":", expand=True).astype(int)
    new_rows = {
        "positions": [f"({x / 1000:.10g} {y / 1000:.10g} {z / 1000:.10g}) 0"
                      for x, y, z in zip(landed.x_mm, landed.y_mm, landed.z_mm)],
        "d": [f"{d * 1e-6:.10g}" for d in landed.d_um], "active": ["0"] * len(landed),
        "origId": [str(i) for i in proc_id[1]], "origProcId": [str(p) for p in proc_id[0]],
        "U": ["(0 0 0)"] * len(landed)}
    t_land = landed.landed_s.to_numpy()
    frames = [(t, d / "lagrangian" / cloud) for t, d in time_dirs(case) if t > 0]
    headers = {f: foam_file(cls, f, "").rstrip() for f, cls in LANDED_CLASSES.items()}   # if no frame has one
    for _t, L in frames[::-1]:
        for f in LANDED_FIELDS:
            if (L / f).exists():
                headers[f] = _entries((L / f).read_text(), f)[0]
    changed = 0
    for t, L in frames:
        n = int(np.searchsorted(t_land, t + 1e-9, side="right"))     # landed by this frame
        if n == 0:
            continue
        L.mkdir(parents=True, exist_ok=True)
        for f in LANDED_FIELDS:
            head, rows = _entries((L / f).read_text(), f) if (L / f).exists() else (headers[f], [])
            rows += new_rows[f][:n]
            (L / f).write_text(f"{head}\n\n{len(rows)}\n(\n" + "\n".join(rows) + "\n)\n")
        changed += 1
    marker.write_text(f"{len(landed)} landed droplets added to {changed} frames\n")
    return changed


def accounting(scn: CloudScenario, df: pd.DataFrame) -> dict:
    """Every droplet fired has a fate: per_size of each size, none lost."""
    want = scn.per_size * scn.sizes_um.size
    per = df.groupby("d_um").size().reindex(scn.sizes_um, fill_value=0)
    odd = per[per != scn.per_size]
    return {"fired_expected": want, "found": int(len(df)), "ok": len(df) == want and odd.empty,
            "sizes_off": {float(k): int(n) for k, n in odd.items()}}


def fates_by_size(scn: CloudScenario, df: pd.DataFrame) -> pd.DataFrame:
    """Per variant and size: droplets fired, and how many ended up where (counts)."""
    order = fates(scn) + sorted(set(df.fate) - set(fates(scn)))
    t = (df.groupby(["variant", "d_um", "fate"], observed=True).size().unstack("fate", fill_value=0)
         .reindex(columns=order, fill_value=0))
    t.insert(0, "fired", t.sum(axis=1))
    if df["airborne_at_switch_off"].notna().any():
        off = df.groupby(["variant", "d_um"], observed=True)["airborne_at_switch_off"].sum()
        t.insert(1, "airborne at switch-off", off)
    return t.reset_index()


def band_label(lo, hi) -> str:
    return f"> {lo:g} µm" if hi is None else f"{lo:g}-{hi:g} µm"


def bands(scn: CloudScenario, df: pd.DataFrame) -> pd.DataFrame:
    """Per variant and size band: the share of the droplets fired that ended up where, each size counting equally
    (not weighted by how many the spray makes: that is the report's job)."""
    rows = []
    for var, g in df.groupby("variant", sort=False, observed=True):
        for lo, hi in BANDS_UM:
            sel = g[(g.d_um > lo) & ((g.d_um <= hi) if hi is not None else True)]
            if sel.empty:
                continue
            row = {"variant": var, "band": band_label(lo, hi), "fired": len(sel)}
            if sel["airborne_at_switch_off"].notna().any():
                row["airborne at switch-off"] = sel["airborne_at_switch_off"].mean()
            for f in fates(scn):
                row[f] = (sel.fate == f).mean()
            rows.append(row)
    out = pd.DataFrame(rows)
    keep = [c for c in out.columns if c in ("variant", "band", "fired") or (out[c] > 0).any()]
    return out[keep]



# ---- grouped fates, and the weighting by the measured spray (the report) ---------------------------------------------

FLOOR_MOVING, FLOOR_STILL, SIDES, PORT = "floor, air moving", "floor, still air", "side walls", "port"
GROUPS = (FLOOR_MOVING, FLOOR_STILL, SIDES, OBJECTS, PORT, "lid", SPRAY_HOLE, AIRBORNE)   # the stacking order


def fate_groups(scn: CloudScenario, df: pd.DataFrame) -> pd.Series:
    """Each droplet's fate, grouped: the floor split by whether the air was still moving when it landed (the
    tracer check says the first is where the tracking's near-wall artefact lives), the side walls together, the
    port's mesh and tube together."""
    still_from = {v.key: scn.exposure_s + v.after_s for v in scn.variants()}
    t0 = df.variant.astype(str).map(still_from).fillna(np.inf)
    sides = {scn.wall_name(a, h) for a in range(3) if a != scn.up for h in (False, True)}
    g = df.fate.astype(str).copy()
    g[df.fate.isin(sides)] = SIDES
    g[df.fate.isin([PORT_MESH, PORT_TUBE])] = PORT
    floor = df.fate == "floor"
    g[floor & (df.landed_s <= t0 + 1e-9)] = FLOOR_MOVING
    g[floor & (df.landed_s > t0 + 1e-9)] = FLOOR_STILL
    return g


def size_weights(scn: CloudScenario) -> tuple[pd.Series | None, dict]:
    """How many droplets each fired size stands for in the measured spray (by number), or None without one."""
    if scn.distribution is None or not Path(scn.distribution).exists():
        return None, {}
    n, info = sizes.weights(scn.sizes_um, sizes.load(scn.distribution), scn.below_dmin_from_um)
    return pd.Series(n, index=scn.sizes_um), info


def weighted_groups(scn: CloudScenario, df: pd.DataFrame, w: pd.Series, lo: float, hi: float | None,
                    volume: bool = False) -> pd.DataFrame:
    """Per run: the share of a band's droplets (by number, or by volume) in each fate group, weighted by the
    measured spray; also airborne at switch-off."""
    sel = df[(df.d_um > lo) & ((df.d_um <= hi) if hi is not None else True)].copy()
    sel["group"] = fate_groups(scn, sel)
    sel["w"] = sel.d_um.map(w) / scn.per_size * (sel.d_um ** 3 if volume else 1.0)
    rows = []
    for var, g in sel.groupby("variant", sort=False, observed=True):
        tot = g.w.sum()
        row = {"variant": str(var)}
        for k in GROUPS:
            row[k] = float(g.w[g.group == k].sum() / tot) if tot > 0 else np.nan
        row["airborne at switch-off"] = float((g.w * g.airborne_at_switch_off).sum() / tot) if tot > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def floor_purity(scn: CloudScenario, df: pd.DataFrame, w: pd.Series, lo: float, hi: float,
                 groups=(FLOOR_MOVING, FLOOR_STILL), volume: bool = False) -> pd.Series:
    """Per run: the band's share (by number or volume, weighted by the measured spray) of everything that landed
    on the floor (in the given floor groups)."""
    d = df.copy()
    d["group"] = fate_groups(scn, d)
    d = d[d.group.isin(groups)]
    d["w"] = d.d_um.map(w) * (d.d_um ** 3 if volume else 1.0)
    inb = (d.d_um > lo) & (d.d_um <= hi)
    out = {}
    for var, g in d.groupby("variant", sort=False, observed=True):
        tot = g.w.sum()
        out[str(var)] = float(g.w[inb.loc[g.index]].sum() / tot) if tot > 0 else np.nan
    return pd.Series(out)
