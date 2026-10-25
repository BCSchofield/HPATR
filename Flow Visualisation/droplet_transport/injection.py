"""The droplets fired: every size on the grid, the same start states for every size.

They start where they are measured (Ben, 2026-10-23): on a disc across the nozzle's axis at the stand-off (the
orifice exit to the shadowgraph image centre), moving away from the axis at an angle that grows with the distance
from it (cone_half_angle at the disc's edge), at the given speed. Moving or tilting the nozzle moves the start with
it. Every size gets the SAME start states (common random numbers), so a difference between sizes is the size's.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Droplets:
    d: np.ndarray           # (N,) m
    x0: np.ndarray          # (N, 3) m
    v0: np.ndarray          # (N, 3) m/s
    size_index: np.ndarray  # (N,) index into sizes_um
    sizes_um: np.ndarray    # the grid fired


def _perpendiculars(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(axis, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(axis, e1)


def speed_for(spray, sizes_um) -> np.ndarray:
    """The starting speed of each size: one number for every size, or interpolated in a [[size_um, m/s]] table."""
    sizes_um = np.asarray(sizes_um, float)
    if np.ndim(spray.speed) == 0:
        return np.full(sizes_um.shape, float(spray.speed))
    t = np.asarray(spray.speed, float)
    return np.interp(sizes_um, t[:, 0], t[:, 1])


def fire(scn, rng: np.random.Generator) -> Droplets:
    sp = scn.spray
    n = sp.per_size
    e1, e2 = _perpendiculars(sp.axis)
    rho = sp.start_radius * np.sqrt(rng.random(n))           # uniform over the disc
    phi = 2.0 * np.pi * rng.random(n)
    radial = np.cos(phi)[:, None] * e1 + np.sin(phi)[:, None] * e2
    start = sp.start_centre + rho[:, None] * radial
    frac = rho / sp.start_radius if sp.start_radius > 0 else np.zeros(n)
    theta = sp.cone_half_angle * frac
    direction = np.cos(theta)[:, None] * sp.axis + np.sin(theta)[:, None] * radial
    k = sp.sizes_um.size
    speeds = speed_for(sp, sp.sizes_um)
    return Droplets(d=np.repeat(sp.sizes_um * 1e-6, n), x0=np.tile(start, (k, 1)),
                    v0=np.tile(direction, (k, 1)) * np.repeat(speeds, n)[:, None],
                    size_index=np.repeat(np.arange(k), n), sizes_um=sp.sizes_um.copy())
