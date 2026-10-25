"""Delivery and purity of a different size band, from a saved run: no re-run (the fates of every size are saved).

    python3 band.py "output/first_scenario/<date_time>" 20 50

Reads the run's per_size.csv (and deflection.csv for the inlets-off shares) and the settings copied into the output
folder (for the measured size distribution).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from droplet_transport import analysis, settings, sizes  # noqa: E402


def settings_copy(run_dir: Path) -> Path | None:
    for d in (run_dir, *run_dir.parents):
        if (d / "settings.yaml").exists():
            return d / "settings.yaml"
    return None


def rebands(run_dir: Path, band) -> dict:
    run_dir = Path(run_dir)
    ps = pd.read_csv(run_dir / "per_size.csv")
    n_w = None
    sfile = settings_copy(run_dir)
    if sfile is not None:
        scn = settings.load(sfile)[0]
        if scn.spray.distribution is not None and Path(scn.spray.distribution).exists():
            n_w, _info = sizes.weights(ps["size_um"].to_numpy(), sizes.load(scn.spray.distribution),
                                       scn.spray.below_dmin_from_um)
    out = {"inlets on": analysis.band_metrics(ps, band, n_w)}
    if (run_dir / "deflection.csv").exists():
        off = pd.read_csv(run_dir / "deflection.csv")[["size_um", "target off"]].rename(columns={"target off": "target"})
        out["inlets off"] = analysis.band_metrics(off, band, n_w)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path, help="a run's output folder (with per_size.csv)")
    ap.add_argument("low_um", type=float)
    ap.add_argument("high_um", type=float)
    a = ap.parse_args(argv)
    if not a.low_um < a.high_um:
        print("the band needs low < high", file=sys.stderr)
        return 2
    for case, m in rebands(a.run_dir, (a.low_um, a.high_um)).items():
        pct = {k: ("–" if m.get(k) is None else f"{100 * m[k]:.1f} %")
               for k in ("delivery_number", "delivery_volume", "purity_number", "purity_volume")}
        print(f"{case}: band {a.low_um:g}-{a.high_um:g} um: delivery {pct['delivery_number']} by number, "
              f"{pct['delivery_volume']} by volume; purity {pct['purity_number']} by number, "
              f"{pct['purity_volume']} by volume ({m.get('weighting')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
