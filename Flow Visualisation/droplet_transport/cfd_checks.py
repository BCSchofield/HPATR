"""Phase 3a checks (PLAN.md, Phase 3a, Checks): small OpenFOAM cases run alongside the runs, and checks read from
the runs' droplets.

- **Tracers:** 0.5 µm droplets fed in like the spray (the same flow, start disc and time step), for the exposure, one
  case per gusts setting. They follow the air (relaxation ~1 µs, settling ~10 µm/s), and the air does not flow into
  the walls, so a tracer that touches one was carried there by the tracking itself (the artefact seen in Part B).
  The share that do sets how far the finest sizes' wall and floor counts can be trusted.
- **Column:** every size let go from rest in free air, in still air and in a uniform cross-flow. Each droplet's
  speed and path against Phase 1's integrator (physics.analytic_step) with OpenFOAM's drag law and air: the
  tracking. Its settling speed against Phase 1's own (Schiller-Naumann, Phase 1's air): the physics.
- **From the runs:** every droplet accounted for; gusts on against off (the fines' floor deposit should move, the
  large droplets' should not); the large droplets land near the jet's impact point.
"""
from __future__ import annotations

import dataclasses
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import cfd_droplets, cfd_results, physics
from .cfd_droplets import CloudScenario, Variant, foam_file, time_dirs

TRACER_UM = 0.5
COLUMN_DT = 1e-3                 # s: the column cases' time step
COLUMN_FRAME_STEPS = 50          # a frame every 0.05 s
COLUMN_END = 0.8                 # s: long enough for the largest to settle to its speed, short of the floor
LARGE_UM = 80                    # "large" for the impact-point check
NEAR_MM = 35                     # the large droplets' landing counts as near the impact point within this (the
#                                  atomiser body's half-width, ~31 mm, rounded up)


def cases(scn: CloudScenario) -> list[str]:
    """The check cases the settings ask for."""
    out = [f"tracers_gusts_{'on' if g else 'off'}" for g in scn.gusts] if scn.tracers > 0 else []
    if scn.column is not None:
        out += ["column_still_air", "column_cross_flow"]
    return out


def tracer_scenario(scn: CloudScenario) -> CloudScenario:
    """The scenario as the tracer case sees it: one size, tracers droplets (in streams of per_size)."""
    streams = math.ceil(scn.tracers / scn.per_size)
    return dataclasses.replace(scn, sizes_um=np.array([TRACER_UM]), per_size=scn.per_size * streams)


def write(scn: CloudScenario, key: str, flow_dir: Path, case: Path) -> None:
    patches = cfd_droplets.read_patches(Path(flow_dir) / "constant" / "polyMesh" / "boundary")
    if key.startswith("tracers_"):
        gusts = key.endswith("_on")
        cfd_droplets.write_stage1(scn, Variant(gusts, 0), flow_dir, case)        # the spray's flow, steps, frames
        streams = math.ceil(scn.tracers / scn.per_size)
        text = "".join(cfd_droplets.injector(scn, f"tracers{i + 1}", TRACER_UM, speed=scn.speed_for(
            float(scn.sizes_um.min()))) for i in range(streams))
        (case / "constant" / "kinematicCloudProperties").write_text(
            cfd_droplets.cloud_properties(scn, gusts, patches, injection=text))
        return
    air = np.zeros(3) if key == "column_still_air" else scn.cross_flow
    col = dataclasses.replace(scn, exposure_s=COLUMN_DT, per_size=1)                 # dt = COLUMN_DT, one of each
    cfd_droplets.write_stage1(col, Variant(False, 0), flow_dir, case)
    (case / "0" / "U").write_text(foam_file("volVectorField", "U", f"""
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform {cfd_droplets._v(air)};
boundaryField
{{
    ".*"
    {{
        type            fixedValue;
        value           uniform {cfd_droplets._v(air)};
    }}
}}
"""))
    (case / "0" / "phi").unlink(missing_ok=True)                    # recomputed from the uniform air
    text = "".join(cfd_droplets.injector(col, cfd_droplets.injector_name(d), d, method="point",
                                         position=scn.column, speed=1e-9, count=1) for d in scn.sizes_um)
    (case / "constant" / "kinematicCloudProperties").write_text(
        cfd_droplets.cloud_properties(col, False, patches, injection=text))
    (case / "system" / "controlDict").write_text(
        cfd_droplets.control_dict("startTime", COLUMN_END, COLUMN_DT, COLUMN_FRAME_STEPS))


# ---- reading -------------------------------------------------------------------------------------------------------

def read_vectors(path: Path) -> np.ndarray:
    """A lagrangian vector list: `N ( (a b c) ... )` or uniform `N{(a b c)}`."""
    s = cfd_results._body(Path(path).read_text()).strip()
    m = re.match(r"(\d+)\s*\{\s*\(([^)]*)\)\s*\}", s)
    if m:
        return np.tile(np.array(m.group(2).split(), float), (int(m.group(1)), 1))
    n = int(re.match(r"(\d+)", s).group(1))
    rows = re.findall(r"\(\s*(" + cfd_results.NUM + r")\s+(" + cfd_results.NUM + r")\s+(" + cfd_results.NUM +
                      r")\s*\)", s)
    v = np.array(rows, float).reshape(-1, 3)
    if len(v) != n:
        raise ValueError(f"{path}: {len(v)} vectors, header says {n}")
    return v


def read_frames(case: Path, cloud: str = "kinematicCloud") -> pd.DataFrame:
    """Every droplet in every frame: t, id, d (m), age (s), x, y, z (m), ux, uy, uz (m/s)."""
    out = []
    for t, d in time_dirs(case):
        L = d / "lagrangian" / cloud
        if t == 0 or not (L / "age").exists():
            continue
        f = cfd_results.read_cloud(d, cloud)
        f["age"] = cfd_results.read_list(L / "age")
        f[["ux", "uy", "uz"]] = read_vectors(L / "U")
        f.insert(0, "t", t)
        out.append(f)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def openfoam_air(case: Path, rho_air: float) -> physics.Gas:
    """The air OpenFOAM's tracker used: rhoInf and the case's nu."""
    txt = (Path(case) / "constant" / "transportProperties").read_text()
    nu = float(re.search(r"\bnu\b[^;]*?\s(" + cfd_results.NUM + r")\s*;", txt).group(1))
    return physics.Gas(293.15, 101325.0, rho_air, rho_air * nu)


def integrate(scn: CloudScenario, d_um, gas: physics.Gas, law: str, air, t_end: float, dt: float = 1e-4):
    """Phase 1's integrator from rest at the column point: times, positions (n_t, n_d, 3), velocities."""
    d = np.asarray(d_um, float) * 1e-6
    n = d.size
    tau0 = physics.tau_stokes(d, scn.rho_d, gas)
    a = scn.gravity * (1.0 - gas.density / scn.rho_d)
    x = np.tile(scn.column, (n, 1))
    v = np.zeros((n, 3))
    u = np.tile(np.asarray(air, float), (n, 1))
    steps = int(math.ceil(t_end / dt))
    X, V = np.empty((steps + 1, n, 3)), np.empty((steps + 1, n, 3))
    X[0], V[0] = x, v
    for k in range(steps):
        Re = gas.density * np.linalg.norm(u - v, axis=1) * d / gas.viscosity
        x, v = physics.analytic_step(x, v, u, tau0 / physics.drag_factor(Re, law), a, np.full(n, dt))
        X[k + 1], V[k + 1] = x, v
    return np.arange(steps + 1) * dt, X, V


def column_result(scn: CloudScenario, frames: pd.DataFrame, gas: physics.Gas, air) -> pd.DataFrame:
    """Per size: OpenFOAM's settling speed at its last frame in the air, Phase 1's integrator's at the same age (the
    same drag law, air and g), the terminal speeds (OpenFOAM's law; Phase 1's own: its drag law, air and g 9.80665
    against the cases' 9.81), and the largest gap between the two paths (mm)."""
    sizes = scn.sizes_um
    T, X, V = integrate(scn, sizes, gas, "putnam", air, COLUMN_END)
    up = np.zeros(3)
    up[scn.up] = scn.up_sign
    vt_of = physics.settling_speed(sizes * 1e-6, scn.rho_d, gas, "putnam", g=cfd_droplets.G)
    vt_p1 = physics.settling_speed(sizes * 1e-6, scn.rho_d, physics.air(20.0), "schiller_naumann")
    rows = []
    for k, s in enumerate(sizes):
        f = frames[np.isclose(frames.d * 1e6, s, rtol=1e-6)].sort_values("t")
        if f.empty:
            rows.append({"size_um": s})
            continue
        P = f[["x", "y", "z"]].to_numpy()
        U = f[["ux", "uy", "uz"]].to_numpy()
        i = np.clip(np.searchsorted(T, f.age.to_numpy()), 1, T.size - 1)
        w = ((f.age.to_numpy() - T[i - 1]) / (T[i] - T[i - 1]))[:, None]
        Xp = X[i - 1, k] * (1 - w) + X[i, k] * w
        Vp = V[i - 1, k] * (1 - w) + V[i, k] * w
        v_of, v_py = -(U[-1] @ up), -(Vp[-1] @ up)
        rows.append({"size_um": s, "age_s": float(f.age.iloc[-1]), "speed_openfoam_mm_s": 1000 * v_of,
                     "speed_integrator_mm_s": 1000 * v_py,
                     "openfoam_vs_integrator_pct": 100 * (v_of / v_py - 1) if v_py else np.nan,
                     "path_gap_mm": float(np.linalg.norm(P - Xp, axis=1).max() * 1000),
                     "terminal_openfoam_law_mm_s": 1000 * vt_of[k],
                     "at_terminal": bool(abs(v_py / vt_of[k] - 1) < 1e-3),
                     "terminal_phase1_mm_s": 1000 * vt_p1[k],
                     "openfoam_vs_phase1_pct": 100 * (v_of / vt_p1[k] - 1),
                     "cross_flow_lag_mm_s": float(1000 * np.linalg.norm((U[-1] - np.asarray(air)) -
                                                                       ((U[-1] - np.asarray(air)) @ up) * up))})
    return pd.DataFrame(rows)


def tracer_result(scn: CloudScenario, df: pd.DataFrame) -> dict:
    n = len(df)
    by = df.fate.value_counts()
    return {"fired": n, "shares": {f: float(c / n) for f, c in by.items()},
            "floor": float(by.get("floor", 0) / n) if n else 0.0,
            "any_wall": float((df.fate != cfd_results.AIRBORNE).sum() / n) if n else 0.0,
            "median_landed_s": float(df.landed_s.median()) if df.landed_s.notna().any() else None}


def run_one(scn: CloudScenario, key: str, flow_dir: Path, case: Path, foam, log=print) -> tuple[dict, pd.DataFrame]:
    """Write, run and read one check case; its frames' flow copies deleted after. `foam` is cfd_runner.foam."""
    write(scn, key, flow_dir, case)
    secs = foam(scn, case, "icoUncoupledKinematicParcelFoam", "log.check")
    if key.startswith("tracers_"):
        st = tracer_scenario(scn)
        df = cfd_results.droplets(st, Variant(key.endswith("_on"), 0), case)
        df["variant"] = key
        out = {"key": key, "seconds": secs, **tracer_result(st, df)}
    else:
        air = np.zeros(3) if key == "column_still_air" else scn.cross_flow
        frames = read_frames(case)
        df = column_result(scn, frames, openfoam_air(case, scn.rho_air), air)
        df.insert(0, "variant", key)
        ok = df[df.at_terminal == True]                                               # noqa: E712
        out = {"key": key, "seconds": secs, "air_m_s": list(map(float, air)),
               "worst_speed_pct": float(df.openfoam_vs_integrator_pct.abs().max()),
               "worst_path_gap_mm": float(df.path_gap_mm.max()),
               "sizes_at_terminal": int(len(ok)),
               "worst_vs_phase1_pct": float(ok.openfoam_vs_phase1_pct.abs().max()) if len(ok) else None}
    cfd_droplets.prune(case, set())
    log(f"  check {key}: done in {secs:.0f} s")
    return out, df


# ---- checks read from the runs ---------------------------------------------------------------------------------------

def _plan_cols(scn):
    h, v = [a for a in range(3) if a != scn.up]
    return ["x_mm", "y_mm", "z_mm"][h], ["x_mm", "y_mm", "z_mm"][v], h, v


def impact_mm(scn) -> np.ndarray:
    k = scn.direction[scn.up]
    floor = scn.inside[scn.up, 0 if scn.up_sign > 0 else 1]
    return (scn.hole + (floor - scn.hole[scn.up]) / k * scn.direction) * 1000


def floor_spread(scn, sel: pd.DataFrame) -> dict:
    """Where a group landed on the floor: its share, centre (mm), and median / 90th-percentile distance from the
    jet's impact point."""
    ch, cv, h, v = _plan_cols(scn)
    fl = sel[sel.fate == "floor"]
    ip = impact_mm(scn)
    if fl.empty:
        return {"floor": 0.0, "n_floor": 0}
    r = np.hypot(fl[ch] - ip[h], fl[cv] - ip[v])
    return {"floor": float(len(fl) / len(sel)), "n_floor": int(len(fl)),
            "centre_mm": [float(fl[ch].mean()), float(fl[cv].mean())],
            "r50_mm": float(np.median(r)), "r90_mm": float(np.percentile(r, 90))}


def gusts_compare(scn, df: pd.DataFrame) -> list[dict]:
    """Per flow-kept time and band: the floor deposit with gusts on and off."""
    rows = []
    if len(scn.gusts) < 2:
        return rows
    for a in scn.after_s:
        on, off = Variant(True, a).key, Variant(False, a).key
        if on not in set(df.variant) or off not in set(df.variant):
            continue
        for lo, hi in cfd_results.BANDS_UM:
            def band(k):
                g = df[df.variant == k]
                return g[(g.d_um > lo) & ((g.d_um <= hi) if hi is not None else True)]
            s_on, s_off = floor_spread(scn, band(on)), floor_spread(scn, band(off))
            shift = (float(np.hypot(*np.subtract(s_on["centre_mm"], s_off["centre_mm"])))
                     if "centre_mm" in s_on and "centre_mm" in s_off else None)
            rows.append({"after_s": a, "band": cfd_results.band_label(lo, hi), "on": s_on, "off": s_off,
                         "centre_shift_mm": shift})
    return rows


def large_near_impact(scn, df: pd.DataFrame) -> list[dict]:
    out = []
    for var, g in df.groupby("variant", sort=False, observed=True):
        s = floor_spread(scn, g[g.d_um >= LARGE_UM])
        out.append({"variant": str(var), **s})
    return out


def tracers_vs_sizes(scn, df: pd.DataFrame, cases: dict, sizes_um=(2, 4, 6, 10, 20, 30)) -> list[dict]:
    """Per gusts setting: the tracers' floor share over the exposure beside the fired sizes' (droplets landed on the
    floor by switch-off, the run with the shortest flow-kept time): how far the artefact reaches up the sizes."""
    out = []
    for g in scn.gusts:
        key = f"tracers_gusts_{'on' if g else 'off'}"
        if key not in cases:
            continue
        run = Variant(g, scn.after_s[0]).key
        r = df[df.variant.astype(str) == run]
        row = {"gusts": g, "tracers_floor": cases[key]["floor"], "tracers_any_wall": cases[key]["any_wall"],
               "run": run, "sizes": {}}
        for s in sizes_um:
            k = scn.sizes_um[np.argmin(np.abs(scn.sizes_um - s))]
            sel = r[r.d_um == k]
            if len(sel):
                row["sizes"][f"{k:g}"] = float(((sel.fate == "floor") & (sel.landed_s <= scn.exposure_s + 1e-9))
                                               .mean())
        out.append(row)
    return out
