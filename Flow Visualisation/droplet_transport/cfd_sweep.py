"""Phase 3a Part D: one droplets settings file run through several flows (or any other changes), then compared.
See PLAN.md, Phase 3a, Part D, and README.md, "Droplets through the CFD flow".

A settings file with a `sweep:` block runs once per entry; each entry changes only what it names (mappings merge, as
with `base:`):

    sweep:
      show: gusts_on_after_2s              # the run the comparison's maps and size curves show (default: gusts on,
                                           #   the middle flow-kept time)
      against: iteration 2000              # the entry the others are measured against (default: the first)
      runs:
        - {label: iteration 1000, flow: {iteration: 1000}}
        - {label: Part 5 case, flow: {case: ~/OpenFOAM/cfdof_cases/Chamber_v1/case}}

    <runs_folder>/<name>/<date_time>/          comparison.md, comparison.csv, figures/, sweep.json, the settings
    <runs_folder>/<name>/<date_time>/<label>/  each entry's full run folder (report.md, paraview/, openfoam/, ...),
                                               its settings written out
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from . import cfd_compare, cfd_runner
from .runner import _slug
from .settings import BASES, SettingsError, _merge, _replaced, base_files

SECTIONS = ("flow", "chamber", "liquid", "spray", "slide_test", "physics", "checks", "run", "paraview")


# ---- the entries ---------------------------------------------------------------------------------------------------

def expand(plain: dict, basis: dict) -> tuple[dict, list[tuple[str, dict, dict]]]:
    """(the sweep block, [(label, plain, basis), ...]): the settings each entry runs with."""
    sw = plain.get("sweep")
    if not isinstance(sw, dict) or not isinstance(sw.get("runs"), list) or len(sw["runs"]) < 2:
        raise SettingsError("sweep: {runs: [{label: ..., <what it changes>}, ...]} with at least two runs")
    base = {k: v for k, v in plain.items() if k != "sweep"}
    base_basis = {k: v for k, v in basis.items() if not (k == "sweep" or k.startswith("sweep."))}
    out, seen = [], set()
    for i, e in enumerate(sw["runs"]):
        if not isinstance(e, dict) or not str(e.get("label") or "").strip():
            raise SettingsError(f"sweep.runs.{i}: a mapping with a label")
        label = str(e["label"]).strip()
        if _slug(label) in seen:
            raise SettingsError(f"sweep.runs.{i}: label {label!r} is used twice (folders are named after it)")
        seen.add(_slug(label))
        change = {k: v for k, v in e.items() if k != "label"}
        bad = [k for k in change if k not in SECTIONS]
        if bad:
            raise SettingsError(f"sweep.runs.{i} ({label}): {bad} is not a settings section; it may change "
                                f"{', '.join(SECTIONS)}")
        pre = f"sweep.runs.{i}."
        gone = list(_replaced(change))
        b = {k: v for k, v in base_basis.items() if not any(k == g or k.startswith(g + ".") for g in gone)}
        b.update({k[len(pre):]: v for k, v in basis.items() if k.startswith(pre)})
        out.append((label, _merge(base, change), b))
    labels = [o[0] for o in out]
    if sw.get("against") is not None and str(sw["against"]) not in labels:
        raise SettingsError(f"sweep.against {sw['against']!r}: not one of the labels {labels}")
    return sw, out


class _Tag:
    """A value written back out with its tag (!measured, ...)."""

    def __init__(self, tag, value):
        self.tag, self.value = tag, value


class _Dumper(yaml.SafeDumper):
    pass


def _represent_tag(dumper, t):
    node = dumper.represent_data(t.value)
    node.tag = t.tag
    return node


_Dumper.add_representer(_Tag, _represent_tag)
_TAGS = {b: t for t, b in BASES.items()}


def _retag(obj, path, basis):
    if path in basis:
        tag = next((t for b, t in _TAGS.items() if str(basis[path][0]).startswith(b)), None)
        if tag:
            return _Tag(tag, obj)
    if isinstance(obj, dict):
        return {k: _retag(v, f"{path}.{k}" if path else str(k), basis) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_retag(v, f"{path}.{i}", basis) for i, v in enumerate(obj)]
    return obj


def dump_settings(plain: dict, basis: dict, header: str = "") -> str:
    """Settings as a file read_yaml reads back to the same values and the same tags."""
    text = yaml.dump(_retag(plain, "", basis), Dumper=_Dumper, sort_keys=False, default_flow_style=None,
                     allow_unicode=True, width=120)
    return "".join(f"# {line}\n" for line in header.splitlines()) + text


# ---- running one -----------------------------------------------------------------------------------------------------

def run_sweep(settings_path: Path, plain: dict, basis: dict, out: Path | None = None, per_size: int | None = None,
              only=None, write_only: bool = False, paraview: bool = True, checks: bool = True, log=print) -> Path:
    sw, entries = expand(plain, basis)
    name = str(plain.get("name") or settings_path.stem)
    scns = [(label, cfd_runner.scenario(p, b, settings_path, per_size), p, b) for label, p, b in entries]
    runs = scns[0][1].runs_folder / _slug(name)                     # every entry's settings checked: now run
    root = Path(out) if out else runs / cfd_runner.fresh_stamp(runs)
    if " " in str(root):
        raise SettingsError(f"--out {root}: OpenFOAM cannot work in a path with spaces")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings_path, root / "settings.yaml")
    for f in base_files(settings_path):
        shutil.copy2(f, root / f.name)
    log(f"{settings_path.name}: a sweep of {len(scns)} -> {root}")
    done, errors = [], []
    for i, (label, scn, p, b) in enumerate(scns):
        folder = root / _slug(label)
        folder.mkdir(exist_ok=True)
        (folder / "settings.yaml").write_text(dump_settings(p, b, f"{label}: run {i + 1} of the sweep in "
                                                                  f"{settings_path.name} (written out in full)"),
                                              encoding="utf-8")
        log(f"\n[{i + 1}/{len(scns)}] {label}")
        try:
            cfd_runner.run_scenario(scn, folder, only, write_only, paraview, checks, log,
                                    extra_meta={"label": label, "sweep": str(settings_path)})
            done.append((label, folder))
        except cfd_runner.RunError as e:                 # one failed entry does not stop the others
            errors.append(f"{label}: {e}")
            log(f"  {label}: FAILED: {e}")
            if (folder / "droplets.csv").exists():
                done.append((label, folder))
    info = {"name": name, "settings": str(settings_path), "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "show": sw.get("show"), "against": sw.get("against"), "tolerance": sw.get("tolerance"),
            "runs": [{"label": la, "folder": f.name} for la, f in done], "errors": errors}
    (root / "sweep.json").write_text(json.dumps(info, indent=1))
    if not write_only and len(done) >= 2:
        compare_sweep(root, log)
    if errors:
        raise cfd_runner.RunError("some of the sweep failed:\n" + "\n".join(errors))
    return root


def compare_sweep(root: Path, log=print) -> Path:
    """The comparison of a finished sweep's entries (again, after a change to the comparison)."""
    root = Path(root)
    info = json.loads((root / "sweep.json").read_text())
    return cfd_compare.compare([root / r["folder"] for r in info["runs"]], root,
                               labels=[r["label"] for r in info["runs"]], show=info.get("show"),
                               against=info.get("against"), tolerance=info.get("tolerance"),
                               title=f"{info['name']}: the same droplets through each flow", log=log)


def rebuild(root: Path, log=print) -> Path:
    """Every entry's figures and report.md, then the comparison."""
    root = Path(root)
    info = json.loads((root / "sweep.json").read_text())
    for r in info["runs"]:
        cfd_runner.rebuild_report(root / r["folder"], log)
    return compare_sweep(root, log)
