"""rsm_detect.py -- work out what response-surface experiment a set of runs forms. No Qt.

Given only the selected run folders (no run sheet needed), as the Taguchi tab does:

    factors      what varies across the runs (design._detect_factors: gas, feed, RPM, orifice,
                 bubbler height, or any run_summary.xlsx field the user adds); what does not vary
                 is listed as held fixed
    levels       per factor, the design levels low / middle / high carrying the runs (uneven
                 spacing allowed). A value that only occurs in a run with every other factor at
                 its centre is SPECIAL: a symmetric pair beyond the levels is an axial pair (and
                 alpha is estimated); a lone value inside the range is an off-grid CHECK point
                 (the 0.8 mm insert); a lone value outside it is a point OUTSIDE the region
                 (the 0 rpm control). Neither of the last two is a level.
    coding       DESIGN coding (low -1, middle 0, high +1, piecewise linear, so an uneven middle
                 still sits at 0) classifies the points; REAL coding ((v - mid-range) / half-range,
                 1.2 mm -> +0.08 on 0.5 / 1.2 / 1.8) is what a fit uses
    point types  corner, face, axial, centre, edge midpoint, check, outside, other; identical
                 settings are grouped as repeats (pure error)
    design type  face-centred CCD, central composite with axial alpha, Box-Behnken, 3^k full
                 factorial, 2^k factorial (+ centres), a regular fraction of either, orthogonal
                 array (Taguchi), or irregular; for a recognised type, exactly which expected
                 points are missing and which runs are extra
    blocks       capture time gives run order; a factor that changes value only about once per
                 level in time order is HARD TO CHANGE (fitted once per block) and so confounded
                 with time of day; several capture days are day blocks; settings repeated inside
                 one block are drift pairs
    Notes        "CCD run 7 centre" (any wording with a point-type word) is cross-checked against
                 the detected point type, and the run numbers against capture order; a
                 disagreement is flagged, never resolved silently
    estimability rank of the full quadratic (real coding) on the runs that would be fitted;
                 which terms are separately estimable; pure-error and lack-of-fit df; when the
                 full quadratic is not estimable, the largest estimable hierarchical model, with
                 what each dropped term is aliased with
    which tab    an orthogonal array -> the Taguchi tab; a CCD / Box-Behnken / factorial -> the
                 Response surface tab; irregular -> response surface with a reduced model

EDITABLE AND SAVED like taguchi_design.json: RsmDesign wraps design.Design (rename / add /
remove factors, override a run's level, leave a run out) and adds validation runs (kept out of
the fit, predicted later) and the block factor (auto, a chosen factor, or none). Saved as
rsm_design.json in the output folder.
"""
from __future__ import annotations

import itertools
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from . import design as dz
from . import run_discovery as rd

SCHEMA = 1
DESIGN_FILENAME = "rsm_design.json"
TOL = 0.03                      # coded values this close are the same point
AXIAL_PAIR_TOL = 0.10           # |alpha+ - alpha-| / alpha for a symmetric axial pair
MIN_COVERAGE = 0.75             # share of a type's expected points needed to call it that type
VIF_NEAR_ALIAS = 50.0           # a kept term this inflated is estimable on paper only (aliased in all but
                                # name: a 4-factor half-fraction CCF gives ~850, a full CCF at most ~3)

CORNER, FACE, AXIAL, CENTRE, EDGE, CHECK, OUTSIDE, OTHER, MISSING = (
    "corner", "face", "axial", "centre", "edge", "check", "outside", "other", "missing")
KIND_TEXT = {CORNER: "corner", FACE: "face centre", AXIAL: "axial", CENTRE: "centre", EDGE: "edge midpoint",
             CHECK: "check point (off-grid)", OUTSIDE: "outside the region", OTHER: "other", MISSING: "incomplete levels"}
NOT_FITTED = (CHECK, OUTSIDE, MISSING)

# Notes wording -> point type. "repeat" alone claims no type (block repeats are faces or centres).
NOTE_KINDS = [(re.compile(r"\bcent(?:re|er)\b", re.I), CENTRE), (re.compile(r"\bcorner\b", re.I), CORNER),
              (re.compile(r"\bface\b", re.I), FACE), (re.compile(r"\b(?:axial|star)\b", re.I), AXIAL),
              (re.compile(r"\bedge\b", re.I), EDGE), (re.compile(r"\bcheck\b", re.I), CHECK),
              (re.compile(r"\b(?:control|no[- ]rotation)\b", re.I), OUTSIDE)]
NOTE_RUN = re.compile(r"\b(?:ccd|rsm|design)?\s*run\s*#?\s*(\d+)", re.I)


def note_kind(notes: str | None) -> str | None:
    hits = {k for rx, k in NOTE_KINDS if rx.search(notes or "")}
    return hits.pop() if len(hits) == 1 else None


def note_run(notes: str | None) -> int | None:
    m = NOTE_RUN.search(notes or "")
    return int(m.group(1)) if m else None


# ---- factors and their levels -----------------------------------------------------------------------

@dataclass
class FactorLevels:
    key: str
    label: str
    levels: list                         # design levels, sorted (2 or 3 usually)
    centre: float | None                 # the centre value (middle level, or mid-range for 2 levels)
    axial: tuple | None = None           # (low axial value, high axial value)
    special: dict = field(default_factory=dict)   # value -> AXIAL | CHECK | OUTSIDE
    numeric: bool = True

    @property
    def low(self):
        return self.levels[0] if self.levels else None

    @property
    def high(self):
        return self.levels[-1] if self.levels else None

    def design_code(self, v) -> float | None:
        """Low -1, middle 0, high +1, piecewise linear (uneven middle still at 0); beyond the
        levels the nearest half extrapolates (an axial value -> +/- alpha)."""
        if v is None or not self.numeric or len(self.levels) < 2:
            return None
        lo, hi, c = float(self.low), float(self.high), float(self.centre)
        v = float(v)
        if v >= c:
            return (v - c) / (hi - c) if hi > c else 0.0
        return (v - c) / (c - lo) if c > lo else 0.0

    def real_code(self, v) -> float | None:
        """(v - mid-range) / half-range: what the fit uses (1.2 on 0.5 / 1.2 / 1.8 -> +0.08)."""
        if v is None or not self.numeric or len(self.levels) < 2:
            return None
        lo, hi = float(self.low), float(self.high)
        return (float(v) - (lo + hi) / 2) / ((hi - lo) / 2)

    def describe(self) -> str:
        lv = " / ".join(dz.norm(x).__str__() for x in self.levels)
        bits = [lv]
        if self.axial:
            bits.append(f"axial {self.axial[0]:g} / {self.axial[1]:g}")
        for v, kind in self.special.items():
            if kind in (CHECK, OUTSIDE):
                bits.append(f"{v:g} ({KIND_TEXT[kind]})")
        return "; ".join(bits)


@dataclass
class RunPoint:
    row: dz.Row
    order: int                           # capture order, 1-based (0 if unknown)
    when: datetime | None
    values: dict                         # factor key -> value
    coded: dict                          # factor key -> design code
    real: dict                           # factor key -> real code
    kind: str
    included: bool = True
    validation: bool = False
    setting: tuple = ()
    group: int = 0                       # repeat group (same setting)
    n_same: int = 1
    block: str | None = None
    noted_kind: str | None = None
    noted_run: int | None = None
    flags: list = field(default_factory=list)

    @property
    def in_fit(self) -> bool:
        return self.included and not self.validation and self.kind not in NOT_FITTED

    @property
    def name(self) -> str:
        return self.row.name


@dataclass
class Term:
    name: str                            # "sccm", "sccm*rpm", "sccm^2"
    parents: tuple                       # factor keys
    separately_estimable: bool = True
    kept: bool = True
    aliases: list = field(default_factory=list)
    vif: float | None = None             # variance inflation in the fitted model (kept terms)


@dataclass
class Estimability:
    n_fit: int
    n_params: int                        # full quadratic, intercept included
    rank: int
    terms: list[Term]
    df_pure_error: int
    df_lack_of_fit: int | None
    full: bool                           # the full quadratic is estimable
    model: list[str]                     # the model that will be fitted (full, or the largest estimable)

    @property
    def dropped(self) -> list[Term]:
        return [t for t in self.terms if not t.kept]

    @property
    def nearly_aliased(self) -> list[Term]:
        return [t for t in self.terms if t.kept and t.vif is not None and t.vif > VIF_NEAR_ALIAS]

    @property
    def usable(self) -> bool:
        """The full quadratic is estimable AND no term is nearly aliased."""
        return self.full and not self.nearly_aliased


@dataclass
class Blocks:
    hard_to_change: list = field(default_factory=list)     # (factor key, label, changes, n levels)
    block_factor: str | None = None                        # the factor used as the block
    days: list = field(default_factory=list)
    segments: list = field(default_factory=list)            # (block label, [RunPoint]) in time order
    drift_pairs: list = field(default_factory=list)         # (block label, first RunPoint, last RunPoint)


@dataclass
class Finding:
    level: str                           # ok | info | warn | error
    text: str


@dataclass
class Detected:
    factors: list[FactorLevels]
    fixed: list[tuple[str, object]]
    points: list[RunPoint]
    design_type: str
    type_key: str                        # ccf | ccd | bbd | full3 | factorial | oa | irregular | none
    alpha: float | None
    complete: bool
    missing: list[dict]                  # expected points not run: {"kind", "coded", "values"}
    extra: list[RunPoint]                # fitted runs that are not one of the type's points
    blocks: Blocks
    estimability: Estimability | None
    recommendation: tuple[str, str]      # (tab, sentence)
    findings: list[Finding]

    @property
    def k(self) -> int:
        return len(self.factors)

    def counts(self) -> dict:
        out: dict = {}
        for p in self.points:
            if p.included:
                out[p.kind] = out.get(p.kind, 0) + 1
        return out

    @property
    def fit_points(self) -> list[RunPoint]:
        return [p for p in self.points if p.in_fit]


# ---- the editable design ------------------------------------------------------------------------------

@dataclass
class RsmDesign:
    """design.Design (factors, overrides, left-out runs) + validation runs + the block factor."""
    base: dz.Design
    validation: set = field(default_factory=set)            # run paths kept out of the fit
    block_factor: str | None = "auto"                       # "auto", a factor key, or None (no block)

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "design": self.base.to_dict(),
                "validation": sorted(str(p) for p in self.validation), "block_factor": self.block_factor}

    def apply_saved(self, saved: dict) -> list[str]:
        if not isinstance(saved, dict) or saved.get("schema") != SCHEMA:
            return ["the saved response-surface design is from a different version and was ignored"]
        notes = self.base.apply_saved(saved.get("design") or {})
        paths = {str(r.path): r.path for r in self.base.rows}
        self.validation = {paths[p] for p in saved.get("validation", []) if p in paths}
        bf = saved.get("block_factor", "auto")
        self.block_factor = bf if bf in (None, "auto") or self.base.has(bf) else "auto"
        return notes

    def detect(self) -> "Detected":
        return analyse(self)


def from_runs(runs: list[rd.RunInfo]) -> RsmDesign:
    return RsmDesign(dz.detect(runs))


def save(d: RsmDesign, output_dir: Path) -> Path:
    from . import jobstate
    path = Path(output_dir) / DESIGN_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    jobstate.atomic_write_json(path, d.to_dict())
    return path


def load_saved(output_dir: Path) -> dict | None:
    try:
        return json.loads((Path(output_dir) / DESIGN_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---- detection ----------------------------------------------------------------------------------------

def _when(row: dz.Row) -> datetime | None:
    try:
        return datetime.strptime(f"{row.date} {row.time}", "%Y-%m-%d %H%M%S")
    except (TypeError, ValueError):
        return None


def _close(a: float, b: float, tol: float = TOL) -> bool:
    return abs(a - b) <= tol


def _centre_guess(rows: list[dz.Row], keys: list[str]) -> dict:
    """The most-repeated full setting if there is one clear one, else each factor's middle value."""
    settings = [tuple(r.value(k) for k in keys) for r in rows]
    counts: dict = {}
    for s in settings:
        if None not in s:
            counts[s] = counts.get(s, 0) + 1
    if counts:
        best = max(counts.values())
        tops = [s for s, n in counts.items() if n == best]
        if best >= 2 and len(tops) == 1:
            return dict(zip(keys, tops[0]))
    out = {}
    for k in keys:
        vals = sorted({r.value(k) for r in rows if isinstance(r.value(k), (int, float))})
        out[k] = vals[len(vals) // 2] if vals else None
    return out


def _factor_levels(rows: list[dz.Row], factors: list[dz.Factor]) -> list[FactorLevels]:
    keys = [f.key for f in factors]
    centre = _centre_guess(rows, keys)
    out = []
    for f in factors:
        vals = [r.value(f.key) for r in rows if r.value(f.key) is not None]
        numeric = bool(vals) and all(isinstance(v, (int, float)) for v in vals)
        distinct = sorted(set(vals), key=lambda x: (str(type(x)), x))
        special = {}
        if numeric:
            others = [o for o in keys if o != f.key]
            for v in distinct:
                if v == centre.get(f.key):
                    continue
                at = [r for r in rows if r.value(f.key) == v]
                if len(at) <= 2 and all(r.value(o) == centre.get(o) for r in at for o in others):
                    special[v] = None
        levels = [v for v in distinct if v not in special]
        if len(levels) < 2:                    # moved only at the centre: those values ARE its levels
            special, levels = {}, distinct
        c = centre.get(f.key)
        if numeric and len(levels) >= 2:
            if len(levels) == 3:
                c = levels[1]
            elif c not in levels:
                c = (levels[0] + levels[-1]) / 2
        out.append(FactorLevels(f.key, f.label, levels, c, special=special, numeric=numeric))
    # special values: symmetric pairs beyond the levels are axial; a lone value inside is a check
    # point, outside (and not at the axial distance of another factor's pair) a point outside
    alphas = []
    for fl in out:
        codes = {v: fl.design_code(v) for v in fl.special if fl.design_code(v) is not None}
        lo = [v for v, c in codes.items() if c < -1 - TOL]
        hi = [v for v, c in codes.items() if c > 1 + TOL]
        for a, b in itertools.product(lo, hi):
            ca, cb = -codes[a], codes[b]
            if abs(ca - cb) / max(ca, cb) <= AXIAL_PAIR_TOL:
                fl.axial = (a, b)
                fl.special[a] = fl.special[b] = AXIAL
                alphas.append((ca + cb) / 2)
                break
    alpha = float(np.mean(alphas)) if alphas else None
    for fl in out:
        for v, kind in list(fl.special.items()):
            if kind is not None:
                continue
            c = fl.design_code(v)
            if c is None:
                fl.special[v] = OTHER
            elif abs(c) < 1 - TOL:
                fl.special[v] = CHECK
            elif alpha is not None and abs(abs(c) - alpha) / alpha <= AXIAL_PAIR_TOL:
                fl.special[v] = AXIAL                      # one of a pair whose partner is missing
            else:
                fl.special[v] = OUTSIDE
    return out


def _classify(coded: list[float | None], specials: list[str | None], k: int) -> str:
    if any(c is None for c in coded):
        return MISSING
    if CHECK in specials:
        return CHECK
    if OUTSIDE in specials:
        return OUTSIDE
    nz = [c for c in coded if abs(c) > TOL]
    if not nz:
        return CENTRE
    if len(nz) == k and all(_close(abs(c), 1) for c in nz):
        return CORNER
    if len(nz) == 1:
        return FACE if _close(abs(nz[0]), 1) else AXIAL if AXIAL in specials else OTHER
    if k >= 3 and len(nz) == 2 and all(_close(abs(c), 1) for c in nz):
        return EDGE
    return OTHER


def _key(coded: tuple) -> tuple:
    return tuple(round(c, 2) for c in coded)


# ---- design types -------------------------------------------------------------------------------------

def _corner_set(k: int) -> set:
    return {tuple(float(x) for x in s) for s in itertools.product((-1, 1), repeat=k)}


def _regular_fraction(corners: set, k: int) -> bool:
    """A regular two-level fraction: closed under element-wise product of any three points."""
    n = len(corners)
    if n < 4 or n >= 2 ** k or n & (n - 1):
        return False
    pts = [np.array(p) for p in corners]
    return all(tuple(float(x) for x in a * b * c) in corners for a, b, c in itertools.combinations(pts, 3))


def _expected(type_key: str, k: int, alpha: float | None, corners_present: set) -> set:
    centre = {tuple(0.0 for _ in range(k))}
    full = _corner_set(k)
    corners = corners_present if _regular_fraction(corners_present, k) else full
    unit = [tuple(float(s) if j == i else 0.0 for j in range(k)) for i in range(k) for s in (-1, 1)]
    if type_key == "ccf":
        return corners | set(unit) | centre
    if type_key == "ccd" and alpha:
        return corners | {tuple(a * alpha for a in u) for u in unit} | centre
    if type_key == "bbd":
        return {tuple(float(s1) if j == a else float(s2) if j == b else 0.0 for j in range(k))
                for a, b in itertools.combinations(range(k), 2) for s1 in (-1, 1) for s2 in (-1, 1)} | centre
    if type_key == "full3":
        return {tuple(float(x) for x in s) for s in itertools.product((-1, 0, 1), repeat=k)}
    if type_key == "factorial":
        return corners | centre
    return set()


def _is_orthogonal_array(pts: set, k: int) -> bool:
    """Strength-2 three-level array smaller than the full factorial: every pair of factors sees every
    pair of levels equally often (an L9 for three factors)."""
    if k < 3 or not pts or len(pts) >= 3 ** k:
        return False
    if any(not any(_close(c, v) for v in (-1, 0, 1)) for p in pts for c in p):
        return False
    for i, j in itertools.combinations(range(k), 2):
        cells: dict = {}
        for p in pts:
            cells[(round(p[i]), round(p[j]))] = cells.get((round(p[i]), round(p[j])), 0) + 1
        if len(cells) != 9 or len(set(cells.values())) != 1:
            return False
    return True


def _match(pts: set, k: int, alpha: float | None) -> tuple[str, set, set]:
    """Best-matching type: (type key, expected points missing, distinct points extra)."""
    corners_present = {p for p in pts if all(_close(abs(c), 1) for c in p)}
    if _is_orthogonal_array(pts, k):
        return "oa", set(), set()
    cands = ["ccf", "bbd", "full3", "factorial"] + (["ccd"] if alpha else [])
    best = None
    for t in cands:
        exp = _expected(t, k, alpha, corners_present)
        if not exp:
            continue
        have = {e for e in exp if any(all(_close(a, b) for a, b in zip(e, p)) for p in pts)}
        extra = {p for p in pts if not any(all(_close(a, b) for a, b in zip(e, p)) for e in exp)}
        cover = len(have) / len(exp)
        score = (cover, -len(extra), -len(exp))
        if best is None or score > best[0]:
            best = (score, t, exp - have, extra)
    if best is None or best[0][0] < MIN_COVERAGE:
        return "irregular", set(), set()
    _, t, miss, extra = best
    return t, miss, extra


def _type_name(t: str, k: int, alpha: float | None, fraction: int | None) -> str:
    frac = f", {fraction}-run fraction of the corners" if fraction else ""
    if t == "ccf":
        return f"face-centred central composite (CCF), {k} factors{frac}" + (
            " (the same points as a 3² full factorial)" if k == 2 else "")
    if t == "ccd":
        rot = (2 ** k if not fraction else fraction) ** 0.25
        kind = "rotatable" if alpha and abs(alpha - rot) / rot < 0.05 else (
            "spherical" if alpha and abs(alpha - math.sqrt(k)) / math.sqrt(k) < 0.05 else "")
        return f"central composite, axial alpha = {alpha:.3g}{' (' + kind + ')' if kind else ''}, {k} factors{frac}"
    if t == "bbd":
        return f"Box-Behnken, {k} factors"
    if t == "full3":
        return f"3^{k} full factorial"
    if t == "factorial":
        return f"two-level factorial with centre points, {k} factors{frac}"
    if t == "oa":
        return "orthogonal array (Taguchi L9)" if k == 3 else f"three-level orthogonal array, {k} factors"
    return "irregular set of runs"


# ---- estimability -----------------------------------------------------------------------------------------

def _terms(keys: list[str]) -> list[Term]:
    lin = [Term(k, (k,)) for k in keys]
    inter = [Term(f"{a}*{b}", (a, b)) for a, b in itertools.combinations(keys, 2)]
    sq = [Term(f"{k}^2", (k, k)) for k in keys]
    return lin + inter + sq


def _column(t: Term, X: dict) -> np.ndarray:
    if len(t.parents) == 1:
        return X[t.parents[0]]
    return X[t.parents[0]] * X[t.parents[1]]


def _rank(cols: list[np.ndarray], n: int) -> int:
    M = np.column_stack([np.ones(n)] + cols) if cols else np.ones((n, 1))
    return int(np.linalg.matrix_rank(M, tol=1e-8 * max(1.0, n)))


def estimability(points: list[RunPoint], keys: list[str]) -> Estimability | None:
    fit = [p for p in points if p.in_fit]
    n = len(fit)
    if n == 0 or not keys:
        return None
    X = {k: np.array([p.real[k] for p in fit], float) for k in keys}
    terms = _terms(keys)
    cols = {t.name: _column(t, X) for t in terms}
    names = [t.name for t in terms]
    full_rank = _rank([cols[x] for x in names], n)
    for t in terms:
        t.separately_estimable = _rank([cols[x] for x in names if x != t.name], n) < full_rank
    full = full_rank == len(terms) + 1
    # largest estimable hierarchical model: drop terms that add nothing to the CURRENT model,
    # squares first, then interactions, then linear terms no kept higher term needs
    kept = list(names)
    order = [t for t in terms if len(t.parents) == 2 and t.parents[0] == t.parents[1]][::-1] + \
            [t for t in terms if len(t.parents) == 2 and t.parents[0] != t.parents[1]][::-1] + \
            [t for t in terms if len(t.parents) == 1][::-1]
    for t in order:
        if len(t.parents) == 1 and any(k in tt.parents for tt in terms if tt.name in kept and tt.name != t.name
                                       for k in t.parents):
            continue
        r_now = _rank([cols[x] for x in kept], n)
        if _rank([cols[x] for x in kept if x != t.name], n) == r_now:
            kept.remove(t.name)
    for t in terms:
        t.kept = t.name in kept
        if not t.kept:
            r = _rank([cols[x] for x in kept], n)
            t.aliases = [u for u in kept
                         if _rank([cols[x] for x in kept if x != u] + [cols[t.name]], n) == r]
    # variance inflation of each kept term (centred columns): rank alone misses near-aliasing
    if len(kept) >= 2 and n > len(kept):
        M = np.column_stack([cols[x] for x in kept])
        M = M - M.mean(axis=0)
        sd = M.std(axis=0)
        live = sd > 1e-12
        if live.sum() >= 2:
            with np.errstate(all="ignore"):
                C = np.corrcoef(M[:, live], rowvar=False)
                v = np.diag(np.linalg.pinv(C))
            for name, val in zip([x for x, ok in zip(kept, live) if ok], v):
                next(t for t in terms if t.name == name).vif = float(val) if np.isfinite(val) else math.inf
    groups: dict = {}
    for p in fit:
        groups.setdefault(p.setting, []).append(p)
    df_pe = sum(len(g) - 1 for g in groups.values())
    p_model = len(kept) + 1
    df_lof = n - p_model - df_pe
    return Estimability(n, len(terms) + 1, full_rank, terms, df_pe, df_lof if df_lof >= 0 else None, full, kept)


# ---- blocks and run order -----------------------------------------------------------------------------------

def _blocks(points: list[RunPoint], factors: list[FactorLevels], choice) -> Blocks:
    b = Blocks()
    timed = sorted([p for p in points if p.included and p.when is not None], key=lambda p: p.when)
    b.days = sorted({p.when.date().isoformat() for p in timed})
    for fl in factors:
        seq = [p.values.get(fl.key) for p in timed if p.values.get(fl.key) is not None]
        if len(seq) < 4:
            continue
        changes = sum(1 for a, c in zip(seq, seq[1:]) if a != c)
        n_lv = len(set(seq))
        if n_lv >= 2 and changes <= n_lv and len(seq) >= 2 * n_lv:
            b.hard_to_change.append((fl.key, fl.label, changes, n_lv))
    if choice == "auto":
        b.block_factor = b.hard_to_change[0][0] if len(b.hard_to_change) == 1 else None
    else:
        b.block_factor = choice if choice in {f.key for f in factors} else None
    if b.block_factor or len(b.days) > 1:
        key = b.block_factor
        cur, seg = None, []
        for p in timed:
            lab = (f"{p.when.date().isoformat()} " if len(b.days) > 1 else "") + (
                f"{next(f.label for f in factors if f.key == key)} = {p.values.get(key)}" if key else "")
            lab = lab.strip()
            if lab != cur and seg:
                b.segments.append((cur, seg))
                seg = []
            cur = lab
            seg.append(p)
            p.block = lab
        if seg:
            b.segments.append((cur, seg))
        for lab, seg in b.segments:
            seen: dict = {}
            for p in seg:
                seen.setdefault(p.setting, []).append(p)
            for same in seen.values():
                if len(same) >= 2:
                    b.drift_pairs.append((lab, same[0], same[-1]))
    return b


# ---- the whole analysis -------------------------------------------------------------------------------------

def analyse(d: RsmDesign) -> Detected:
    base = d.base
    rows = base.rows
    findings: list[Finding] = []
    varying = [f for f in base.factors
               if len({r.value(f.key) for r in rows if r.included and r.value(f.key) is not None}) >= 2]
    for f in base.factors:
        if f not in varying:
            findings.append(Finding("info", f"{f.label} does not vary across the selected runs, so it is "
                                            f"held fixed, not a factor"))
    fixed = []
    for key, (label, source, fld) in dz.BUILTIN.items():
        if any(f.key == key for f in varying):
            continue
        vals = {dz.read_factor(base.runs[r.path], dz.Factor(key, label, source, fld))
                for r in rows if r.included and r.path in base.runs}
        vals.discard(None)
        if len(vals) == 1:
            fixed.append((label, vals.pop()))
    active = [r for r in rows if r.included]
    levels = _factor_levels(active, varying)
    keys = [fl.key for fl in levels]
    k = len(keys)

    # points
    timed = sorted([r for r in rows if _when(r) is not None], key=_when)
    order = {r.path: i for i, r in enumerate(timed, 1)}
    points = []
    for r in rows:
        vals = {fl.key: r.value(fl.key) for fl in levels}
        coded = {fl.key: fl.design_code(vals[fl.key]) for fl in levels}
        real = {fl.key: fl.real_code(vals[fl.key]) for fl in levels}
        specials = [fl.special.get(vals[fl.key]) for fl in levels]
        kind = _classify([coded[x] for x in keys], specials, k) if k else OTHER
        p = RunPoint(r, order.get(r.path, 0), _when(r), vals, coded, real, kind, included=r.included,
                     validation=r.path in d.validation, setting=tuple(vals[x] for x in keys),
                     noted_kind=note_kind(r.notes), noted_run=note_run(r.notes))
        points.append(p)
    groups: dict = {}
    for p in points:
        if p.included and p.kind != MISSING:
            groups.setdefault(p.setting, []).append(p)
    for i, (s, ps) in enumerate(sorted(groups.items(), key=lambda kv: min(p.order for p in kv[1])), 1):
        for p in ps:
            p.group, p.n_same = i, len(ps)

    # design type, on the distinct fitted points
    alpha = None
    axial = [fl for fl in levels if fl.axial]
    if axial:
        alpha = float(np.mean([(abs(fl.design_code(fl.axial[0])) + fl.design_code(fl.axial[1])) / 2
                               for fl in axial]))
    fit_pts = {_key(tuple(p.coded[x] for x in keys)) for p in points if p.in_fit}
    if k == 0:
        t, miss, extra_pts = "none", set(), set()
    elif k == 1:
        t, miss, extra_pts = ("irregular", set(), set())
    else:
        t, miss, extra_pts = _match(fit_pts, k, alpha)
    corners = {p for p in fit_pts if all(_close(abs(c), 1) for c in p)}
    fraction = len(corners) if _regular_fraction(corners, k) else None
    name = _type_name(t, k, alpha, fraction) if t != "none" else "no factor varies"
    extra = [p for p in points if p.in_fit and _key(tuple(p.coded[x] for x in keys)) in extra_pts]
    missing = []
    for m in sorted(miss):
        vals = {}
        for fl, c in zip(levels, m):
            vals[fl.label] = _decode(fl, c)
        missing.append({"kind": _classify(list(m), [None] * k, k), "coded": m, "values": vals})
    complete = t not in ("irregular", "none") and not missing and not extra

    # blocks, notes, estimability
    blocks = _blocks(points, levels, d.block_factor)
    est = estimability(points, keys)
    for p in points:
        if p.noted_kind and p.included and p.kind != MISSING and p.noted_kind != p.kind \
                and not (p.noted_kind == FACE and p.kind == AXIAL):
            p.flags.append(f"Notes say {KIND_TEXT[p.noted_kind]}, the settings are a {KIND_TEXT[p.kind]}")
    numbered = sorted([p for p in points if p.noted_run is not None and p.when], key=lambda p: p.when)
    for a, b in zip(numbered, numbered[1:]):
        if b.noted_run < a.noted_run:
            b.flags.append(f"captured after run {a.noted_run} but numbered run {b.noted_run} (out of the "
                           f"planned order)")

    # findings
    counts: dict = {}
    for p in points:
        if p.included:
            counts[p.kind] = counts.get(p.kind, 0) + 1
    n_fit = sum(1 for p in points if p.in_fit)
    findings.insert(0, Finding("ok" if complete else "warn" if t != "irregular" else "info",
                               f"{name}: {n_fit} runs in the fit (" + ", ".join(
                                   f"{n} {KIND_TEXT[kk]}" for kk, n in sorted(counts.items()) if kk not in NOT_FITTED)
                               + ")"))
    for m in missing:
        findings.append(Finding("warn", f"{KIND_TEXT[m['kind']]} not run: " + ", ".join(
            f"{lab} {v}" for lab, v in m["values"].items())))
    for p in extra:
        findings.append(Finding("warn", f"{p.name[:6]} is not one of the {name.split(',')[0]}'s points "
                                        f"({KIND_TEXT[p.kind]})"))
    for p in points:
        if p.included and p.kind in (CHECK, OUTSIDE):
            what = "an off-grid check point" if p.kind == CHECK else "outside the design region (e.g. a control)"
            findings.append(Finding("info", f"{p.name[:6]} is {what}: kept out of the fit and predicted from it"))
        if p.validation and p.included:
            findings.append(Finding("info", f"{p.name[:6]} is marked as a validation run: kept out of the fit"))
        for fl_ in p.flags:
            findings.append(Finding("warn", f"{p.name[:6]}: {fl_}"))
    for key, label, changes, nl in blocks.hard_to_change:
        findings.append(Finding("warn", f"{label} changed only {changes} time(s) over the session ({nl} values, each "
                                        f"run as one block), so it is confounded with time of day: a drift would "
                                        f"look like its effect"))
    if len(blocks.days) > 1:
        findings.append(Finding("info", f"runs from {len(blocks.days)} days ({', '.join(blocks.days)}): each day "
                                        f"is a block"))
    if blocks.drift_pairs:
        pairs = [f"{a.name[:6]} and {b.name[:6]}" for _, a, b in blocks.drift_pairs if a is not b]
        findings.append(Finding("info", f"{len(pairs)} setting(s) repeated inside a block (drift checks): "
                                        + "; ".join(pairs[:6]) + ("; ..." if len(pairs) > 6 else "")))
    if est is not None:
        if est.full and est.nearly_aliased:
            findings.append(Finding("warn", f"the full quadratic is estimable on paper only: "
                                            + ", ".join(f"{t.name} (VIF {t.vif:.0f})" for t in est.nearly_aliased)
                                            + " are nearly aliased, so their estimates would be meaningless"))
        elif est.full:
            findings.append(Finding("ok", f"full quadratic estimable: {est.n_params} terms on {est.n_fit} runs, "
                                          f"{est.df_pure_error} pure-error df, {est.df_lack_of_fit} lack-of-fit df"))
        else:
            def why(t):
                if not t.aliases:
                    return " (no run varies its factors together)"
                if len(t.aliases) > 3:
                    return " (aliased with a combination of the kept terms)"
                return f" (aliased with {', '.join(t.aliases)})"
            dropped = ", ".join(t.name + why(t) for t in est.dropped)
            findings.append(Finding("warn", f"the full quadratic is not estimable on these runs (rank {est.rank} of "
                                            f"{est.n_params}); the largest estimable model drops: {dropped}"))
    rec = _recommend(t, name, n_fit, counts, est)
    return Detected(levels, fixed, points, name, t, alpha, complete, missing, extra, blocks, est, rec, findings)


def _decode(fl: FactorLevels, c: float):
    """Design code -> real value (inverse of design_code)."""
    lo, hi, mid = float(fl.low), float(fl.high), float(fl.centre)
    v = mid + c * ((hi - mid) if c >= 0 else (mid - lo))
    return dz.norm(v)


def _recommend(t: str, name: str, n_fit: int, counts: dict, est: Estimability | None) -> tuple[str, str]:
    extra_runs = counts.get(CHECK, 0) + counts.get(OUTSIDE, 0)
    tail = f" + {extra_runs} check / control run(s)" if extra_runs else ""
    if t == "oa":
        return "Taguchi", f"{name}: use the Taguchi tab"
    if t in ("ccf", "ccd", "bbd", "full3", "factorial"):
        model = "" if est is None or est.full else " with a reduced model"
        return "Response surface", f"{name}, {n_fit} design runs{tail}: use the Response surface tab{model}"
    if t == "irregular":
        if est is not None and est.full:
            return "Response surface", f"irregular set of {n_fit} runs, full quadratic estimable: response surface"
        return "Response surface", f"irregular set of {n_fit} runs: response surface with a reduced model"
    return "", "no factor varies across the selected runs"
