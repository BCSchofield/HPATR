"""orifice.py -- the exit orifice: its discharge coefficient (orifice_cd.json), the gas-only mass flux it could
pass at the measured upstream pressure, and from the measured gas flux the split of its area between gas and
silicone. No Qt.

THE MODEL (docs/notes/2026-10-13_phase12_physical_variables.md, "Follow-up: the orifice split"):
    G         measured gas mass flux through the orifice (covariates.gas_flux, camera-window gas)
    G_gas     Cd x the ideal gas-only mass flux from P0 (camera-window upstream pressure) to atmosphere:
                choked when Pa/P0 <= (2/(g+1))^(g/(g-1)) (0.528 for g = 1.4):
                    G* = P0 sqrt(g/(R T)) (2/(g+1))^((g+1)/(2(g-1)))
                else subsonic isentropic, r = Pa/P0:
                    G = P0 sqrt(2g/((g-1) R T) [r^(2/g) - r^((g+1)/g)])
    alpha     G / G_gas: the gas share of the orifice area (clipped to [0, 1]; above 1 is flagged)
    u_L       Q_L / ((1 - alpha) A): the silicone speed in the orifice, Q_L the syringe flow (positive
              displacement, so in steady running it IS the silicone leaving the nozzle)
    h         (d/2)(1 - sqrt(alpha)): the film on the wall for an annular exit (gas core, silicone film)
Assumes separated, frozen flow, the gas choked in its share, 20 degC; P0 is read upstream (Alicat), so the
nozzle pressure is lower and alpha is underestimated. Cd is unknown until each insert is measured gas-only
(AI/Real_Data_Code/orifice_cd.py, docs/ORIFICE_CD_TEST.md); until then Cd = 1 and the outputs say so.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

PA_BAR = 1.01325             # atmosphere the spray exits into
T_K = 293.15                 # 20 degC
# (gamma, R J/kg/K) by the run's 'Gas' tag; unknown -> air, and the note says so
GASES = {"air": (1.4, 287.05), "nitrogen": (1.4, 296.8), "co2": (1.29, 188.9)}
CD_FILE = Path(__file__).with_name("orifice_cd.json")
IDEAL = "ideal (not measured)"
DIAMETER_TOL_MM = 0.01
LENGTH_TOL_MM = 0.05


def gas_properties(tag: str | None) -> tuple[str, float, float, str]:
    """(name, gamma, R, note) from the workbook's 'Gas' text ('Nitrogen Gas', 'N2', 'CO2', 'Air' ...)."""
    t = (tag or "").lower().replace(" ", "")
    if "nitrogen" in t or t.startswith("n2") or t == "n₂":
        return ("nitrogen", *GASES["nitrogen"], "")
    if "co2" in t or "carbondioxide" in t or "co₂" in t:
        return ("co2", *GASES["co2"], "")
    if "air" in t:
        return ("air", *GASES["air"], "")
    return ("air", *GASES["air"], f"gas '{tag}' not known: air properties used" if tag else
            "no gas recorded: air properties used")


def critical_ratio(gamma: float) -> float:
    """Pa / P0 at and below which the gas chokes (0.528 for gamma 1.4)."""
    return (2 / (gamma + 1)) ** (gamma / (gamma - 1))


def gas_only_flux(p0_bar: float, gamma: float, R: float, T: float = T_K, pa_bar: float = PA_BAR) -> tuple:
    """(G kg/m2/s, choked) of an ideal (Cd = 1) gas-only orifice from p0_bar to pa_bar; (0.0, False) when P0
    does not exceed Pa."""
    if p0_bar is None or p0_bar <= pa_bar:
        return 0.0, False
    p0 = p0_bar * 1e5
    r = pa_bar / p0_bar
    if r <= critical_ratio(gamma):
        return p0 * math.sqrt(gamma / (R * T)) * (2 / (gamma + 1)) ** ((gamma + 1) / (2 * (gamma - 1))), True
    return p0 * math.sqrt(2 * gamma / ((gamma - 1) * R * T) * (r ** (2 / gamma) - r ** ((gamma + 1) / gamma))), False


# ---- discharge coefficients --------------------------------------------------------------------------------

def load_cd(path: Path | None = None) -> list[dict]:
    """The inserts of orifice_cd.json ([] if it is missing or unreadable: every insert is then ideal)."""
    try:
        data = json.loads(Path(path or CD_FILE).read_text(encoding="utf-8"))
        return [e for e in data.get("inserts", []) if isinstance(e, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def lookup_cd(d_mm: float | None, length_mm: float | None = None, inserts: list | None = None) -> tuple:
    """(Cd, source) for an insert: matched by diameter (within 0.01 mm) and, when both the run and the entry
    have a length, by length too (within 0.05 mm). No match, or cd null: (1.0, 'ideal (not measured)')."""
    inserts = load_cd() if inserts is None else inserts
    if d_mm is None:
        return 1.0, IDEAL
    found = []
    for e in inserts:
        try:
            if abs(float(e["diameter_mm"]) - d_mm) > DIAMETER_TOL_MM:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        el = e.get("length_mm")
        if el is not None and length_mm is not None and abs(float(el) - length_mm) > LENGTH_TOL_MM:
            continue
        found.append(e)
    # a length match first, then a measured Cd
    found.sort(key=lambda e: (not (e.get("length_mm") is not None and length_mm is not None), e.get("cd") is None))
    if not found or found[0].get("cd") is None:
        return 1.0, IDEAL
    e = found[0]
    return float(e["cd"]), ("measured " + str(e.get("measured") or "")).strip()


# ---- the split --------------------------------------------------------------------------------------------

@dataclass
class Split:
    gas_share: float | None = None           # alpha, clipped to [0, 1]
    film_um: float | None = None             # annular film thickness at the exit
    u_liquid_m_s: float | None = None        # silicone speed in the orifice
    note: str = ""


def split(G: float | None, G_gas: float | None, d_mm: float | None, q_liquid_m3s: float | None) -> Split:
    """The gas / silicone split of the orifice area from the measured flux G and the gas-only capacity G_gas
    (both kg/m2/s), d the orifice (mm), Q_L the silicone flow (m3/s; None leaves u_L out)."""
    if G is None or not d_mm:
        return Split()
    if not G_gas or G_gas <= 0:
        return Split(note="upstream pressure at or below atmospheric: no gas-only capacity")
    alpha, note = G / G_gas, ""
    if alpha > 1:
        alpha, note = 1.0, "measured gas exceeds the ideal gas-only capacity: check P0/Cd"
    alpha = max(alpha, 0.0)
    area = math.pi * (d_mm / 1e3) ** 2 / 4
    u = (q_liquid_m3s / ((1 - alpha) * area) if q_liquid_m3s is not None and alpha < 1 else None)
    return Split(alpha, d_mm / 2 * 1e3 * (1 - math.sqrt(alpha)), u, note)


# the maths and assumptions in plain text, beside the per-run table in the workbooks (workbook.annotate_film)
EXPLANATION = (
    "How the gas flux and the silicone film are estimated (diagram above)",
    "G = gas delivered in the camera window (sccm) x recorded gas density / 6e7, over the orifice area "
    "pi d^2 / 4 (kg/m2/s). Exit velocity equivalent = G / gas density: a scale for G, not the jet's speed.",
    "Gas-only capacity = Cd x the ideal mass flux of gas alone from P0 to atmosphere (choked when P0 > 1.89 "
    "x 1.013 barA, else subsonic isentropic), 20 degC, gamma and R from the run's 'Gas' tag (air if unknown).",
    "Gas share alpha = G / capacity: the share of the orifice area the gas occupies; the rest, 1 - alpha, is "
    "silicone.",
    "u_L = syringe flow Q_L / ((1 - alpha) A): the silicone speed in the orifice. The syringe is positive "
    "displacement, so in steady running Q_L is the silicone leaving the nozzle.",
    "Film h = (d/2)(1 - sqrt(alpha)): the silicone film on the wall if the exit is annular (gas core, film).",
    "Assumptions and caveats:",
    "- Cd 'ideal (not measured)' = 1.0 until the insert is measured gas-only (orifice_cd.json, "
    "docs/ORIFICE_CD_TEST.md); a Cd of 0.8 would raise alpha by 25%.",
    "- P0 is read upstream at the Alicat: line and bubbler losses make the nozzle pressure lower, so alpha is "
    "underestimated.",
    "- Separated, frozen flow with the gas choked in its share; the real exit pattern (annular, slug, bubbly) is "
    "not observed. Only runs with a camera window have P0, so only they have a film.",
    "- Covariates, not factors: made from the gas, the pressure and the orifice, so aliased with them. No-spray "
    "runs are left out of the trends.",
)
