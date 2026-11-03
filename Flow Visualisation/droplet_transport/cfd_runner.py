"""Phase 3a: run a droplets settings file through OpenFOAM, collect where every droplet went, build the ParaView
states. See README.md, "Droplets through the CFD flow".

    <runs_folder>/<name>/<date_time>/                one folder per run, everything in it (copy it anywhere whole):
        report.md, figures/                          the report
        paraview/<variant>.command                   double-click: opens that run in ParaView, wherever the folder is
        paraview/<variant>.pvsm, *.png               the ParaView states and their pictures
        openfoam/<variant>/                          the OpenFOAM cases (their meshes hard-linked, so real files)
        settings.yaml, run.json, droplets.csv, fates_by_size.csv, bands.csv, checks.json (+ csv), plan_view.npz,
        flow_grid.npz (the air, for comparisons)
    <runs_folder>/flows/<flow case>_it<iteration>/   the flow at that iteration, reconstructed once and shared

Each variant runs on its own core: stage 1 (spray, then the flow kept for the bracketed time), stage 2 (still air),
then its results and its ParaView state; the check cases (cfd_checks) run alongside. The frames' copies of the frozen
flow are deleted as each stage ends (the droplets in every frame are kept). Then the figures and report.md
(rebuild_report remakes them from the output folder alone).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, cfd_checks, cfd_compare, cfd_droplets, cfd_plots, cfd_report, cfd_results
from .cfd_droplets import CloudScenario, Variant, time_dirs
from .runner import _slug
from .settings import base_files

PV_SCRIPT = Path(__file__).with_name("pv_droplets.py")
_print_lock = threading.Lock()


class RunError(RuntimeError):
    pass


def _say(log, msg):
    with _print_lock:
        log(msg)


def foam(scn: CloudScenario, case: Path, command: str, log_name: str) -> float:
    """Run an OpenFOAM command in `case` (its output in case/log_name); the seconds it took."""
    t0 = time.time()
    cmd = f'source "{scn.bashrc}" >/dev/null 2>&1; cd "{case}" && {command} > {log_name} 2>&1'
    r = subprocess.run(["bash", "-c", cmd])
    log_file = Path(case) / log_name
    text = log_file.read_text(errors="replace") if log_file.exists() else ""
    if r.returncode != 0 or "FOAM FATAL" in text or not re.search(r"^End\s*$", text, re.M):
        tail = "\n".join(text.splitlines()[-30:])
        raise RunError(f"{command} failed in {case} (log: {log_file}):\n{tail}")
    return time.time() - t0


def _iterations(case: Path) -> list[int]:
    found = set()
    for base in [case, *sorted(case.glob("processor[0-9]*"))[:1]]:
        found |= {int(t) for t, d in time_dirs(base) if (d / "U").exists() and float(t).is_integer()}
    return sorted(found)


def prepare_flow(scn: CloudScenario, log=print) -> Path:
    """The flow at the chosen iteration, as one (reconstructed) case under runs_folder/flows/: copied from the
    CfdOF case, which is only read. Reused while the CfdOF case's files for that iteration are unchanged."""
    src, it = scn.flow_case, str(scn.iteration)
    if not (src / "constant" / "polyMesh").is_dir():
        raise RunError(f"flow.case {src}: no constant/polyMesh there (is it the CfdOF case folder, .../case?)")
    procs = sorted(src.glob("processor[0-9]*"))
    if (src / it / "U").exists():
        stamp_file = src / it / "U"
    elif procs and (procs[0] / it / "U").exists():
        stamp_file = procs[0] / it / "U"
    else:
        raise RunError(f"flow.iteration {it}: not saved in {src}; saved: {_iterations(src)}")
    stamp = f"{src.resolve()}\n{stamp_file.stat().st_mtime:.0f}\n"
    name = src.parent.name if src.name == "case" else src.name
    dest = scn.runs_folder / "flows" / f"{_slug(name)}_it{it}"
    if (dest / "source.txt").exists() and (dest / "source.txt").read_text() == stamp and (dest / it / "U").exists():
        log(f"flow: {dest} (reused)")
        return dest
    tmp = dest.with_name(f"{dest.name}.building-{os.getpid()}-{threading.get_ident()}")   # runs started together
    shutil.rmtree(tmp, ignore_errors=True)                                                 #   each build their own
    tmp.mkdir(parents=True)
    shutil.copytree(src / "constant", tmp / "constant")
    shutil.copytree(src / "system", tmp / "system")
    if (src / it / "U").exists():
        shutil.copytree(src / it, tmp / it)
        _round_denormals_in(tmp / it)
    else:
        log(f"flow: reconstructing iteration {it} of {src} ({len(procs)} pieces) ...")
        for p in procs:
            shutil.copytree(p / "constant", tmp / p.name / "constant")
            shutil.copytree(p / it, tmp / p.name / it)
            _round_denormals_in(tmp / p.name / it)
        foam(scn, tmp, f"reconstructPar -time {it}", "log.reconstructPar")
        for p in procs:
            shutil.rmtree(tmp / p.name)
    (tmp / "source.txt").write_text(stamp)
    if (dest / "source.txt").exists() and (dest / "source.txt").read_text() == stamp:   # another run finished first
        shutil.rmtree(tmp)
        log(f"flow: {dest} (reused)")
        return dest
    shutil.rmtree(dest, ignore_errors=True)
    try:
        tmp.rename(dest)
    except OSError:                                                   # another run renamed its copy in between
        if not ((dest / "source.txt").exists() and (dest / "source.txt").read_text() == stamp):
            raise
        shutil.rmtree(tmp)
    log(f"flow: {dest}")
    return dest


def _round_denormals_in(folder: Path) -> None:
    """The copied flow's fields with numbers below ~1e-300 set to 0: OpenFOAM can write them (e.g. 4.9e-324 in p of
    Chamber_v2) but not read them back, so reconstructPar and the droplet cases would stop on them."""
    for f in folder.iterdir():
        if f.is_file():
            txt = f.read_text()
            fixed = cfd_droplets.round_denormals(txt)
            if fixed != txt:
                f.write_text(fixed)


def _wall_patches(flow_dir: Path, scn: CloudScenario) -> list[str]:
    pats = cfd_droplets.read_patches(flow_dir / "constant" / "polyMesh" / "boundary")
    missing = [p for p in [scn.spray_patch, *scn.port_patches] if p not in [q[0] for q in pats]]
    if missing:
        raise RunError(f"flow: no patch {missing} in the mesh; its patches: {[q[0] for q in pats]}")
    empty = [p for p in [scn.spray_patch, *scn.port_patches] if dict((q[0], q[2]) for q in pats)[p] == 0]
    if empty:
        raise RunError(f"flow: patch {empty} has no faces (refine it: CFDOF_GUIDE.md Part 5)")
    return [n for n, t, nf in sorted(pats, key=lambda q: -q[2]) if t == "wall" and nf > 0]   # largest first


def run_variant(scn: CloudScenario, v: Variant, case: Path, log=print) -> dict:
    """Both stages for one variant; the frames' flow copies deleted as each ends."""
    out = {"variant": v.key, "label": v.label, "case": str(case)}
    _say(log, f"  {v.key}: stage 1 (spray {scn.exposure_s:g} s, flow kept {v.after_s:g} s more) ...")
    out["stage1_s"] = foam(scn, case, "icoUncoupledKinematicParcelFoam", "log.stage1")
    t1 = time_dirs(case)[-1][0]
    want1 = scn.stage1_steps(v) * scn.dt
    if abs(t1 - want1) > scn.dt / 2:
        raise RunError(f"{case}: stage 1 ended at {t1:g} s, not {want1:g} s (log.stage1)")
    freed = cfd_droplets.prune(case, {t1})
    cfd_droplets.write_still_air(scn, v, case)
    _say(log, f"  {v.key}: stage 1 done in {out['stage1_s']:.0f} s; stage 2 (still air to "
              f"{scn.exposure_s + scn.settle_s:g} s) ...")
    out["stage2_s"] = foam(scn, case, "icoUncoupledKinematicParcelFoam", "log.stage2")
    t2 = time_dirs(case)[-1][0]
    if abs(t2 - (scn.exposure_s + scn.settle_s)) > 1e-3:
        raise RunError(f"{case}: stage 2 ended at {t2:g} s, not {scn.exposure_s + scn.settle_s:g} s (log.stage2)")
    out["freed_GB"] = (freed + cfd_droplets.prune(case, set())) / 1e9      # finished: no restart point needed
    out["still_air_step_s"] = scn.still_air(v)[1]
    _say(log, f"  {v.key}: stage 2 done in {out['stage2_s']:.0f} s")
    return out


def _port_seed(plan: dict | None) -> list | None:
    """Where Ben's view seeds its streamlines into the (first) port: half way along its stub, in m."""
    if not plan or not plan.get("ports"):
        return None
    p = plan["ports"][0]
    c = list(p["centre_mm"])
    c[p["wall_axis"]] = (c[p["wall_axis"]] + p["wall_mm"]) / 2
    return [x / 1000 for x in c]


def paraview_state(scn: CloudScenario, v: Variant, case: Path, pv_dir: Path, walls: list[str],
                   plan: dict | None = None) -> dict:
    """The run's .pvsm and three pictures (switch-off, the end, the split at switch-off), made by ParaView's
    pvbatch."""
    pv_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"case": str(case), "pvsm": str(pv_dir / f"{v.key}.pvsm"),
           "png_end": str(pv_dir / f"{v.key}_end.png"), "png_switch_off": str(pv_dir / f"{v.key}_switch_off.png"),
           "png_split": str(pv_dir / f"{v.key}_split_switch_off.png"),
           "wall_patches": walls, "flow_slices_normal": scn.flow_slices_normal, "port_seed": _port_seed(plan),
           "spray_direction": scn.direction.tolist(),
           "hole": scn.hole.tolist(), "slice_normal": scn.slice_normal, "inside": scn.inside.tolist(),
           "up": scn.up, "up_sign": scn.up_sign, "switch_off_s": scn.exposure_s,
           "size_min_um": float(scn.sizes_um.min()), "size_max_um": float(scn.sizes_um.max()),
           "flow_colour_max_m_s": 5.0,
           "note": (f"{scn.name}: {v.label}\nspray on 0-{scn.exposure_s:g} s, switched off at {scn.exposure_s:g} s, "
                    f"still air from {scn.exposure_s + v.after_s:g} s\n{scn.per_size} droplets of each size, "
                    f"{scn.sizes_um.min():g}-{scn.sizes_um.max():g} µm")}
    cfg_file = pv_dir / f"{v.key}.json"
    cfg_file.write_text(json.dumps(cfg, indent=1))
    t0 = time.time()
    r = subprocess.run([str(scn.paraview_bin / "pvbatch"), str(PV_SCRIPT), str(cfg_file)], capture_output=True,
                       text=True)
    if r.returncode != 0 or not Path(cfg["pvsm"]).exists():
        raise RunError(f"pvbatch failed for {v.key}:\n{(r.stdout + r.stderr)[-3000:]}")
    cfg_file.unlink()
    write_opener(scn, pv_dir.parent, v.key, v.label)
    return {"pvsm": cfg["pvsm"], "png_end": cfg["png_end"], "png_switch_off": cfg["png_switch_off"],
            "png_split": cfg["png_split"], "paraview_s": time.time() - t0}


OPENER = """#!/bin/bash
# {label}.
# Double-click to open this run in ParaView (then First Frame, Play). It works wherever the run's folder now is
# (copy the whole folder): the view's paths are rewritten from where the run was made to where this file sits.
run="$(cd "$(dirname "$0")/.." && pwd)"
made={made}
state="$(mktemp -d)/{key}.pvsm"
MADE="$made" RUN="$run" perl -pe 's/\\Q$ENV{{MADE}}\\E/$ENV{{RUN}}/g' "$run/paraview/{key}.pvsm" > "$state"
open -n -a {app} --args --state="$state"
"""


def write_opener(scn: CloudScenario, root: Path, key: str, label: str) -> Path:
    """paraview/<key>.command: double-clicked in Finder (or `open`ed), opens that run's state in ParaView from
    wherever the run's folder has been copied or moved to."""
    f = Path(root) / "paraview" / f"{key}.command"
    f.write_text(OPENER.format(label=label, made=shlex.quote(str(Path(root))), key=key,
                               app=shlex.quote(str(scn.paraview_bin.parent.parent))))
    f.chmod(0o755)
    return f


def _one(scn, v, flow_dir, cases, pv_dir, walls, plan, write_only, paraview, log):
    case = cases / v.key
    cfd_droplets.write_stage1(scn, v, flow_dir, case)
    if write_only:
        return {"variant": v.key, "label": v.label, "case": str(case)}, None
    info = run_variant(scn, v, case, log)
    df = cfd_results.droplets(scn, v, case)
    info["accounting"] = cfd_results.accounting(scn, df)
    cfd_results.add_landed(case, df)                      # the deposit, into every frame, for ParaView
    if paraview:
        info.update(paraview_state(scn, v, case, pv_dir, walls, plan))
    return info, df


def fresh_stamp(cases_parent: Path) -> str:
    """A date_time name not yet used under cases_parent, claimed by making the folder (runs started in the same
    second get _2, _3, ...)."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    Path(cases_parent).mkdir(parents=True, exist_ok=True)
    for i in range(1, 100):
        name = stamp if i == 1 else f"{stamp}_{i}"
        try:
            (Path(cases_parent) / name).mkdir()
            return name
        except FileExistsError:
            continue
    raise RunError(f"{cases_parent}: no free name for {stamp}")


def scenario(plain: dict, basis: dict, source: Path, per_size: int | None = None) -> CloudScenario:
    """The scenario from plain settings (per_size, if given, replaces the settings')."""
    if per_size:
        plain = {**plain, "spray": {**(plain.get("spray") or {}),
                                    "droplets": {**((plain.get("spray") or {}).get("droplets") or {}),
                                                 "per_size": int(per_size)}}}
    return cfd_droplets.build(plain, basis, source)


def run_file(settings_path: Path, out: Path | None = None, per_size: int | None = None, only=None,
             write_only: bool = False, paraview: bool = True, checks: bool = True, log=print) -> Path:
    """Run a droplets settings file into its output folder; a file with a `sweep:` runs once per entry and then
    compares them (cfd_sweep)."""
    settings_path = Path(settings_path)
    plain, basis = cfd_droplets.read_yaml(settings_path)
    if "sweep" in plain:
        from . import cfd_sweep
        return cfd_sweep.run_sweep(settings_path, plain, basis, out, per_size, only, write_only, paraview, checks,
                                   log)
    scn = scenario(plain, basis, settings_path, per_size)
    root = Path(out) if out else scn.runs_folder / _slug(scn.name) / fresh_stamp(scn.runs_folder / _slug(scn.name))
    if " " in str(root):
        raise cfd_droplets.SettingsError(f"--out {root}: OpenFOAM cannot work in a path with spaces")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings_path, root / "settings.yaml")
    for b in base_files(settings_path):
        shutil.copy2(b, root / b.name)
    return run_scenario(scn, root, only, write_only, paraview, checks, log)


def run_scenario(scn: CloudScenario, root: Path, only=None, write_only: bool = False, paraview: bool = True,
                 checks: bool = True, log=print, extra_meta: dict | None = None) -> Path:
    """Every run of one scenario (its settings already in root/settings.yaml; the OpenFOAM cases in
    root/openfoam/), the checks alongside, then the figures and report.md."""
    variants = scn.variants()
    if only:
        want = [w.strip() for w in only.split(",")] if isinstance(only, str) else list(only)
        bad = [w for w in want if w not in [v.key for v in variants]]
        if bad:
            raise cfd_droplets.SettingsError(f"--only {bad}: the runs are {[v.key for v in variants]}")
        variants = [v for v in variants if v.key in want]
    root = Path(root)
    cases = root / "openfoam"
    cases.mkdir(parents=True, exist_ok=True)
    n = scn.sizes_um.size * scn.per_size
    log(f"{Path(scn.source).name if scn.source else scn.name}: {len(variants)} run(s), {n:,} droplets each "
        f"({scn.sizes_um.size} sizes x {scn.per_size}) -> {root}")
    if scn.dt > cfd_droplets.MAX_STEP_S:
        log(f"  note: a {scn.dt * 1000:.1f} ms step (above {cfd_droplets.MAX_STEP_S * 1000:g} ms): a quick look; "
            f"report.md flags it")
    flow_dir = prepare_flow(scn, log)
    walls = _wall_patches(flow_dir, scn)
    mesh = flow_dir / "constant" / "polyMesh"
    plan = cfd_plots.plan_view(scn, cfd_droplets.boundary_faces(mesh, walls + [scn.spray_patch, *scn.port_patches]),
                               walls)
    cfd_plots.save_plan(plan, root / "plan_view.npz")
    air = cfd_compare.save_flow_grid(scn, flow_dir, root / "flow_grid.npz", foam) if not write_only else {}
    check_keys = cfd_checks.cases(scn) if checks and not write_only else []
    t0 = time.time()
    infos, frames, done_checks = {}, [], {}
    with ThreadPoolExecutor(max_workers=min(scn.parallel, len(variants) + len(check_keys))) as pool:
        jobs = {pool.submit(_one, scn, v, flow_dir, cases, root / "paraview", walls, plan, write_only, paraview,
                            log): v.key for v in variants}
        jobs.update({pool.submit(cfd_checks.run_one, scn, k, flow_dir, cases / f"check_{k}", foam,
                                 lambda m: _say(log, m)): f"check_{k}" for k in check_keys})
        errors = []
        for job in as_completed(jobs):
            key = jobs[job]
            try:
                info, df = job.result()
            except Exception as e:                       # one failed run does not stop the others
                errors.append(f"{key}: {e}")
                _say(log, f"  {key}: FAILED: {e}")
                continue
            if key.startswith("check_"):
                done_checks[key[len("check_"):]] = (info, df)
                continue
            infos[key] = info
            if df is not None:
                frames.append(df)
    wall_s = time.time() - t0
    order = [v.key for v in variants if v.key in infos]
    meta = {**(extra_meta or {}), "name": scn.name, "settings": str(scn.source),
            "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "version": __version__,
            "flow_case": str(scn.flow_case), "iteration": scn.iteration, "flow_copy": str(flow_dir),
            "flow_cells": air.get("cells"), "cases": str(cases), "per_size": scn.per_size,
            "sizes_um": [float(scn.sizes_um.min()), float(scn.sizes_um.max()), int(scn.sizes_um.size)],
            "stage1_step_s": scn.dt, "wall_clock_s": wall_s, "runs": [infos[k] for k in order], "errors": errors}
    (root / "run.json").write_text(json.dumps(meta, indent=1, default=str))
    if write_only:
        log(f"written only: {cases}")
        return root
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df["variant"] = pd.Categorical(df["variant"], categories=order, ordered=True)
        df = df.sort_values(["variant", "d_um", "id"], kind="stable")
        df.to_csv(root / "droplets.csv", index=False, float_format="%.6g")
        fbs = cfd_results.fates_by_size(scn, df)
        fbs.to_csv(root / "fates_by_size.csv", index=False)
        bt = cfd_results.bands(scn, df)
        bt.to_csv(root / "bands.csv", index=False, float_format="%.4f")
        for kind, name in (("column", "checks_column.csv"), ("tracers", "checks_tracers.csv")):
            got = [d for k, (_i, d) in sorted(done_checks.items()) if k.startswith(kind)]
            if got:
                pd.concat(got, ignore_index=True).to_csv(root / name, index=False, float_format="%.6g")
        ck = {"cases": {k: i for k, (i, _d) in sorted(done_checks.items())}}
        (root / "checks.json").write_text(json.dumps(ck, indent=1, default=str))
        rebuild_report(root, log)
    if errors:
        raise RunError("some runs failed:\n" + "\n".join(errors))
    return root


def remake_views(root: Path, log=print) -> Path:
    """Every run's ParaView state, pictures and opener again, from a finished run's folder (after a change to the
    views; OpenFOAM is not run)."""
    root = Path(root).resolve()
    meta = json.loads((root / "run.json").read_text())
    plain, basis = cfd_droplets.read_yaml(root / "settings.yaml")
    plain.setdefault("spray", {}).setdefault("droplets", {})["per_size"] = int(meta["per_size"])
    scn = cfd_droplets.build(plain, basis, Path(meta["settings"]))
    plan = cfd_plots.load_plan(root / "plan_view.npz")
    keys = {v.key: v for v in scn.variants()}
    runs = [r for r in meta["runs"] if r["variant"] in keys and (root / "openfoam" / r["variant"]).is_dir()]
    if not runs:
        raise RunError(f"{root}: no OpenFOAM cases in openfoam/ to make views of")
    walls = _wall_patches(root / "openfoam" / runs[0]["variant"], scn)
    with ThreadPoolExecutor(max_workers=min(scn.parallel, len(runs))) as pool:
        jobs = {pool.submit(paraview_state, scn, keys[r["variant"]], root / "openfoam" / r["variant"],
                            root / "paraview", walls, plan): r for r in runs}
        for job in as_completed(jobs):
            jobs[job].update(job.result())
            _say(log, f"  view: {jobs[job]['variant']}")
    (root / "run.json").write_text(json.dumps(meta, indent=1, default=str))
    return root / "paraview"


# ---- the figures and report.md (from the output folder alone) -------------------------------------------------------

def rebuild_report(root: Path, log=print) -> Path:
    """The figures and report.md, from what a run left in its output folder: settings.yaml, run.json,
    droplets.csv, bands.csv, checks.json and its csv files, plan_view.npz. Safe to run again after a change to the
    figures or report."""
    root = Path(root).resolve()
    meta = json.loads((root / "run.json").read_text())
    meta["root"] = str(root)                            # where the run is now (it may have been moved)
    plain, basis = cfd_droplets.read_yaml(root / "settings.yaml")
    plain.setdefault("spray", {}).setdefault("droplets", {})["per_size"] = int(meta["per_size"])
    scn = cfd_droplets.build(plain, basis, Path(meta["settings"]))
    order = [r["variant"] for r in meta["runs"]]
    df = pd.read_csv(root / "droplets.csv")
    df["variant"] = pd.Categorical(df["variant"], categories=order, ordered=True)
    plan = cfd_plots.load_plan(root / "plan_view.npz")
    ck = json.loads((root / "checks.json").read_text()) if (root / "checks.json").exists() else {"cases": {}}
    col = pd.read_csv(root / "checks_column.csv") if (root / "checks_column.csv").exists() else None
    tr = pd.read_csv(root / "checks_tracers.csv") if (root / "checks_tracers.csv").exists() else None
    ck["tracers_vs_sizes"] = cfd_checks.tracers_vs_sizes(scn, df, ck["cases"])
    ck["gusts"] = cfd_checks.gusts_compare(scn, df)
    ck["large"] = cfd_checks.large_near_impact(scn, df)
    figs = root / "figures"
    figs.mkdir(exist_ok=True)
    figures = []
    for v in scn.variants():
        g = df[df.variant.astype(str) == v.key]
        if g.empty:
            continue
        f = f"floor_{v.key}.png"
        cfd_plots.floor_maps(scn, plan, [("", cfd_plots.band_panels(scn, plan, g))], figs / f,
                             f"Where each size band lands on the floor: {v.label}",
                             f"{scn.name}. Each size counted equally ({scn.per_size} of each). Seen from above.")
        figures.append((f, f"the floor deposit by band, {v.label}"))
    if len(scn.gusts) == 2:
        a = scn.after_s[len(scn.after_s) // 2]
        rows = [(f"gusts {'on' if gu else 'off'}", cfd_plots.band_panels(scn, plan, df[df.variant.astype(str) ==
                                                                                     Variant(gu, a).key]))
                for gu in scn.gusts]
        if all(len(p) for _l, p in rows):
            cfd_plots.floor_maps(scn, plan, rows, figs / "floor_gusts_on_vs_off.png",
                                 f"Gusts on against off, flow kept {a:g} s: the fines' deposit should move, the large "
                                 "droplets' should not", f"{scn.name}. Each size counted equally. Seen from above.")
            figures.append(("floor_gusts_on_vs_off.png", f"the floor deposit by band, gusts on against off "
                                                         f"(flow kept {a:g} s)"))
    cfd_plots.fates_by_size(scn, df, figs / "fates_by_size.png", f"Where each size ends up: {scn.name}")
    figures.append(("fates_by_size.png", "where each size ends up, every run"))
    if tr is not None and len(tr):
        h, v = plan["h"], plan["v"]
        cols = ["x_mm", "y_mm", "z_mm"]
        panels = []
        for gu in scn.gusts:
            t = tr[tr.variant == f"tracers_gusts_{'on' if gu else 'off'}"]
            fl = t[t.fate == "floor"]
            panels.append(cfd_plots.Panel(f"tracers, gusts {'on' if gu else 'off'}",
                                          fl[[cols[h], cols[v]]].to_numpy(float), max(len(t), 1),
                                          f"floor {100 * len(fl) / max(len(t), 1):.0f} % of {len(t):,} fired"))
            run = df[(df.variant.astype(str) == Variant(gu, scn.after_s[0]).key) & (df.d_um == scn.sizes_um.min())]
            fl = run[(run.fate == "floor") & (run.landed_s <= scn.exposure_s + 1e-9)]
            panels.append(cfd_plots.Panel(f"{scn.sizes_um.min():g} µm, gusts {'on' if gu else 'off'}",
                                          fl[[cols[h], cols[v]]].to_numpy(float), max(len(run), 1),
                                          f"floor {100 * len(fl) / max(len(run), 1):.0f} % of {len(run):,}, by "
                                          f"switch-off"))
        cfd_plots.floor_maps(scn, plan, [("", panels)], figs / "check_tracers.png",
                             "Tracers that follow the air should never land: where they do is the artefact",
                             f"0.5 µm tracers and the smallest size fired, landed on the floor during the "
                             f"{scn.exposure_s:g} s exposure. Seen from above.")
        figures.append(("check_tracers.png", "where tracers land on the floor (the near-wall artefact)"))
    if col is not None and len(col):
        cfd_plots.check_column(col, figs / "check_column.png")
        figures.append(("check_column.png", "settling speeds and paths against Phase 1"))
    meta["bands_csv"] = str(root / "bands.csv")
    (root / "checks.json").write_text(json.dumps(ck, indent=1, default=str))
    (root / "report.md").write_text(cfd_report.report(scn, Path(meta["settings"]).name, meta, df, ck, figures),
                                    encoding="utf-8")
    old = root / "run.md"
    if old.exists():
        old.unlink()
    log(f"report: {root / 'report.md'}")
    return root / "report.md"
