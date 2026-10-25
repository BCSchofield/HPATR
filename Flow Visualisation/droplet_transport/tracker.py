"""Fire the droplets through the gas flow and follow each one to its fate.

Each droplet ends as one of (PLAN.md, Phase 1):
    outlet:<name>   left through that outlet (the target, when it is the target outlet)
    target          entered the target box (when the target is a box)
    wall:<wall>     touched a wall and stuck (silicone sticks), where it touched is kept
    airborne        still in the air at the time limit

The step: the analytic exponential step (physics.analytic_step) with dt so that the droplet moves no more than
run.step_mm (judged on the faster of its own speed and the speed it is relaxing to), and no more than run.max_step_s.
The random walk (off by default): each droplet sees the mean gas velocity plus a fluctuation drawn from a normal
distribution of rms intensity x |mean gas speed| per component, held for time_scale_s, then redrawn.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import physics

FACES = ("left", "front", "floor", "right", "back", "lid")     # axis 0, 1, 2 at 0; then at the far side


@dataclass
class Track:
    fate: np.ndarray            # (N,) str
    end: np.ndarray             # (N, 3) m, where it ended
    t_end: np.ndarray           # (N,) s
    v_end: np.ndarray           # (N, 3) m/s
    crossings: list             # per plane: {"pos": (N, 3), "t": (N,), "v": (N, 3)}, nan where not crossed
    paths: dict                 # droplet index -> (M, 4) array: x, y, z (m), speed (m/s)
    iterations: int
    timed_out: int = 0
    notes: dict = field(default_factory=dict)


def track(scn, flow, drops, rng: np.random.Generator | None = None, record=None,
          max_iterations: int = 2_000_000) -> Track:
    rng = rng or np.random.default_rng(scn.run["seed"])
    N = drops.d.size
    x, v = drops.x0.astype(float).copy(), drops.v0.astype(float).copy()
    t = np.zeros(N)
    alive = np.ones(N, bool)
    fate = np.full(N, "airborne", dtype=object)
    end = np.full((N, 3), np.nan)
    v_end = np.full((N, 3), np.nan)
    t_end = np.full(N, np.nan)
    crossings = [{"pos": np.full((N, 3), np.nan), "t": np.full(N, np.nan), "v": np.full((N, 3), np.nan)}
                 for _ in scn.planes]
    tau0 = physics.tau_stokes(drops.d, scn.rho_d, scn.gas)
    a = physics.gravity_vector(scn.rho_d, scn.gas, scn.gravity)
    rho, mu, law = scn.gas.density, scn.gas.viscosity, scn.drag
    L = scn.box
    step, max_dt, t_max = scn.run["step_mm"] / 1000.0, scn.run["max_step_s"], scn.run["max_time_s"]
    rw = scn.random_walk
    uprime = np.zeros((N, 3))
    eddy_left = np.zeros(N)
    outlets_on = {f: [p for p in scn.outlets if p.wall == f] for f in FACES}
    tbox = scn.target_box
    rec = np.zeros(N, bool) if record is None else np.asarray(record, bool)
    path_ids, path_pts = [np.flatnonzero(rec)], [np.c_[x[rec], np.linalg.norm(v[rec], axis=1)]]

    def finish(ids, label_or_labels, where, when, vel):
        fate[ids] = label_or_labels
        end[ids], t_end[ids], v_end[ids] = where, when, vel
        alive[ids] = False

    it = 0
    while it < max_iterations:
        idx = np.flatnonzero(alive)
        if idx.size == 0:
            break
        it += 1
        P, V, d = x[idx], v[idx], drops.d[idx]
        ug = flow.velocity(P)
        if rw["on"]:
            need = eddy_left[idx] <= 0.0
            if need.any():
                sig = rw["intensity"] * np.linalg.norm(ug[need], axis=1)
                uprime[idx[need]] = rng.standard_normal((int(need.sum()), 3)) * sig[:, None]
                eddy_left[idx[need]] = rw["time_scale_s"]
            ug = ug + uprime[idx]
        slip = np.linalg.norm(ug - V, axis=1)
        tau = tau0[idx] / physics.drag_factor(rho * slip * d / mu, law)
        u_inf = ug + a * tau[:, None]
        speed = np.maximum(np.maximum(np.linalg.norm(V, axis=1), np.linalg.norm(u_inf, axis=1)), 1e-9)
        dt = np.minimum(np.minimum(step / speed, max_dt), t_max - t[idx])
        if rw["on"]:
            dt = np.minimum(dt, eddy_left[idx])
        dt = np.maximum(dt, 1e-12)
        Xn, Vn = physics.analytic_step(P, V, ug, tau, a, dt)

        # leaving the box: the first wall crossed, and where
        out_lo, out_hi = Xn < 0.0, Xn > L
        exiting = (out_lo | out_hi).any(axis=1)
        t_hit = np.full(idx.size, np.inf)
        face = np.full(idx.size, -1)
        if exiting.any():
            with np.errstate(divide="ignore", invalid="ignore"):
                f_lo = np.where(out_lo, P / (P - Xn), np.inf)
                f_hi = np.where(out_hi, (L - P) / (Xn - P), np.inf)
            frac = np.concatenate([f_lo, f_hi], axis=1)
            face = np.argmin(frac, axis=1)
            t_hit = np.clip(frac[np.arange(idx.size), face], 0.0, 1.0)
            t_hit[~exiting] = np.inf

        # the first crossing of each plane (before any wall)
        for pc, (ax, c, _name) in zip(crossings, scn.planes):
            fresh = np.isnan(pc["t"][idx])
            p0, p1 = P[:, ax] - c, Xn[:, ax] - c
            hit = fresh & (((p0 < 0) & (p1 >= 0)) | ((p0 > 0) & (p1 <= 0)))
            if hit.any():
                with np.errstate(divide="ignore", invalid="ignore"):
                    fr = p0 / (p0 - p1)
                hit &= fr <= t_hit
                h = np.flatnonzero(hit)
                fr = fr[h][:, None]
                pc["pos"][idx[h]] = P[h] + fr * (Xn[h] - P[h])
                pc["pos"][idx[h], ax] = c
                pc["t"][idx[h]] = t[idx[h]] + fr[:, 0] * dt[h]
                pc["v"][idx[h]] = V[h] + fr * (Vn[h] - V[h])

        done = np.zeros(idx.size, bool)
        if exiting.any():
            ex = np.flatnonzero(exiting)
            th = t_hit[ex][:, None]
            hp = np.clip(P[ex] + th * (Xn[ex] - P[ex]), 0.0, L)
            labels = np.array([f"wall:{FACES[f]}" for f in face[ex]], dtype=object)
            for f_i, f_name in enumerate(FACES):
                on_face = face[ex] == f_i
                for port in outlets_on[f_name]:
                    inside = on_face & port.contains(hp)
                    labels[inside] = f"outlet:{port.name}"
            finish(idx[ex], labels, hp, t[idx[ex]] + th[:, 0] * dt[ex], V[ex] + th * (Vn[ex] - V[ex]))
            done[ex] = True
        if tbox is not None:
            inb = ~done & (Xn >= tbox[0]).all(axis=1) & (Xn <= tbox[1]).all(axis=1)
            if inb.any():
                ib = np.flatnonzero(inb)
                finish(idx[ib], "target", Xn[ib], t[idx[ib]] + dt[ib], Vn[ib])
                done[ib] = True

        stay = ~done
        s_idx = idx[stay]
        x[s_idx], v[s_idx] = Xn[stay], Vn[stay]
        t[s_idx] += dt[stay]
        if rw["on"]:
            eddy_left[s_idx] -= dt[stay]
        late = s_idx[t[s_idx] >= t_max - 1e-12]
        if late.size:
            finish(late, "airborne", x[late], t[late], v[late])

        r = rec[idx]
        if r.any():
            ids = idx[r]
            pos = np.where(alive[ids][:, None], x[ids], end[ids])
            vel = np.where(alive[ids][:, None], v[ids], v_end[ids])
            path_ids.append(ids)
            path_pts.append(np.c_[pos, np.linalg.norm(vel, axis=1)])

    left = np.flatnonzero(alive)
    if left.size:                                            # the iteration cap: counted as airborne, flagged
        finish(left, "airborne", x[left], t[left], v[left])
    ids_all = np.concatenate(path_ids) if path_ids else np.zeros(0, int)
    pts_all = np.concatenate(path_pts) if path_pts else np.zeros((0, 4))
    order = np.argsort(ids_all, kind="stable")
    ids_all, pts_all = ids_all[order], pts_all[order]
    paths = {int(i): pts_all[ids_all == i] for i in np.unique(ids_all)}
    return Track(fate=fate, end=end, t_end=t_end, v_end=v_end, crossings=crossings, paths=paths, iterations=it,
                 timed_out=int(left.size), notes={"iteration_cap": int(left.size)})
