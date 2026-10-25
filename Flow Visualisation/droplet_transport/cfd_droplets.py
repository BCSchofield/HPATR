"""Phase 3a: droplets through a CfdOF chamber flow with OpenFOAM's particle tracker (PLAN.md, Phase 3a).

The settings file (settings/droplets_baseline.yaml) is read here into SI units, and the OpenFOAM particle case is
written from it. Two stages, as in the slide test (Ben, 2026-10-25):

    stage 1  the spray on for exposure_s: droplets fed in at the shadowgraph window through the frozen CfdOF flow;
             then the flow kept as it was for flow_after_switch_off_s more (how long the circulation lasts: bracketed)
    stage 2  still air until settle_s after switch-off: the same droplets, restarted with the air at rest

The solver is icoUncoupledKinematicParcelFoam: one-way (the droplets do not push the air), drag (OpenFOAM's
sphereDrag), gravity with buoyancy, turbulent gusts from k (stochasticDispersionRAS) or none, stuck where they touch a
wall (each droplet leaves the tracking at its first touch; the record of the hit keeps where and when, and the
landed droplets are put back into the saved frames afterwards, so ParaView shows the deposit). A run is one
combination of turbulent_gusts and flow_after_switch_off_s (a variant).

One injector per size, one droplet per size per time step, so stage 1's time step is exposure_s / per_size and every
size gets exactly per_size droplets, spread evenly over the exposure. OpenFOAM's per-step count is
floor(rate x step), and the step it sees is a hair short of the set one, so the rate is 1.5 / step (always 1).
OpenFOAM writes only on a frame, so the switch-off and the end of each stage are made to fall on one.
"""
from __future__ import annotations

import itertools
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .settings import ROOT, SettingsError, _num, _sizes, _vec, read_yaml

AXES = "xyz"
G = 9.81
TOL = 1e-6
MAX_STEP_S = 0.0085          # stage 1's step (exposure / per_size) above this: flagged. With gusts off the fines'
                             #   side-wall hits need it: 8.3, 5 and 2.5 ms agree, 25 ms does not (CFD_LOG section 6)


@dataclass(frozen=True)
class Variant:
    gusts: bool
    after_s: float

    @property
    def key(self) -> str:
        return f"gusts_{'on' if self.gusts else 'off'}_after_{self.after_s:g}s"

    @property
    def label(self) -> str:
        return f"gusts {'on' if self.gusts else 'off'}, flow kept {self.after_s:g} s after switch-off"


@dataclass
class CloudScenario:
    name: str
    flow_case: Path
    iteration: int
    spray_patch: str
    port_patches: list
    rho_air: float
    inside: np.ndarray          # (3, 2) m: the chamber's inside walls, low and high on each axis
    up: int                     # the axis gravity points down
    up_sign: float              # +1: up is +axis
    wall_names: dict            # x_min, ... -> a name for each side wall
    rho_d: float
    hole: np.ndarray            # (3,) m
    direction: np.ndarray       # unit vector the spray fires along
    standoff: float             # m
    start_radius: float         # m
    cone_half_angle_deg: float
    speed: float | np.ndarray   # m/s: a number, or [[size_um, m/s], ...] interpolated by size
    sizes_um: np.ndarray
    per_size: int
    distribution: Path | None
    below_dmin_from_um: float
    exposure_s: float
    settle_s: float
    after_s: list
    gusts: list
    spray_frame_s: float
    still_air_frame_s: float
    parallel: int
    runs_folder: Path           # each run's folder goes under it: report, figures, ParaView views, OpenFOAM cases
    bashrc: Path
    paraview_bin: Path
    slice_normal: int
    flow_slices_normal: int     # Ben's CfdOF views: their cuts (hole, port), in every run's view
    tracers: int                # the checks (cfd_checks): tracer droplets per gusts setting (0: none)
    column: np.ndarray | None   # m: where every size is let go from rest (None: no column checks)
    cross_flow: np.ndarray      # m/s: the uniform air of the second column check
    basis: dict
    plain: dict
    source: Path | None = None

    # ---- derived ----
    @property
    def start_centre(self) -> np.ndarray:
        return self.hole + self.standoff * self.direction

    @property
    def gravity(self) -> np.ndarray:
        g = np.zeros(3)
        g[self.up] = -G * self.up_sign
        return g

    @property
    def dt(self) -> float:
        """Stage 1's time step: one droplet of each size per step over the exposure."""
        return self.exposure_s / self.per_size

    @property
    def spray_frame_steps(self) -> int:
        return int(round(self.spray_frame_s / self.dt))

    def variants(self) -> list[Variant]:
        return [Variant(g, a) for g, a in itertools.product(self.gusts, self.after_s)]

    def stage1_steps(self, v: Variant) -> int:
        return self.per_size + int(round(v.after_s / self.dt))

    def still_air(self, v: Variant) -> tuple[int, float]:
        """(steps, step s) of still air, from the end of stage 1 to settle_s after switch-off; each step a frame."""
        span = self.settle_s - v.after_s
        n = max(1, int(round(span / self.still_air_frame_s)))
        return n, span / n

    def speed_for(self, d_um: float) -> float:
        if isinstance(self.speed, np.ndarray):
            return float(np.interp(d_um, self.speed[:, 0], self.speed[:, 1]))
        return float(self.speed)

    def wall_name(self, axis: int, high: bool) -> str:
        key = f"{AXES[axis]}_{'max' if high else 'min'}"
        if key in self.wall_names:
            return str(self.wall_names[key])
        return f"wall {AXES[axis]} {self.inside[axis, int(high)] * 1000:g} mm"


def _path(value, what: str) -> Path:
    if not value:
        raise SettingsError(f"{what}: a path is needed")
    p = Path(os.path.expanduser(str(value)))
    return p if p.is_absolute() else ROOT / p


def _bools(value, what: str) -> list[bool]:
    vals = value if isinstance(value, list) else [value]
    out = []
    for v in vals:
        if isinstance(v, bool):
            out.append(v)
        elif str(v).lower() in ("on", "off", "true", "false", "yes", "no"):
            out.append(str(v).lower() in ("on", "true", "yes"))
        else:
            raise SettingsError(f"{what}: on or off (or a list of them), got {v!r}")
    if not out or len(set(out)) != len(out):
        raise SettingsError(f"{what}: on, off or [on, off]")
    return out


def _multiple(x: float, of: float) -> bool:
    k = x / of
    return abs(k - round(k)) < TOL * max(1.0, abs(k))


def build(plain: dict, basis: dict, source: Path | None = None) -> CloudScenario:
    S = plain
    fl = S.get("flow") or {}
    flow_case = _path(fl.get("case"), "flow.case")
    iteration = int(_num(fl.get("iteration"), "flow.iteration"))
    ports = fl.get("port_patches") or []
    ports = [str(p) for p in (ports if isinstance(ports, list) else [ports])]

    ch = S.get("chamber") or {}
    ins = ch.get("inside_mm")
    if not isinstance(ins, dict) or set(ins) != set(AXES):
        raise SettingsError("chamber.inside_mm: {x: [low, high], y: [low, high], z: [low, high]} in mm")
    inside = np.array([_vec(ins[a], f"chamber.inside_mm.{a}", 2) for a in AXES]) / 1000.0
    if (inside[:, 0] >= inside[:, 1]).any():
        raise SettingsError("chamber.inside_mm: low must be below high on every axis")
    up = str(ch.get("up", "z")).strip().lower()
    sign = -1.0 if up.startswith("-") else 1.0
    up = up.lstrip("+-")
    if up not in AXES:
        raise SettingsError("chamber.up: x, y or z (or -x, ...)")

    sp = S.get("spray") or {}
    dr = sp.get("droplets") or {}
    direction = _vec(sp.get("direction"), "spray.direction")
    if np.linalg.norm(direction) == 0:
        raise SettingsError("spray.direction: not all zero")
    speed = dr.get("speed_m_s")
    if isinstance(speed, list):
        speed = np.array([_vec(p, "spray.droplets.speed_m_s", 2) for p in speed])
        speed = speed[np.argsort(speed[:, 0])]
    else:
        speed = _num(speed, "spray.droplets.speed_m_s")
    dist = dr.get("distribution")
    dist = None if dist in (None, "", "none") else _path(dist, "spray.droplets.distribution")

    st = S.get("slide_test") or {}
    after = st.get("flow_after_switch_off_s", [0])
    after = sorted({_num(a, "slide_test.flow_after_switch_off_s") for a in (after if isinstance(after, list)
                                                                               else [after])})
    ph = S.get("physics") or {}
    r = S.get("run") or {}
    fr = r.get("frames") or {}
    pv = S.get("paraview") or {}
    ck = S.get("checks") or {}
    column = ck.get("column_mm")
    normal = str(pv.get("slice_normal", "z")).lower()
    if normal not in AXES:
        raise SettingsError("paraview.slice_normal: x, y or z")
    normal2 = str(pv.get("flow_slices_normal", "x")).lower()
    if normal2 not in AXES:
        raise SettingsError("paraview.flow_slices_normal: x, y or z")

    scn = CloudScenario(
        name=str(S.get("name") or (source.stem if source else "droplets")),
        flow_case=flow_case, iteration=iteration, spray_patch=str(fl.get("spray_patch", "inlet")),
        port_patches=ports, rho_air=_num(fl.get("air_density_kg_m3", 1.204), "flow.air_density_kg_m3"),
        inside=inside, up=AXES.index(up), up_sign=sign, wall_names=dict(ch.get("wall_names") or {}),
        rho_d=_num((S.get("liquid") or {}).get("density_kg_m3"), "liquid.density_kg_m3"),
        hole=_vec(sp.get("hole_mm"), "spray.hole_mm") / 1000.0, direction=direction / np.linalg.norm(direction),
        standoff=_num(dr.get("standoff_mm"), "spray.droplets.standoff_mm") / 1000.0,
        start_radius=_num(dr.get("start_radius_mm", 0), "spray.droplets.start_radius_mm") / 1000.0,
        cone_half_angle_deg=_num(dr.get("cone_half_angle_deg", 0), "spray.droplets.cone_half_angle_deg"),
        speed=speed, sizes_um=_sizes(dr.get("sizes_um"), "spray.droplets.sizes_um"),
        per_size=int(_num(dr.get("per_size", 200), "spray.droplets.per_size")), distribution=dist,
        below_dmin_from_um=_num(dr.get("below_d_min_from_um", 10), "spray.droplets.below_d_min_from_um"),
        exposure_s=_num(st.get("exposure_s"), "slide_test.exposure_s"),
        settle_s=_num(st.get("settle_s"), "slide_test.settle_s"), after_s=after,
        gusts=_bools(ph.get("turbulent_gusts", True), "physics.turbulent_gusts"),
        spray_frame_s=_num(fr.get("spray_every_s", 0.25), "run.frames.spray_every_s"),
        still_air_frame_s=_num(fr.get("still_air_every_s", 10), "run.frames.still_air_every_s"),
        parallel=max(1, int(_num(r.get("parallel", 4), "run.parallel"))),
        runs_folder=_path(r.get("runs_folder", r.get("cases_folder", "~/OpenFOAM/droplet_runs")), "run.runs_folder"),
        bashrc=_path(r.get("openfoam_bashrc"), "run.openfoam_bashrc"),
        paraview_bin=_path(r.get("paraview_bin"), "run.paraview_bin"),
        slice_normal=AXES.index(normal), flow_slices_normal=AXES.index(normal2), tracers=int(_num(ck.get("tracers", 0), "checks.tracers")),
        column=None if column in (None, "", "none") else _vec(column, "checks.column_mm") / 1000.0,
        cross_flow=_vec(ck.get("cross_flow_m_s", [0, 0, 0]), "checks.cross_flow_m_s"),
        basis=basis, plain=plain, source=source)
    check(scn)
    return scn


def check(scn: CloudScenario):
    """The rules the time steps and frames need (they keep the switch-off and each stage's end on a frame)."""
    if scn.iteration < 0 or scn.per_size < 1:
        raise SettingsError("flow.iteration >= 0 and spray.droplets.per_size >= 1")
    if " " in str(scn.runs_folder):
        raise SettingsError(f"run.runs_folder {scn.runs_folder}: OpenFOAM cannot work in a path with spaces")
    if min(scn.exposure_s, scn.spray_frame_s, scn.still_air_frame_s) <= 0:
        raise SettingsError("slide_test.exposure_s and the run.frames must be positive")
    if scn.after_s[0] < 0 or scn.settle_s <= scn.after_s[-1]:
        raise SettingsError("slide_test: flow_after_switch_off_s >= 0 and settle_s longer than the longest of them")
    if not _multiple(scn.exposure_s, scn.spray_frame_s):
        raise SettingsError(f"slide_test.exposure_s {scn.exposure_s:g} must be a whole number of "
                            f"run.frames.spray_every_s ({scn.spray_frame_s:g} s)")
    frames = int(round(scn.exposure_s / scn.spray_frame_s))
    if scn.per_size % frames:
        raise SettingsError(f"spray.droplets.per_size {scn.per_size} must be a multiple of {frames} (the frames in "
                            f"the exposure, {scn.exposure_s:g} s / {scn.spray_frame_s:g} s): one droplet of each size "
                            f"per time step, and the switch-off on a frame")
    for a in scn.after_s:
        if not _multiple(a, scn.spray_frame_s):
            raise SettingsError(f"slide_test.flow_after_switch_off_s {a:g} must be a whole number of "
                                f"run.frames.spray_every_s ({scn.spray_frame_s:g} s)")
    if (scn.sizes_um <= 0).any() or scn.rho_d <= 0 or scn.rho_air <= 0:
        raise SettingsError("sizes and densities must be positive")
    if isinstance(scn.speed, np.ndarray) and (scn.speed[:, 1] <= 0).any() or \
            not isinstance(scn.speed, np.ndarray) and scn.speed <= 0:
        raise SettingsError("spray.droplets.speed_m_s must be positive")
    lo, hi = scn.inside[:, 0], scn.inside[:, 1]
    c, R = scn.start_centre, scn.start_radius
    if ((c - R) < lo).any() or ((c + R) > hi).any():
        raise SettingsError(f"the droplets' start (hole + standoff {scn.standoff * 1000:g} mm along the spray, radius "
                            f"{R * 1000:g} mm) is not inside chamber.inside_mm: {np.round(c * 1000, 1)} mm")
    if scn.spray_patch in scn.port_patches:
        raise SettingsError("flow: the spray patch cannot also be a port patch")
    if scn.tracers < 0:
        raise SettingsError("checks.tracers: 0 or more")
    if scn.column is not None and ((scn.column <= lo).any() or (scn.column >= hi).any()):
        raise SettingsError(f"checks.column_mm {np.round(scn.column * 1000, 1)}: not inside chamber.inside_mm")


def load(path: Path) -> CloudScenario:
    path = Path(path)
    plain, basis = read_yaml(path)
    return build(plain, basis, path)


# ---- OpenFOAM files ----------------------------------------------------------------------------------------------

HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
  Written by Flow Visualisation (droplet_transport.cfd_droplets)
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    object      {obj};
}}
"""


def foam_file(cls: str, obj: str, body: str) -> str:
    return HEADER.format(cls=cls, obj=obj) + body


def _v(x) -> str:
    return "(" + " ".join(f"{float(a):.9g}" for a in x) + ")"


def read_patches(boundary: Path) -> list[tuple[str, str, int]]:
    """(name, type, nFaces) of each patch in a polyMesh/boundary file."""
    txt = re.sub(r"//[^\n]*", "", Path(boundary).read_text())
    txt = txt[txt.index("}", txt.index("FoamFile")) + 1:]
    out = []
    for m in re.finditer(r"(\w[\w.:-]*)\s*\{([^{}]*)\}", txt):
        body = m.group(2)
        t = re.search(r"\btype\s+(\w+)\s*;", body)
        n = re.search(r"\bnFaces\s+(\d+)\s*;", body)
        if t and n:
            out.append((m.group(1), t.group(1), int(n.group(1))))
    return out


def boundary_faces(mesh: Path, names) -> dict | None:
    """The faces of the named patches, each an (n, 3) array of its corners (m), from an ascii polyMesh; None for a
    binary one (the figures then leave the chamber's objects out)."""
    mesh = Path(mesh)
    pt, fc = (mesh / "points").read_text(), (mesh / "faces").read_text()
    if re.search(r"\bformat\s+binary", pt + fc[:2000]) or re.search(r"\bclass\s+faceCompactList", fc[:2000]):
        return None
    body = re.sub(r"//[^\n]*", "", pt[pt.index("}", pt.index("FoamFile")) + 1:])
    body = body[body.index("(") + 1:]
    P = np.array(body[: body.rindex(")")].replace("(", " ").replace(")", " ").split(), float).reshape(-1, 3)
    lines = fc[fc.index("}", fc.index("FoamFile")) + 1:].splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.strip() == "(") + 1      # one face a line from here
    pats = {}
    txt = re.sub(r"//[^\n]*", "", (mesh / "boundary").read_text())
    for m in re.finditer(r"(\w[\w.:-]*)\s*\{([^{}]*)\}", txt[txt.index("}", txt.index("FoamFile")) + 1:]):
        nf, sf = re.search(r"\bnFaces\s+(\d+)", m.group(2)), re.search(r"\bstartFace\s+(\d+)", m.group(2))
        if nf and sf:
            pats[m.group(1)] = (int(sf.group(1)), int(nf.group(1)))
    out = {}
    for name in names:
        s, n = pats[name]
        out[name] = [P[[int(i) for i in ln[ln.index("(") + 1: ln.rindex(")")].split()]]
                     for ln in lines[first + s: first + s + n]]
    return out


def injector_name(d_um: float) -> str:
    return "d" + f"{d_um:g}".replace(".", "p") + "um"


def injector(scn: CloudScenario, name: str, d_um: float, method: str = "disc", position=None, speed=None,
             count: int | None = None) -> str:
    """One coneNozzleInjection: `count` droplets of one size (default per_size), one per time step from the start,
    on the start disc (or at a point), leaning out up to the cone half-angle."""
    dt = scn.dt
    n = scn.per_size if count is None else count
    disc = method == "disc"
    return f"""        {name}
        {{
            type            coneNozzleInjection;
            SOI             0;
            duration        {n * dt - dt / 2:.9g};
            massTotal       1;
            parcelBasisType fixed;
            nParticle       1;
            parcelsPerSecond {1.5 / dt:.9g};
            flowRateProfile constant 1;
            injectionMethod {method};
            flowType        constantVelocity;
            UMag            {scn.speed_for(d_um) if speed is None else speed:.6g};
            position        constant {_v(scn.start_centre if position is None else position)};
            direction       constant {_v(scn.direction)};
            outerDiameter   {2 * scn.start_radius if disc else 1e-6:.9g};
            innerDiameter   0;
            thetaInner      constant 0;
            thetaOuter      constant {scn.cone_half_angle_deg if disc else 0:.6g};
            sizeDistribution
            {{
                type        fixedValue;
                fixedValueDistribution {{ value {d_um * 1e-6:.9g}; }}
            }}
        }}
"""


def injectors(scn: CloudScenario) -> str:
    """One injector per size: per_size droplets, one per time step over the exposure, on a disc at the window."""
    return "".join(injector(scn, injector_name(d), d) for d in scn.sizes_um)


def cloud_properties(scn: CloudScenario, gusts: bool, patches, inject: bool = True,
                     injection: str | None = None) -> str:
    """The cloud: forces, injectors (none in still air, so a restart can never inject again; `injection` replaces
    the spray's, for the checks), gusts, walls, and a record of every wall hit."""
    names = [p[0] for p in patches]
    # every patch 'escape': a droplet leaves the tracking at its first touch, and the hit record keeps where and when
    # (the same as sticking for where it ends up). OpenFOAM's 'stick' keeps a stuck droplet in the cloud and keeps
    # working out its velocity under gravity, so with a long step each one costs thousands of sub-steps: a still-air
    # step took ~9 s per 20,000 droplets (2026-10-25)
    inter = "\n".join(f"            {n:<16} {{ type escape; }}" for n in names)
    return foam_file("dictionary", "kinematicCloudProperties", f"""
solution
{{
    active          true;
    coupled         false;
    transient       yes;
    cellValueSourceCorrection off;
    maxCo           0.3;
    sourceTerms {{ schemes {{ }} }}
    interpolationSchemes {{ rho cell; U cellPoint; mu cell; k cell; epsilon cell; }}
    integrationSchemes {{ U analytical; }}
}}

constantProperties
{{
    rho0            {scn.rho_d:g};
    youngsModulus   1e9;
    poissonsRatio   0.35;
}}

subModels
{{
    particleForces
    {{
        sphereDrag;
        gravity;
    }}

    injectionModels
    {{
{(injectors(scn) if injection is None else injection) if inject else ''}    }}

    dispersionModel {'stochasticDispersionRAS' if gusts else 'none'};

    patchInteractionModel localInteraction;
    localInteractionCoeffs
    {{
        patches
        (
{inter}
        );
    }}

    surfaceFilmModel none;
    stochasticCollisionModel none;
    collisionModel  none;
}}

cloudFunctions
{{
    hits
    {{
        type             particlePostProcessing;
        maxStoredParcels 1e7;
        patches          ({' '.join(names)});
    }}
}}
""")


def control_dict(start_from: str, end: float, dt: float, write_steps: int) -> str:
    return foam_file("dictionary", "controlDict", f"""
application     icoUncoupledKinematicParcelFoam;
startFrom       {start_from};
startTime       0;
stopAt          endTime;
endTime         {end:.10g};
deltaT          {dt:.10g};
writeControl    timeStep;
writeInterval   {write_steps};
purgeWrite      0;
writeFormat     ascii;
writePrecision  10;
writeCompression off;
timeFormat      general;
timePrecision   8;
runTimeModifiable false;
""")


def zero_velocity() -> str:
    return foam_file("volVectorField", "U", """
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    ".*"
    {
        type            fixedValue;
        value           uniform (0 0 0);
    }
}
""")


DENORMAL = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?[eE]-3\d\d\b")


def round_denormals(text: str) -> str:
    """OpenFOAM writes numbers below ~1e-300 (e.g. 8e-316) that it cannot read back: they become 0."""
    return DENORMAL.sub("0", text)


def time_dirs(case: Path) -> list[tuple[float, Path]]:
    out = []
    for p in Path(case).iterdir():
        if p.is_dir():
            try:
                out.append((float(p.name), p))
            except ValueError:
                pass
    return sorted(out)


def _link_or_copy(src, dst):
    """A hard link (no extra disk; a copy of the folder elsewhere gets the real file), or a copy across disks."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def write_stage1(scn: CloudScenario, v: Variant, flow_dir: Path, case: Path) -> None:
    """The particle case for one variant, from the reconstructed flow (constant/, system/, <iteration>/)."""
    flow_dir, case = Path(flow_dir), Path(case)
    if case.exists():
        shutil.rmtree(case)
    (case / "constant").mkdir(parents=True)
    shutil.copytree(flow_dir / "constant" / "polyMesh", case / "constant" / "polyMesh",     # read only: hard links,
                    copy_function=_link_or_copy)                                           #   real files if copied
    for f in (flow_dir / "constant").iterdir():
        if f.is_file():
            shutil.copy2(f, case / "constant" / f.name)
    tp = case / "constant" / "transportProperties"
    txt = tp.read_text()
    if "rhoInf" not in txt:
        tp.write_text(txt.rstrip() + f"\n\nrhoInf          [1 -3 0 0 0 0 0] {scn.rho_air:g};\n")
    (case / "constant" / "g").write_text(foam_file("uniformDimensionedVectorField", "g", f"""
dimensions      [0 1 -2 0 0 0 0];
value           {_v(scn.gravity)};
"""))
    shutil.copytree(flow_dir / "system", case / "system")
    fs = case / "system" / "fvSchemes"
    txt = fs.read_text()
    fs.write_text(re.sub(r"(ddtSchemes\s*\{[^}]*default\s+)steadyState", r"\1Euler", txt))   # transient tracking
    shutil.copytree(flow_dir / str(scn.iteration), case / "0", ignore=shutil.ignore_patterns("uniform"))
    patches = read_patches(flow_dir / "constant" / "polyMesh" / "boundary")
    (case / "constant" / "kinematicCloudProperties").write_text(cloud_properties(scn, v.gusts, patches))
    end = scn.stage1_steps(v) * scn.dt
    (case / "system" / "controlDict").write_text(control_dict("startTime", end, scn.dt, scn.spray_frame_steps))
    for f in ("flow.foam", "cloud.foam"):           # ParaView's two readers (the flow, the droplets)
        (case / f).touch()


def write_still_air(scn: CloudScenario, v: Variant, case: Path) -> float:
    """Stage 2: restart from stage 1's last frame with the air at rest. Returns that frame's time."""
    case = Path(case)
    t1, last = time_dirs(case)[-1]
    (last / "U").write_text(zero_velocity())
    for f in ("phi", "kinematicCloud:UCoeff", "kinematicCloud:UTrans", "kinematicCloud:rhokTrans"):
        (last / f).unlink(missing_ok=True)                  # phi is recomputed from the still air
    for f in ("k", "omega", "nut", "p"):
        if not (last / f).exists() and (case / "0" / f).exists():
            shutil.copy2(case / "0" / f, last / f)
    cloud = last / "lagrangian" / "kinematicCloud"
    for f in (list(cloud.glob("*")) if cloud.is_dir() else []) + [last / f for f in ("k", "omega", "nut")]:
        if f.is_file():
            txt = f.read_text()
            fixed = round_denormals(txt)
            if fixed != txt:
                f.write_text(fixed)
    patches = read_patches(case / "constant" / "polyMesh" / "boundary")
    (case / "constant" / "kinematicCloudProperties").write_text(cloud_properties(scn, False, patches, inject=False))
    _n, dt2 = scn.still_air(v)
    (case / "system" / "controlDict").write_text(control_dict("latestTime", scn.exposure_s + scn.settle_s, dt2, 1))
    return t1


# the droplet fields ParaView and the results need; the rest are dropped from frames that are not restart points
KEEP_LAGRANGIAN = {"positions", "d", "active", "origId", "origProcId", "U"}


def prune(case: Path, keep_whole: set[float]) -> int:
    """Delete the flow fields (copies of the frozen flow, ~30 MB a frame) and the droplet fields nobody reads from
    every frame except time 0 (the flow) and keep_whole (a restart point). Returns the bytes freed."""
    freed = 0
    for t, d in time_dirs(case):
        if t == 0 or any(abs(t - k) < 1e-9 for k in keep_whole):
            continue
        for p in d.iterdir():
            if p.name == "lagrangian":
                for cloud in p.iterdir():
                    for f in cloud.iterdir():
                        if f.name not in KEEP_LAGRANGIAN:
                            freed += f.stat().st_size
                            f.unlink()
                continue
            if p.is_dir():
                freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                shutil.rmtree(p)
            else:
                freed += p.stat().st_size
                p.unlink()
    return freed
