"""Phase 3a: run a droplets settings file through OpenFOAM, collect where every droplet went, build the ParaView
states. See README.md, "Droplets through the CFD flow".

    <runs_folder>/<date>_<time>_<name>/              one folder per run, everything in it (copy it anywhere whole):
        View <flow>.command                          double-click: opens the headline run (gusts on, the middle
                                                     flow-kept time) in ParaView, wherever the folder is
        report.md                                    the report (its figures in data/)
        data/                                        everything else:
            figures/                                 the report's figures
            paraview/<variant>.command               double-click: opens that run in ParaView, wherever the folder is
            paraview/<variant>.pvsm, *.png           the ParaView states and their pictures
            openfoam/<variant>/                      the OpenFOAM cases (their meshes hard-linked, so real files)
            settings.yaml, run.json, droplets.csv, fates_by_size.csv, bands.csv, checks.json (+ csv), plan_view.npz,
            flow_grid.npz (the air, for comparisons)
    <runs_folder>/flows/<flow case>_it<iteration>/   the flow at that iteration, reconstructed once and shared

Runs made before 2026-11-12 are <runs_folder>/<name>/<date_time>/, with everything at the top (no data/); the tools
read both (cfd_report.run_files).

Each variant runs on its own core: stage 1 (spray, then the flow kept for the bracketed time), stage 2 (still air),
then its results and its ParaView state; the check cases (cfd_checks) run alongside. The frames' copies of the frozen
flow are deleted while each stage runs (the droplets in every frame are kept). Then the figures and report.md
(rebuild_report remakes them from the output folder alone).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, cfd_checks, cfd_compare, cfd_droplets, cfd_plots, cfd_report, cfd_results
from .cfd_droplets import CloudScenario, Variant, headline, time_dirs
from .cfd_report import DATA, link_prefix, report_path, run_files
from .runner import _slug
from .settings import base_files

PV_SCRIPT = Path(__file__).with_name("pv_droplets.py")
_print_lock = threading.Lock()


class RunError(RuntimeError):
    pass


class Stalled(RunError):
    """A command stopped because its log went quiet (foam)."""


def _say(log, msg):
    with _print_lock:
        log(msg)


STALL_S = 900               # a command whose log hasn't changed this long is stopped: one droplet looping forever in
                            #   OpenFOAM's tracking hung two gusts-off runs on 2026-11-14 (a step logs every ~0.1 s)


def foam(scn: CloudScenario, case: Path, command: str, log_name: str, stall_s: float | None = None) -> float:
    """Run an OpenFOAM command in `case` (its output in case/log_name); the seconds it took. Stopped (Stalled) if
    its log goes quiet for stall_s (default STALL_S)."""
    stall_s = STALL_S if stall_s is None else stall_s
    t0 = time.time()
    cmd = f'source "{scn.bashrc}" >/dev/null 2>&1; cd "{case}" && {command} > {log_name} 2>&1'
    log_file = Path(case) / log_name
    p = subprocess.Popen(["bash", "-c", cmd], start_new_session=True)     # its own group: stopped with its solver
    stalled = False
    while True:
        try:
            p.wait(timeout=min(10, stall_s))
            break
        except subprocess.TimeoutExpired:
            pass
        last = log_file.stat().st_mtime if log_file.exists() else t0
        if time.time() - max(last, t0) > stall_s:
            stalled = True
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            break
    text = log_file.read_text(errors="replace") if log_file.exists() else ""
    tail = "\n".join(text.splitlines()[-30:])
    if stalled:
        raise Stalled(f"{command} in {case}: its log stopped changing for {stall_s / 60:g} min, so it was stopped "
                      f"(log: {log_file}):\n{tail}")
    if p.returncode != 0 or "FOAM FATAL" in text or not re.search(r"^End\s*$", text, re.M):
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
    dest = scn.runs_folder / "flows" / f"{_slug(flow_name(scn))}_it{it}"
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


def flow_name(scn: CloudScenario) -> str:
    """The CfdOF case's name: its folder's (the one holding case/)."""
    src = scn.flow_case
    return src.parent.name if src.name == "case" else src.name


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


PRUNE_EVERY_S = 30          # a running stage's finished frames pruned this often
DROPLET_STALL_S = 300       # a droplet stage quiet this long is stuck (a step logs in well under a second)
RESTARTS = 4                # restarts a stage gets before it is given up
NUDGE_DIGITS = (8, 6)       # restarting from the frame it started from, the droplets' positions rounded to these


def restart_frame(case: Path) -> tuple[float, Path] | None:
    """The newest frame a stage can restart from (the flow and the droplets both there), or None."""
    frames = time_dirs(case)
    if not frames or frames[-1][0] == 0:
        return None
    t, d = frames[-1]
    cloud = d / "lagrangian" / "kinematicCloud"
    ok = (d / "U").exists() and (d / "uniform" / "time").exists() and (cloud / "coordinates").exists()
    return (t, d) if ok else None


BARY = re.compile(r"\(([^()]+)\)(\s+-?\d+\s+-?\d+\s+-?\d+)")


def nudge(frame: Path, digits: int) -> None:
    """Round every droplet's position (its barycentric coordinates in its tet) in `frame` to `digits` significant
    figures: a move of ~1e-8 of a cell at 8, enough to put a droplet off the knife-edge it looped on."""
    f = frame / "lagrangian" / "kinematicCloud" / "coordinates"
    txt = f.read_text()
    j = txt.index("}", txt.index("FoamFile")) + 1
    body = BARY.sub(lambda m: "(" + " ".join(f"{float(x):.{digits}g}" for x in m.group(1).split()) + ")" + m.group(2),
                    txt[j:])
    f.write_text(txt[:j] + body)


def readable(frame: Path) -> None:
    """The droplets' numbers below ~1e-300 in `frame` set to 0: OpenFOAM writes them (e.g. a barycentric coordinate
    of 1.2e-311) but can't read them back, and Stream 4000's restart died on one (2026-11-15)."""
    _round_denormals_in(frame / "lagrangian" / "kinematicCloud")


BAD_TETS = "badTetCells"    # the faceZone round the cells OpenFOAM can't split into valid tets, and its removeParcels


def _labels(path: Path) -> np.ndarray:
    """An ascii labelList or set file (owner, neighbour, a checkMesh faceSet): its labels."""
    s = cfd_results._body(Path(path).read_text())
    m = re.search(r"(\d+)\s*\(", s)
    if not m:
        raise RunError(f"{path}: not a list of labels")
    vals = np.array(s[m.end(): s.rindex(")")].split(), dtype=np.int64)
    if vals.size != int(m.group(1)):
        raise RunError(f"{path}: {vals.size} labels, its header says {m.group(1)}")
    return vals


def _rewrite(f: Path, text: str) -> None:
    """f's content replaced by a new file: a hard-linked file (the cases' meshes) is not changed under the others."""
    f.unlink()
    f.write_text(text)


REMOVE_PARCELS = f"""
    {BAD_TETS}
    {{
        type            removeParcels;
        faceZones       ({BAD_TETS});
        log             true;
        resetOnWrite    false;
        resetOnStart    false;
    }}
"""


def _remove_parcels_on(case: Path) -> None:
    """removeParcels on the bad cells' faceZone in the case's cloud (again after stage 2 rewrites the cloud)."""
    f = Path(case) / "constant" / "kinematicCloudProperties"
    txt = f.read_text()
    if f"type            removeParcels;" in txt:
        return
    new, n = re.subn(r"^(cloudFunctions\s*\{)", lambda m: m.group(1) + REMOVE_PARCELS, txt, count=1, flags=re.M)
    if n != 1:
        raise RunError(f"{f}: no cloudFunctions to add removeParcels to")
    _rewrite(f, new)


def guard(scn: CloudScenario, case: Path) -> np.ndarray:
    """Keep droplets out of the cells OpenFOAM can't split into valid tets (the stuck droplets, CFDOF_GUIDE.md 8.11)
    from now on, and return those cells. They are the cells either side of the faces checkMesh -allGeometry finds
    ("Error in face tets"); a faceZone of their internal faces, with OpenFOAM's removeParcels on it, takes a droplet
    out of the run the moment it reaches one. (Only their flagged faces is not enough: the droplet loops inside the
    cell without touching its bad face, 2026-11-15.) They are near-wall layer cells, so cfd_results gives such a
    droplet the fate of the wall its cell is on, or the port's if the cell is in its cone or pipe (flagged
    removed_in_bad_cell). The case's faceZones and cloud are rewritten as new files; its other mesh files (hard links
    shared with the flow and every other case) are only read: checkMesh and writeCellCentres run in a scratch case of
    links beside it. Once on, case/GUARD_FILE holds the cells, their centres and the ports' centres (m)."""
    case = Path(case)
    marker = case / cfd_results.GUARD_FILE
    if marker.exists():
        return np.array(json.loads(marker.read_text())["cells"], dtype=np.int64)
    mesh = case / "constant" / "polyMesh"
    work = case / "checkMesh"
    shutil.rmtree(work, ignore_errors=True)
    (work / "constant" / "polyMesh").mkdir(parents=True)
    (work / "system").mkdir()
    for f in mesh.iterdir():
        if f.is_file():
            (work / "constant" / "polyMesh" / f.name).symlink_to(f.resolve())
    for f in ("controlDict", "fvSchemes", "fvSolution"):
        shutil.copy2(case / "system" / f, work / "system" / f)
    foam(scn, work, "checkMesh -allGeometry -constant", "log.checkMesh")
    s = work / "constant" / "polyMesh" / "sets" / "lowQualityTetFaces"
    faces = _labels(s) if s.exists() else np.zeros(0, np.int64)
    owner, neighbour = _labels(mesh / "owner"), _labels(mesh / "neighbour")
    cells = np.unique(np.concatenate([owner[faces], neighbour[faces[faces < neighbour.size]]]))
    (work / "0").mkdir()
    foam(scn, work, "postProcess -func writeCellCentres -time 0", "log.writeCellCentres")
    txt = (work / "0" / "C").read_text()
    m = re.compile(r"(\d+)\s*\(\s*\n").search(txt, txt.index("internalField"))
    rows = txt[m.end():].split("\n", int(m.group(1)))
    centres = np.array([rows[c].strip("()").split() for c in cells], float).reshape(-1, 3)
    ports = {p: c.tolist() for p in scn.port_patches if (c := _patch_centre(txt, p)) is not None}
    bad = np.zeros(int(owner.max()) + 1, bool)
    bad[cells] = True
    zone = np.nonzero(bad[owner[:neighbour.size]] | bad[neighbour])[0]
    fz = mesh / "faceZones"
    txt = fz.read_text()
    j = txt.index("}", txt.index("FoamFile")) + 1
    if not re.fullmatch(r"\s*0\s*\(\s*\)\s*", cfd_results._body(txt)):
        raise RunError(f"{fz}: already has zones; the guard only adds its own to an empty list")
    _rewrite(fz, txt[:j] + f"\n\n1\n(\n{BAD_TETS}\n{{\n    type faceZone;\n    faceLabels List<label> {zone.size}\n(\n"
                 + "\n".join(map(str, zone)) + f"\n)\n;\n    flipMap List<bool> {zone.size}{{0}};\n}}\n)\n")
    _remove_parcels_on(case)
    (case / "log.checkMesh").write_text((work / "log.checkMesh").read_text())
    shutil.rmtree(work)
    marker.write_text(json.dumps({"cells": cells.tolist(), "centres_m": centres.round(9).tolist(), "ports_m": ports}))
    return cells


def _patch_centre(c_field: str, patch: str) -> np.ndarray | None:
    """The mean of a patch's face centres (m), from writeCellCentres' C field."""
    m = re.compile(rf"^\s*{re.escape(patch)}\s*\{{", re.M).search(c_field, c_field.index("boundaryField"))
    if not m:
        return None
    block = c_field[m.end(): c_field.index("}", m.end())]
    u = re.search(r"value\s+uniform\s+\(([^)]*)\)", block)
    if u:
        return np.array(u.group(1).split(), float)
    n = re.search(r"value\s+nonuniform\s+List<vector>\s*\d+\s*\(", block)
    if not n:
        return None
    return np.array(block[n.end(): block.rindex(")")].replace("(", " ").replace(")", " ").split(),
                    float).reshape(-1, 3).mean(axis=0)


def _keep_entries(text: str, keep: np.ndarray, where) -> str:
    """A lagrangian field file with only the `keep` droplets: `N{v}` (one value for all) or `N ( one a line )`."""
    j = text.index("}", text.index("FoamFile")) + 1
    head, body = text[:j], text[j:]
    m = re.search(r"^(\d+)\s*([{(])", body, re.M)
    if not m or int(m.group(1)) != keep.size or keep.size == 0:
        raise RunError(f"{where}: not a list of {keep.size} droplets")
    if m.group(2) == "{":
        return head + body[:m.start(1)] + str(int(keep.sum())) + body[m.end(1):]
    a = m.end()
    b = body.index("\n)", a)
    items = body[a:b].strip("\n").split("\n")
    if len(items) != keep.size:
        raise RunError(f"{where}: {len(items)} lines for {keep.size} droplets")
    kept = [x for x, k in zip(items, keep) if k]
    return head + body[:m.start(1)] + f"{len(kept)}\n(\n" + "\n".join(kept) + body[b:]


def drop_parcels(frame: Path, cells: np.ndarray) -> int:
    """Take the droplets in `cells` out of `frame` (removeParcels only acts as one enters a cell), the same entries
    from every field of the cloud; returns how many. cfd_results finds them in the frames before (removed_in_bad_cell)."""
    L = Path(frame) / "lagrangian" / "kinematicCloud"
    txt = (L / "coordinates").read_text()
    j = txt.index("}", txt.index("FoamFile")) + 1
    where = np.array([int(m.group(2).split()[0]) for m in BARY.finditer(txt[j:])], dtype=np.int64)
    gone = np.isin(where, cells)
    if not gone.any():
        return 0
    for f in sorted(L.iterdir()):
        if f.is_file():
            _rewrite(f, _keep_entries(f.read_text(), ~gone, f))
    return int(gone.sum())


def _foam_pruning(scn: CloudScenario, case: Path, log_name: str, freed: list, restarts: list | None = None,
                  resume: bool = False) -> float:
    """foam() for one stage, its finished frames pruned as it goes (all but the newest, which it may be writing):
    each frame holds a copy of the flow (~210 MB on a 1.7 M cell mesh), so a 290 s run at 4 frames a second would
    otherwise reach ~250 GB before the stage ended (Stream_2000 filled the disk, 2026-11-14).

    A stage that stalls is restarted from its newest frame, up to RESTARTS times; each restart appended to
    `restarts`. The stall is one droplet looping in a cell OpenFOAM can't split into valid tets (CFDOF_GUIDE.md 8.11):
    the run repeats exactly, but the frame's positions are written to 10 figures, and reading them back moves every
    droplet by ~1e-10 of a cell, which puts the stuck one off its knife-edge. Restarting again from the same frame
    would repeat exactly, so those positions are rounded further (NUDGE_DIGITS).

    That alone often wasn't enough (the air carries the droplet back onto the same face, 2026-11-15), so from the
    first stall on the stage runs guarded (guard): droplets are kept out of those cells, the ones already in one are
    taken out of the frame it restarts from, and each is flagged (cfd_results, removed_in_bad_cell). `resume`: the stage stalled
    last time (its frames are there), so it restarts at once as after a stall."""
    restarts = [] if restarts is None else restarts
    stop = threading.Event()

    def pruning():
        while not stop.wait(PRUNE_EVERY_S):
            try:
                frames = time_dirs(case)
                if len(frames) > 1:
                    freed.append(cfd_droplets.prune(case, set(), before=frames[-1][0]))
            except OSError:                              # a frame changing under it: the next pass gets it
                pass

    th = threading.Thread(target=pruning, daemon=True)
    th.start()
    t0 = time.time()
    started = time_dirs(case)[-1][0] if time_dirs(case) else 0.0    # the frame this attempt starts from
    nudges = 0
    try:
        while True:
            try:
                if resume:
                    resume = False
                    raise Stalled(f"{log_name}: stalled last time, resumed")
                foam(scn, case, "icoUncoupledKinematicParcelFoam", log_name, DROPLET_STALL_S)
                return time.time() - t0
            except Stalled:
                fr = restart_frame(case)
                if len(restarts) >= RESTARTS or fr is None:
                    raise
                t, frame = fr
                first = not (Path(case) / cfd_results.GUARD_FILE).exists()
                cells = guard(scn, case)
                if first:                                # the guard changes the run: no nudge needed yet
                    nudges = 0
                elif abs(t - started) < 1e-9:            # no newer frame since the last start: it would repeat exactly
                    if nudges >= len(NUDGE_DIGITS):
                        raise
                    nudge(frame, NUDGE_DIGITS[nudges])
                    nudges += 1
                else:
                    nudges = 0
                dropped = drop_parcels(frame, cells)
                readable(frame)
                log_file = Path(case) / log_name
                n = 1
                while log_file.with_name(f"{log_name}.stalled{n}").exists():   # a resumed case has some already
                    n += 1
                kept = log_file.with_name(f"{log_name}.stalled{n}")
                if log_file.exists():
                    log_file.replace(kept)
                cd = Path(case) / "system" / "controlDict"
                cd.write_text(re.sub(r"^startFrom\s+\S+;", "startFrom       latestTime;", cd.read_text(), flags=re.M))
                restarts.append({"log": log_name, "from_s": t, "rounded_to": NUDGE_DIGITS[nudges - 1] if nudges else 10,
                                 "guarded": True, "dropped": dropped, "stalled_log": kept.name})
                started = t
    finally:
        stop.set()
        th.join()


def run_variant(scn: CloudScenario, v: Variant, case: Path, log=print, resume: bool = False) -> dict:
    """Both stages for one variant; the frames' flow copies deleted as each runs and ends. `resume`: carry on a case
    that stalled last time from its newest frame, guarded (_foam_pruning)."""
    out = {"variant": v.key, "label": v.label, "case": str(case)}
    freed, restarts = [], []
    in_stage2 = resume and (Path(case) / "log.stage2").exists()
    if in_stage2:
        out["stage1_s"] = None
    else:
        _say(log, f"  {v.key}: stage 1 (spray {scn.exposure_s:g} s, flow kept {v.after_s:g} s more)"
                  + (", resumed from its newest frame" if resume else "") + " ...")
        out["stage1_s"] = _foam_pruning(scn, case, "log.stage1", freed, restarts, resume)
        t1 = time_dirs(case)[-1][0]
        want1 = scn.stage1_steps(v) * scn.dt
        if abs(t1 - want1) > scn.dt / 2:
            raise RunError(f"{case}: stage 1 ended at {t1:g} s, not {want1:g} s (log.stage1)")
        freed.append(cfd_droplets.prune(case, {t1}))
        cfd_droplets.write_still_air(scn, v, case)
        if (Path(case) / cfd_results.GUARD_FILE).exists():
            _remove_parcels_on(case)                     # the still air's cloud is a new file: the guard again
        _say(log, f"  {v.key}: stage 1 done in {out['stage1_s']:.0f} s; stage 2 (still air to "
                  f"{scn.exposure_s + scn.settle_s:g} s) ...")
    out["stage2_s"] = _foam_pruning(scn, case, "log.stage2", freed, restarts, in_stage2)   # its restart frame, once
                                                                                           #   read, is pruned too
    t2 = time_dirs(case)[-1][0]
    if abs(t2 - (scn.exposure_s + scn.settle_s)) > 1e-3:
        raise RunError(f"{case}: stage 2 ended at {t2:g} s, not {scn.exposure_s + scn.settle_s:g} s (log.stage2)")
    out["freed_GB"] = (sum(freed) + cfd_droplets.prune(case, set())) / 1e9   # finished: no restart point needed
    out["still_air_step_s"] = scn.still_air(v)[1]
    out["restarts"] = restarts
    if resume:
        out["resumed"] = True
    froms = ", ".join("%g s" % r["from_s"] for r in restarts)
    _say(log, f"  {v.key}: stage 2 done in {out['stage2_s']:.0f} s"
              + (f" (restarted {len(restarts)}x after a stuck droplet, from {froms}; guarded from the first)"
                 if restarts else ""))
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


FRONT = """#!/bin/bash
# {name}: {label}.
# Double-click to open it in ParaView (then First Frame, Play). Every run's view: {views}/*.command.
exec bash "$(dirname "$0")/{inner}"
"""


def write_fronts(top: Path, runs: list[tuple[str, Path, CloudScenario, str]]) -> list[Path]:
    """top/View <name>.command for each (name, run folder, its scenario, variant): double-clicked, it opens that run
    through the run's own opener (paraview/<variant>.command, inside top, found from where this file is), so it works
    wherever top is moved. A run without that view is left out; older openers in top are replaced."""
    top = Path(top)
    for old in top.glob("View *.command"):
        old.unlink()
    made = []
    for name, folder, scn, key in runs:
        inner = Path(folder) / "paraview" / f"{key}.command"
        if not inner.exists():
            continue
        f = top / f"View {re.sub(r'[/:]+', '-', name)}.command"
        f.write_text(FRONT.format(name=name, label=cfd_report._label(scn, key),
                                  views=inner.parent.relative_to(top).as_posix(),
                                  inner=inner.relative_to(top).as_posix()))
        f.chmod(0o755)
        made.append(f)
    return made


def _one(scn, v, flow_dir, cases, pv_dir, walls, plan, write_only, paraview, log, resume=False):
    case = cases / v.key
    if not resume:
        cfd_droplets.write_stage1(scn, v, flow_dir, case)
    if write_only:
        return {"variant": v.key, "label": v.label, "case": str(case)}, None
    info = run_variant(scn, v, case, log, resume)
    df = cfd_results.droplets(scn, v, case)
    info["accounting"] = cfd_results.accounting(scn, df)
    if (case / cfd_results.GUARD_FILE).exists():
        gone = df[df.removed_in_bad_cell == 1]
        info["removed_in_bad_cells"] = {"n": len(gone), "by_fate": gone.fate.value_counts().to_dict()}
        _say(log, f"  {v.key}: {len(gone)} droplets removed in bad cells (of {len(df):,}): "
                  + ", ".join(f"{n} {f}" for f, n in info["removed_in_bad_cells"]["by_fate"].items()))
    cfd_results.add_landed(case, df)                      # the deposit, into every frame, for ParaView
    if paraview:
        info.update(paraview_state(scn, v, case, pv_dir, walls, plan))
    return info, df


def fresh_stamp(cases_parent: Path, test: str = "") -> str:
    """<date>_<time>_<test>, a name not yet used under cases_parent, claimed by making the folder (runs started in
    the same minute get _2, _3, ...)."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M") + (f"_{test}" if test else "")
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
    top = Path(out) if out else scn.runs_folder / fresh_stamp(scn.runs_folder, _slug(scn.name))
    root = top / DATA
    if " " in str(root):
        raise cfd_droplets.SettingsError(f"--out {top}: OpenFOAM cannot work in a path with spaces")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings_path, root / "settings.yaml")
    for b in base_files(settings_path):
        shutil.copy2(b, root / b.name)
    try:
        run_scenario(scn, root, only, write_only, paraview, checks, log)
    finally:
        write_fronts(top, [(flow_name(scn), root, scn, headline(scn))])
    return top


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
        _save_droplets(scn, root, frames, order)
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


def _save_droplets(scn: CloudScenario, root: Path, frames: list, order: list[str]) -> None:
    """droplets.csv, fates_by_size.csv and bands.csv from every run's droplets."""
    df = pd.concat(frames, ignore_index=True)
    df["variant"] = pd.Categorical(df["variant"].astype(str), categories=order, ordered=True)
    df = df.sort_values(["variant", "d_um", "id"], kind="stable")
    df.to_csv(root / "droplets.csv", index=False, float_format="%.6g")
    cfd_results.fates_by_size(scn, df).to_csv(root / "fates_by_size.csv", index=False)
    cfd_results.bands(scn, df).to_csv(root / "bands.csv", index=False, float_format="%.4f")


def resume_runs(root: Path, only=None, paraview: bool = True, log=print) -> Path:
    """Carry on a finished run's failed runs (a stuck droplet) from their cases' newest frames, guarded
    (_foam_pruning), then remake its results, figures and report.md with them. `only`: which runs (default every one
    run.json lists as failed). The runs that finished are not touched."""
    root = run_files(Path(root).resolve())
    meta = json.loads((root / "run.json").read_text())
    plain, basis = cfd_droplets.read_yaml(root / "settings.yaml")
    plain.setdefault("spray", {}).setdefault("droplets", {})["per_size"] = int(meta["per_size"])
    scn = cfd_droplets.build(plain, basis, Path(meta["settings"]))
    variants = {v.key: v for v in scn.variants()}
    failed = [e.split(":", 1)[0] for e in meta.get("errors", [])]
    want = ([w.strip() for w in only.split(",")] if isinstance(only, str) else list(only)) if only else \
        [k for k in failed if k in variants]
    bad = [w for w in want if w not in variants or not (root / "openfoam" / w).is_dir()]
    if bad:
        raise RunError(f"--resume {root}: no such run to carry on: {bad}")
    if not want:
        log(f"{root}: no failed runs to carry on")
        return root
    flow_dir = Path(meta["flow_copy"])
    walls = _wall_patches(root / "openfoam" / want[0], scn)
    plan = cfd_plots.load_plan(root / "plan_view.npz")
    infos = {r["variant"]: r for r in meta["runs"]}
    errors = [e for e in meta.get("errors", []) if e.split(":", 1)[0] not in want]
    frames = [pd.read_csv(root / "droplets.csv")] if (root / "droplets.csv").exists() else []
    frames = [f[~f.variant.isin(want)] for f in frames]
    log(f"{root}: carrying on {', '.join(want)}")
    with ThreadPoolExecutor(max_workers=min(scn.parallel, len(want))) as pool:
        jobs = {pool.submit(_one, scn, variants[k], flow_dir, root / "openfoam", root / "paraview", walls, plan,
                            False, paraview, log, True): k for k in want}
        for job in as_completed(jobs):
            key = jobs[job]
            try:
                info, df = job.result()
            except Exception as e:                       # one failed run does not stop the others
                errors.append(f"{key}: {e}")
                _say(log, f"  {key}: FAILED: {e}")
                continue
            infos[key] = info
            frames.append(df)
    order = [v.key for v in scn.variants() if v.key in infos]
    meta.update({"runs": [infos[k] for k in order], "errors": errors,
                 "resumed": [*meta.get("resumed", []), {"when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                         "runs": want}]})
    (root / "run.json").write_text(json.dumps(meta, indent=1, default=str))
    if frames:
        _save_droplets(scn, root, frames, order)
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
    figures or report. report.md goes beside a data/ folder (cfd_report.report_path)."""
    root = run_files(Path(root).resolve())
    md = report_path(root)
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
    md.write_text(cfd_report.report(scn, Path(meta["settings"]).name, meta, df, ck, figures, link_prefix(root, md)),
                  encoding="utf-8")
    old = root / "run.md"
    if old.exists():
        old.unlink()
    log(f"report: {md}")
    return md
