"""report.md for a Phase 3a run: the headline (where the 0-30 µm band ends up, weighted by the measured spray), the
figures, the checks, the flags, the runs, and every input by how it is known (PLAN.md, Phase 3a, Outputs)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import cfd_results as R
from .report import inputs_section

BAND = (0.0, 30.0)


def _p(x, nd=1) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    return "0" if x == 0 else f"{100 * x:.{nd}f}" if x >= 0.001 else "<0.1"


def _label(scn, key: str) -> str:
    return next((v.label for v in scn.variants() if v.key == key), key)


def headline(scn, df: pd.DataFrame) -> list[str]:
    lo, hi = BAND
    w, info = R.size_weights(scn)
    out = [f"## Headline: where the {lo:g}-{hi:g} µm band ends up", ""]
    if w is None:
        return out + ["No measured size distribution in the settings (`spray.droplets.distribution`): the band's "
                      "shares, each size counted equally, are under *By band* below.", ""]
    covered = sorted(float(s) for s in w.index[(w > 0) & (w.index <= hi)])
    out += [f"Weighted by the spray's measured sizes (`{Path(scn.distribution).name}`): each fired size stands for "
            f"as many droplets as the spray makes of it. Below {info['d_min_um']:g} µm the spray's droplets were "
            f"counted, not sized; they are spread evenly from {scn.below_dmin_from_um:g} µm (estimated), so in this "
            f"weighting the band is in effect {covered[0]:g}-{hi:g} µm." if covered else "", ""]
    for volume in (False, True):
        t = R.weighted_groups(scn, df, w, lo, hi, volume)
        cols = [c for c in [*R.GROUPS, "airborne at switch-off"] if c in t and (t[c] > 0).any()]
        out += [f"**By {'volume (the liquid)' if volume else 'number'}**, % of the band:", "",
                "| run | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        for r in t.to_dict("records"):
            out.append(f"| {_label(scn, r['variant'])} | " + " | ".join(_p(r[c]) for c in cols) + " |")
        out.append("")
    pn = R.floor_purity(scn, df, w, lo, hi)
    pv = R.floor_purity(scn, df, w, lo, hi, volume=True)
    ps = R.floor_purity(scn, df, w, lo, hi, groups=(R.FLOOR_STILL,))
    out += [f"**The band's share of the floor's deposit** (what the slides would collect, summed over the whole "
            f"floor), %:", "", "| run | by number | by volume | by number, landed in still air only |",
            "|---|---|---|---|"]
    for k in pn.index:
        out.append(f"| {_label(scn, k)} | {_p(pn[k])} | {_p(pv[k])} | {_p(ps.get(k))} |")
    out += ["", "*Airborne at switch-off* is a moment; the other columns are where they were when the slides came "
                "out. *Floor, air moving* is where the tracking's near-wall artefact lives (Checks, tracers): read "
                "it for the fines as an upper bound.", ""]
    return out


def checks_section(scn, meta: dict, checks: dict) -> tuple[list[str], list[str]]:
    """The checks, and the flags they raise."""
    out, flags = ["## Checks", ""], []
    runs = meta.get("runs", [])
    acc = [r.get("accounting") for r in runs if r.get("accounting")]
    ok = all(a["ok"] for a in acc) and acc
    out += [f"**1. Every droplet accounted for: {'PASS' if ok else 'FAIL'}.** "
            + "; ".join(f"{_label(scn, r['variant'])}: {r['accounting']['found']:,} of "
                        f"{r['accounting']['fired_expected']:,}" for r in runs if r.get("accounting")) + ".", ""]
    if not ok:
        flags.append("Some droplets are not accounted for (Checks, 1).")
    cases = checks.get("cases", {})
    cols = [cases[k] for k in ("column_still_air", "column_cross_flow") if k in cases]
    if cols:
        worst_v = max(c["worst_speed_pct"] for c in cols)
        worst_x = max(c["worst_path_gap_mm"] for c in cols)
        vs_p1 = max((c["worst_vs_phase1_pct"] or 0) for c in cols)
        good = worst_v < 0.1 and worst_x < 1.0
        out += [f"**2. The tracking against Phase 1's integrator: {'PASS' if good else 'FAIL'}.** Every size let go "
                f"from rest at {np.round(scn.column * 1000).astype(int).tolist()} mm, in still air and in a "
                f"uniform {np.linalg.norm(scn.cross_flow):g} m/s cross-flow, OpenFOAM against Phase 1's integrator "
                f"(physics.analytic_step) with OpenFOAM's drag law and air: speeds within {worst_v:.2g} %, paths "
                f"within {worst_x:.2g} mm, every size.", "",
                f"**3. Settling speeds against Phase 1's physics: {'PASS' if vs_p1 < 1 else 'within 3 %'}.** "
                f"Largest difference {vs_p1:.1f} %, at the largest sizes: OpenFOAM's sphereDrag (Putnam, "
                f"f = 1 + Re^⅔/6) against Phase 1's Schiller-Naumann (f = 1 + 0.15 Re^0.687), which part at Re of a "
                f"few (a 200 µm droplet settles at Re ≈ 9). Below ~60 µm (Re < 1) they agree within ~0.5 %, "
                f"the rest being the air's viscosity (CfdOF's ν against Sutherland's law). "
                "`figures/check_column.png`.", ""]
        if not good:
            flags.append("OpenFOAM's tracking disagrees with Phase 1's integrator (Checks, 2).")
    tv = checks.get("tracers_vs_sizes", [])
    if tv:
        sz = list(tv[0]["sizes"])
        out += ["**4. Tracers: the near-wall artefact: FLAG.** "
                f"{max(c.get('fired', 0) for k, c in cases.items() if k.startswith('tracers')) or scn.tracers:,} "
                "droplets of 0.5 µm, which follow the air, fed in like the spray for the "
                f"{scn.exposure_s:g} s exposure. None should touch a wall (the air does not flow into one), yet:", "",
                "| gusts | tracers on the floor | tracers on any wall | " + " | ".join(f"{s} µm on the floor"
                                                                              for s in sz) + " |",
                "|---|---|---|" + "---|" * len(sz)]
        for r in tv:
            out.append(f"| {'on' if r['gusts'] else 'off'} | {_p(r['tracers_floor'])} % | "
                       f"{_p(r['tracers_any_wall'])} % | " + " | ".join(f"{_p(r['sizes'].get(s))} %" for s in sz)
                       + " |")
        out += ["", "(The fired sizes: landed on the floor by switch-off, in the run with the flow kept "
                    f"{scn.after_s[0]:g} s.)", "",
                "Why (found 2026-10-25, in scratch): every tracer reaches the floor at exactly its own settling "
                "speed (8 µm/s), and with gravity off none touches it. In the cell against a wall OpenFOAM "
                "interpolates the air linearly, so its speed towards the wall falls only in proportion to height "
                "and a droplet riding it closes in exponentially fast, to within nanometres, where settling "
                "finishes the job. At a real no-slip wall that speed falls with height squared and the droplet is "
                "swept along instead. The floor share does not depend on the time step (the same at 0.1, 1, 5 "
                "and 25 ms; check 7 for what does). "
                "Most tracers land on their first pass down the jet, within ~80 mm of its impact point (the "
                "floor cells there are 1.3 mm deep). So every droplet small enough to follow the air near the "
                "floor is over-collected while the air moves, most for the smallest, fading where settling or "
                "momentum take over (compare the sizes above with the tracers). With gusts on, the random gusts "
                "also carry tracers to every wall (an isotropic gust model near a wall over-predicts that too).",
                "", "`figures/check_tracers.png`.", ""]
        flags.append("**The near-wall artefact (Checks, 4):** while the air moves, the fines' floor and wall "
                     "counts are too high and their airborne shares too low (the tracers' row is the size of it). "
                     "Landings in still air are not affected; nor are the large droplets.")
    gc = checks.get("gusts", [])
    if gc:
        a = scn.after_s[len(scn.after_s) // 2]
        rows = [g for g in gc if g["after_s"] == a]
        out += [f"**5. Gusts on against off (flow kept {a:g} s).** The fines' deposit should change, the large "
                "droplets' should not:", "",
                "| band | floor, on | floor, off | centre moved (mm) | half within (mm), on | off |",
                "|---|---|---|---|---|---|"]
        for g in rows:
            s = g["centre_shift_mm"]
            out.append(f"| {g['band']} | {_p(g['on']['floor'])} % | {_p(g['off']['floor'])} % | "
                       f"{'–' if s is None else f'{s:.1f}'} | {g['on'].get('r50_mm', float('nan')):.0f} | "
                       f"{g['off'].get('r50_mm', float('nan')):.0f} |")
        big = [g for g in rows if g["band"].startswith(">")]
        if big and big[0]["centre_shift_mm"] is not None:
            b = big[0]
            same = b["centre_shift_mm"] < 3 and abs(b["on"]["r50_mm"] - b["off"]["r50_mm"]) < 3
            out += ["", f"Large droplets ({b['band']}): {'PASS' if same else 'CHECK'}: their deposit's centre "
                        f"moved {b['centre_shift_mm']:.1f} mm and its median distance from the impact point "
                        f"{b['on']['r50_mm']:.0f} against {b['off']['r50_mm']:.0f} mm."]
        out.append("")
    lg = checks.get("large", [])
    if lg:
        from .cfd_checks import LARGE_UM, NEAR_MM
        worst = max(g.get("r90_mm", 0) for g in lg)
        out += [f"**6. Large droplets (≥ {LARGE_UM} µm) land near the jet's impact point: "
                f"{'PASS' if worst <= NEAR_MM else 'CHECK'}.** 90 % of them within {worst:.0f} mm of it in every run "
                f"(median {min(g.get('r50_mm', 0) for g in lg):.0f}-{max(g.get('r50_mm', 0) for g in lg):.0f} mm); "
                f"the floor takes {min(g['floor'] for g in lg) * 100:.1f}-{max(g['floor'] for g in lg) * 100:.1f} %. "
                f"(Near: within {NEAR_MM} mm, the atomiser body's half-width.)", ""]
    from .cfd_droplets import MAX_STEP_S
    ok = scn.dt <= MAX_STEP_S
    need = int(np.ceil(scn.exposure_s / MAX_STEP_S / 20) * 20)                 # per_size is a multiple of 20
    out += [f"**7. The time step while the spray is on: {'PASS' if ok else 'FLAG'}.** {scn.dt * 1000:.1f} ms "
            f"(the exposure / {scn.per_size} per size); at most {MAX_STEP_S * 1000:g} ms. With gusts off a longer "
            "step sends the fines to the side walls: 0-10 µm, 12 % on the side walls at 25 ms against 2 % at 8.3, 5 "
            "and 2.5 ms (which agree), and 13 % against 24 % airborne at switch-off (found 2026-10-25, Phase 3a "
            "Part D). With gusts on, and for the larger sizes, the step does not matter.", ""]
    if not ok:
        flags.append(f"**The time step (Checks, 7)** is {scn.dt * 1000:.1f} ms: with gusts off the fines' side-wall "
                     f"counts are too high and their airborne shares too low. For numbers, {need} or more per size.")
    return out, flags


def report(scn, settings_name: str, meta: dict, df: pd.DataFrame, checks: dict, figures: list) -> str:
    L = [f"# Droplets through the CFD flow: {scn.name}", "",
         f"{meta['when']} · `{settings_name}` · Phase 3a (PLAN.md) · droplet_transport {meta['version']}. "
         f"{scn.sizes_um.size} sizes, {scn.sizes_um.min():g}-{scn.sizes_um.max():g} µm, {scn.per_size} of each "
         f"({scn.sizes_um.size * scn.per_size:,} a run), {len(meta['runs'])} runs, through "
         f"`{scn.flow_case}` at iteration {scn.iteration}.", "",
         "> **What it cannot say yet.** The sub-30 µm sizes in the measured spray are estimated (counted, not "
         "sized; the slides measure them). The start speed is estimated (Phase 5 measures it). Near the nozzle the "
         "liquid carries as much mass as the gas; its push on the air is left out. The flow is one steady "
         "snapshot of a flow that sways (Part D's snapshot check says how much that matters). Droplets stick where "
         "they first touch: no bounce or splash. **While the air moves, the fines' floor and wall counts are too "
         "high (Checks, 4).**", ""]
    L += headline(scn, df)
    figs = dict(figures)
    L += ["## The floor deposit by size band", "",
          "Seen from above, in the CAD's mm. The dashed outline is the atomiser body, nozzle block and arm (from "
          "the mesh), the ring the exit orifice (the jet lands straight below it), the thick line the port. Colour: "
          "how densely each band landed, % of the band fired per cm², one log scale; the lines enclose the densest "
          "half and 90 %. Each size counted equally.", ""]
    for f, desc in figures:
        if f.startswith("floor_"):
            L += [f"**{desc}**", "", f"![{desc}](figures/{f})", ""]
    if "fates_by_size.png" in figs:
        L += ["## Where each size ends up", "", "![where each size ends up](figures/fates_by_size.png)", ""]
    ck, flags = checks_section(scn, meta, checks)
    L += ck
    if "check_tracers.png" in figs:
        L += ["![tracers](figures/check_tracers.png)", ""]
    if "check_column.png" in figs:
        L += ["![column](figures/check_column.png)", ""]
    L += ["## Flags", ""] + [f"- {f}" for f in flags] + [
        "- The slide positions are not in yet (the slide-comparison step): the maps cover the whole floor.", ""]
    L += ["## Runs", "", "| run | droplets accounted for | stage 1 | stage 2 | ParaView |", "|---|---|---|---|---|"]
    for r in meta["runs"]:
        a = r.get("accounting", {})
        acc = (f"{a['found']:,} of {a['fired_expected']:,}" + ("" if a["ok"] else " **(check)**")) if a else ""
        pv = f"`paraview/{r['variant']}.command`" if r.get("pvsm") else ""
        L.append(f"| {r['label']} | {acc} | {r.get('stage1_s', 0):.0f} s | {r.get('stage2_s', 0):.0f} s | {pv} |")
    L += ["", f"All runs and checks together took {meta['wall_clock_s'] / 60:.1f} min ({scn.parallel} at once). "
              f"Spray: {scn.dt * 1000:g} ms steps (one droplet of each size a step); still air ~"
              f"{scn.still_air_frame_s:g} s steps.", ""]
    if meta.get("errors"):
        L += ["**Failed:**", ""] + [f"- {e}" for e in meta["errors"]] + [""]
    first = next((r for r in meta["runs"] if r.get("pvsm")), None)
    if first:
        here = meta.get("root") or str(Path(first["pvsm"]).parent.parent)
        L += ["**Open a run in ParaView:** double-click its `paraview/<run>.command` in Finder; it works wherever this "
              "folder is copied or moved (copy the whole folder). Then First Frame, Play; *0-30 µm band only* and "
              "*still airborne only* are hidden: click their eyes. Or paste:", "", "```",
              f'open "{here}/paraview/{first["variant"]}.command"', "```", ""]
    bt = pd.read_csv(meta["bands_csv"]) if meta.get("bands_csv") and Path(meta["bands_csv"]).exists() else None
    if bt is not None:
        L += ["## By band, each size counted equally", "",
              "Share of the droplets fired in each band, %, not weighted by the spray.", ""]
        for var, g in bt.groupby("variant", sort=False):
            cols = [c for c in g.columns if c not in ("variant", "band", "fired")]
            L += [f"**{_label(scn, var)}**", "", "| band | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
            for row in g.to_dict("records"):
                L.append(f"| {row['band']} | " + " | ".join(_p(row[c]) for c in cols) + " |")
            L.append("")
    L += [""] + inputs_section(scn) + [""]
    L += ["## Files", "",
          "- `figures/`: " + "; ".join(f"`{f}` {d}" for f, d in figures) + ".",
          "- `droplets.csv`: one row per droplet: run, size, fate, when and where it landed (mm, the CAD's "
          "coordinates), still airborne at switch-off.",
          "- `fates_by_size.csv`: per run and size, how many ended up where. `bands.csv`: the tables above.",
          "- `checks.json`, `checks_column.csv`, `checks_tracers.csv`: the checks' numbers.",
          "- `plan_view.npz`: the chamber seen from above (from the mesh), for the maps.",
          f"- `openfoam_cases/` (a link to `{meta['cases']}`): the OpenFOAM cases, with their logs.",
          "- `settings.yaml`: the settings as run.", ""]
    return "\n".join(L)
