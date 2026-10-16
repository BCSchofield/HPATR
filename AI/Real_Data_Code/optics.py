#!/usr/bin/env python3
"""
optics.py -- the optical set-up each capture was taken with, read from one profile file per set-up
(sizer 3.0.0 plan, Phase 0, 2026-10-15).

Every number that depends on the optics (the scale in um/px now; the edge level, the blur-width focus rule, the
smallest size measured and the measurement depth once calibrated) lives in config/optics/<name>.json, never in
the code. A new lens, aperture, working distance or camera position is a new profile file.

Which profile a capture used, in this order:
  1. HPATR_OPTICS_PROFILE in the environment (a profile name): forces one, e.g. for a tool run on old data;
  2. the run's own run_summary.xlsx, field "Optics profile" (GUI_Clean writes it from 2026-10-15), found in the
     given folder or any folder above it (so a path inside a run's analysis folder works too);
  3. the capture date in the path (.../YYYY/MM/DD/...): the latest profile whose valid_from is on or before it;
  4. the only profile, if there is just one.
Otherwise it is ambiguous and an OpticsProfileError says so: with two set-ups on disk, a wrong scale must never be
picked silently.

    import optics
    optics.um_per_px(run_dir)        # 10.0
    optics.profile_for(run_dir)      # the whole profile (dict)
    optics.current()                 # the newest profile: what GUI_Clean stamps on new runs
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parents[2] / "config" / "optics"
ENV_PROFILE = "HPATR_OPTICS_PROFILE"
ENV_DIR = "HPATR_OPTICS_DIR"            # tests: profiles from another folder
REQUIRED = ("name", "valid_from", "um_per_px")
DATE_RE = re.compile(r"(?:^|[\\/])(20\d\d)[\\/](\d\d)[\\/](\d\d)(?:[\\/]|$)")


class OpticsProfileError(ValueError):
    pass


def _dir() -> Path:
    return Path(os.environ.get(ENV_DIR) or PROFILE_DIR)


def _signature(folder: Path) -> tuple:
    """The profile files and their modification times: a profile added or edited while a program runs (the GUI
    runs for days) is picked up at the next call, without a restart."""
    return tuple(sorted((f.name, f.stat().st_mtime_ns) for f in folder.glob("*.json")))


@lru_cache(maxsize=None)
def _load_all(folder: str, signature: tuple) -> tuple:
    out = []
    for f in sorted(Path(folder).glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        missing = [k for k in REQUIRED if k not in p]
        if missing:
            raise OpticsProfileError(f"{f.name}: missing {', '.join(missing)}")
        if p["name"] != f.stem:
            raise OpticsProfileError(f"{f.name}: its name is {p['name']!r}; the file must be named after it")
        p["_valid_from"] = date.fromisoformat(str(p["valid_from"]))
        out.append(p)
    if not out:
        raise OpticsProfileError(f"no optics profiles in {folder}")
    return tuple(sorted(out, key=lambda p: p["_valid_from"]))


def profiles() -> list[dict]:
    """Every profile, oldest first."""
    d = _dir()
    return list(_load_all(str(d), _signature(d)))


def load(name: str) -> dict:
    for p in profiles():
        if p["name"] == name:
            return p
    raise OpticsProfileError(f"no optics profile {name!r} in {_dir()} "
                             f"(have: {', '.join(p['name'] for p in profiles())})")


def current() -> dict:
    """The newest profile: the set-up on the rig now, which GUI_Clean records on every new run."""
    return profiles()[-1]


def _named_in_run(path: Path) -> str | None:
    for folder in [path] + list(path.parents)[:6]:
        x = folder / "run_summary.xlsx"
        if x.is_file():
            try:
                import openpyxl
                wb = openpyxl.load_workbook(x, read_only=True, data_only=True)
                try:
                    if "Metadata" in wb.sheetnames:
                        for r in wb["Metadata"].iter_rows(min_row=2, values_only=True):
                            if r and r[0] is not None and str(r[0]).strip() == "Optics profile":
                                v = str(r[1] or "").strip()
                                return v if v and v.upper() != "NOT RECORDED" else None
                finally:
                    wb.close()
            except Exception:                                  # noqa: BLE001 -- unreadable: fall through to the date
                return None
            return None
    return None


def _date_in(path: Path) -> date | None:
    m = None
    for m in DATE_RE.finditer(str(path)):
        pass
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def profile_for(path=None) -> dict:
    """The profile a capture (a run folder, or any path inside one) was taken with. See the module docstring."""
    forced = os.environ.get(ENV_PROFILE)
    if forced:
        return load(forced)
    if path is not None:
        path = Path(path)
        named = _named_in_run(path)
        if named:
            return load(named)
        d = _date_in(path.resolve() if path.exists() else path)
        if d is not None:
            valid = [p for p in profiles() if p["_valid_from"] <= d]
            if valid:
                return valid[-1]
            raise OpticsProfileError(f"no optics profile valid on {d} (the earliest starts "
                                     f"{profiles()[0]['_valid_from']})")
    ps = profiles()
    if len(ps) == 1:
        return ps[0]
    raise OpticsProfileError("several optics profiles exist and this path names none and has no date: set "
                             f"{ENV_PROFILE} to one of {', '.join(p['name'] for p in ps)}")


def um_per_px(path=None) -> float:
    return float(profile_for(path)["um_per_px"])


def mm2_per_px(path=None) -> float:
    return (um_per_px(path) / 1000.0) ** 2


def describe(path=None) -> str:
    p = profile_for(path)
    return f"{p['name']} ({p['um_per_px']} um/px)"
