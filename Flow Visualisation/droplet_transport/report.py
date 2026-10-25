"""report.md for a run and sweep_report.md for a sweep: the headline, the band, the flags, the gas flow, and every
input by how it is known (PLAN.md ground rule: every assumed number is labelled)."""
from __future__ import annotations

import math

import numpy as np

HEADLINE_SIZES = (2, 6, 10, 14, 18, 22, 26, 30, 40, 60, 100, 200)   # the nearest fired size of each, once


def _p(x, nd=1):
    return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{100 * x:.{nd}f} %"


def _f(x, fmt="{:.1f}"):
    return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def inputs_section(scn) -> list[str]:
    out = ["## Inputs, by how they are known", ""]
    order = ("estimated", "measured", "design choice")
    rows = sorted(scn.basis.items(), key=lambda kv: (next((i for i, o in enumerate(order) if kv[1][0].startswith(o)),
                                                          9), kv[0]))
    out += ["| setting | value | known as |", "|---|---|---|"]
    for path, (basis, value) in rows:
        out.append(f"| `{path}` | {value} | {basis} |")
    n_est = sum(1 for b, _v in scn.basis.values() if b.startswith("estimated"))
    out += ["", f"{n_est} inputs are estimates; each is replaced when it is measured (the stand-off and the droplet "
                "speeds on the velocity rig day, Phase 5)."]
    return out


def gas_section(scn, flow) -> list[str]:
    sx = flow.notes["spray"]
    sp = scn.spray
    out = ["## The gas flow (idealised)", "",
           "| jet | gas flow | exit area | exit speed | Mach | choked | upstream p0 | momentum | effective speed |",
           "|---|---|---|---|---|---|---|---|---|",
           f"| spray ({sp.orifice_mm:g} mm, Cd {sp.orifice_cd:g}) | {sp.gas_flow_sccm:,.0f} sccm "
           f"({sx['mdot_kg_s'] * 1e6:.0f} mg/s) | {sx['area_m2'] * 1e6:.3f} mm² | {sx['exit_speed_m_s']:.0f} m/s | "
           f"{sx['mach']:.2f} | {'yes' if sx['choked'] else 'no'} | {sx['p0_Pa'] / 1e5:.2f} barA | "
           f"{sx['momentum_N'] * 1e3:.1f} mN | {sx['effective_speed_m_s']:.0f} m/s |"]
    for p in scn.inlets:
        ex = flow.notes[p.name]
        out.append(f"| {p.name} ({p.shape}) | {p.flow_sccm:,.0f} sccm ({ex['mdot_kg_s'] * 1e6:.0f} mg/s) | "
                   f"{p.area * 1e6:.1f} mm² | {_f(ex.get('exit_speed_m_s'), '{:.2f}')} m/s | "
                   f"{_f(ex.get('mach'), '{:.3f}')} | no | – | {ex['momentum_N'] * 1e3:.3f} mN | "
                   f"{_f(ex.get('effective_speed_m_s'), '{:.2f}')} m/s |")
    jet = flow.jet("spray")
    out += ["", f"- The spray jet: u_c = B K / (s + B d0) with K = {jet.K:.3f} m²/s and d0 = {jet.d0 * 1e3:.2f} mm "
                f"(the momentum-equivalent exit at chamber density): {float(jet.centreline(0.1)):.1f} m/s at 100 mm, "
                f"{float(jet.centreline(0.3)):.1f} m/s at 300 mm below the nozzle.",
            f"- Drift (through-flow over the chamber's cross-section): {flow.notes['drift_m_s'] * 1000:.1f} mm/s."]
    if sp.liquid_flow_ml_min:
        from . import injection
        mdot_l = sp.liquid_flow_ml_min * 1e-6 / 60.0 * scn.rho_d
        v = float(np.mean(injection.speed_for(sp, sp.sizes_um)))
        out.append(f"- The liquid's momentum ({sp.liquid_flow_ml_min:g} mL/min at ~{v:g} m/s) is "
                   f"{mdot_l * v * 1e3:.2f} mN, {100 * mdot_l * v / sx['momentum_N']:.0f} % of the gas's: "
                   "not added (PLAN.md Phase 2 decides whether to).")
    return out


def run_report(ctx: dict) -> str:
    scn, flow, ps, ps_off = ctx["scn"], ctx["flow"], ctx["ps"], ctx["ps_off"]
    m, m_off = ctx["metrics"], ctx["metrics_off"]
    lo, hi = scn.band_um
    title = f"# {scn.name}{': ' + scn.label if scn.label else ''}"
    out = [title, "",
           f"Flow Visualisation Phase 1 (idealised flow), droplet_transport {ctx['version']}, {ctx['when']}. "
           f"Settings: `{ctx['settings_name']}`. {ctx['n_fired']:,} droplets ({scn.spray.per_size} per size, "
           f"{scn.spray.sizes_um.size} sizes {scn.spray.sizes_um[0]:g}-{scn.spray.sizes_um[-1]:g} um) in "
           f"{ctx['seconds']:.1f} s.", "",
           "> **Idealised flow.** Textbook jets added together: no recirculation, and the walls do not turn the flow, "
           "so the jets pass through the floor and walls. In the closed chamber the spray jet's circulation "
           "dominates, so delivery and purity here are idealised; the headline is how far the jets carry or deflect "
           "each size. Thesis numbers come from Phase 3 (PLAN.md).", ""]

    out += ["## Headline: what the cross-stream does to each size", ""]
    if scn.planes and ps_off is not None:
        from .plots import cross_axis
        ax_i, at, pname = scn.planes[0]
        a = "xyz"[cross_axis(scn, ax_i)]
        mean = f"{pname}: {a} mean mm"
        stw = [c for c in ps.columns if c.startswith("St spray at the")][0]
        st_in = [c for c in ps.columns if c.startswith("St ") and c != stw]
        out += [f"Where each size crosses **{pname}** ({'xyz'[ax_i]} = {at * 1000:g} mm), along {a}, with the "
                "inlets on and off (the same droplets, the same starts):", "",
                f"| size (um) | crossing on (%) | {a} on (mm) | {a} off (mm) | shift (mm) | to target on | off | "
                + " | ".join(st_in) + f" | {stw} |",
                "|---" * (7 + len(st_in) + 1) + "|"]
        for k in sorted({int(np.argmin(np.abs(ps["size_um"].to_numpy() - s))) for s in HEADLINE_SIZES}):
            r, ro = ps.iloc[k], ps_off.iloc[k]
            out.append(f"| {r['size_um']:g} | {100 * r[f'{pname}: crossed']:.0f} | {_f(r[mean])} | {_f(ro[mean])} | "
                       f"{_f(r[mean] - ro[mean], '{:+.1f}')} | {_p(r['target'])} | {_p(ro['target'])} | "
                       + " | ".join(_f(r[c], "{:.2g}") for c in st_in) + f" | {_f(r[stw], '{:.2g}')} |")
        out += ["", f"Band {lo:g}-{hi:g} um, mean shift along {a}: {_f(ctx['band_shift_mm'], '{:+.1f}')} mm, i.e. "
                    f"**pushed {_f(ctx['band_push_mm'], '{:.1f}')} mm along the cross-stream** by the time it crosses "
                    f"{pname}. "
                    "St = tau x u_c / (2 r_1/2): the Stokes number in each jet, for an inlet where its jet passes "
                    "closest to the spray's axis."]
    else:
        out += ["(No plane, or no inlets to compare: see the figures.)"]

    out += ["", f"## The band, {lo:g}-{hi:g} um (idealised)", "",
            "| | inlets on | inlets off |", "|---|---|---|",
            f"| delivery, by number | {_p(m.get('delivery_number'))} | {_p((m_off or {}).get('delivery_number'))} |",
            f"| delivery, by volume | {_p(m.get('delivery_volume'))} | {_p((m_off or {}).get('delivery_volume'))} |",
            f"| purity, by number | {_p(m.get('purity_number'))} | {_p((m_off or {}).get('purity_number'))} |",
            f"| purity, by volume | {_p(m.get('purity_volume'))} | {_p((m_off or {}).get('purity_volume'))} |", "",
            f"Weighting: {m.get('weighting')}."]
    if m.get("purity_number") is not None:
        out.append(f"What else arrives: below the band {_p(m.get('arrivals_below_band_number'))} by number "
                   f"({_p(m.get('arrivals_below_band_volume'))} by volume), above it "
                   f"{_p(m.get('arrivals_above_band_number'))} ({_p(m.get('arrivals_above_band_volume'))}).")

    out += ["", "## Flags", ""] + [f"- {f}" for f in ctx["flags"]]
    out += [""] + gas_section(scn, flow) + [""] + inputs_section(scn)
    out += ["", "## Figures", ""] + [f"- `figures/{f}`: {d}" for f, d in ctx["figures"]]
    out += ["", "## Files", "",
            "- `per_size.csv`: every fired size: its fates, tau, settling speed, Stokes numbers, plane crossings.",
            "- `droplets.csv`: every droplet: size, start, fate, where and when it ended, plane crossings"
            + (", number weight." if ctx.get("weighted") else "."),
            "- `deflection.csv`: per size, the crossing shift by the inlets and the target shares on and off.",
            "- `summary.json`: the numbers above, the gas flow, the accounting.",
            "- `settings.yaml` (and any base file it starts from, under its own name): the settings as run, in the top "
            "output folder; "
            "a sweep's run changes only what its title says."]
    return "\n".join(out) + "\n"


def sweep_report(name, settings_name, when, axes, table, runs, figures, version) -> str:
    out = [f"# {name}: sweep", "",
           f"Flow Visualisation Phase 1 (idealised flow), droplet_transport {version}, {when}. Settings: "
           f"`{settings_name}`. {len(table)} runs: " + "; ".join(f"`{p}` = {v}" for p, v in axes) + ".", "",
           "> Idealised flow (see each run's report): trends and orders of magnitude, not thesis numbers.", "",
           "| run | " + " | ".join(p for p, _v in axes) + " | delivery (number) | delivery (volume) | "
           "purity (number) | purity (volume) | band pushed (mm) | delivery off (number) |",
           "|---" * (len(axes) + 7) + "|"]
    for (_i, r), (folder, _lab) in zip(table.iterrows(), runs):
        out.append(f"| [{folder}](runs/{folder}/report.md) | " + " | ".join(str(r[p]) for p, _v in axes) +
                   f" | {_p(r['delivery_number'])} | {_p(r['delivery_volume'])} | {_p(r['purity_number'])} | "
                   f"{_p(r['purity_volume'])} | {_f(r['band_push_mm'], '{:.1f}')} | "
                   f"{_p(r['delivery_number off'])} |")
    out += ["", "## Figures", ""] + [f"- `figures/{f}`: {d}" for f, d in figures]
    out += ["", "`sweep.csv` holds the table; each run's folder holds its own report, figures and CSVs."]
    return "\n".join(out) + "\n"
