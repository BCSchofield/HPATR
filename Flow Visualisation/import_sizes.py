"""Import a run's measured droplet size distribution for Flow Visualisation (read only: nothing is written in the run).

    python3 import_sizes.py "/Volumes/LaCie/Experiments/.../<run>/shadowgraph/analysis/droplets_0.30" --name ccd_131450

writes data/<name>_sizes.csv, which a settings file names in spray.droplets.distribution. Needs a run measured with
sizer 3.x (the in-volume counts). See droplet_transport/sizes.py for exactly what is imported.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from droplet_transport import sizes  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("droplets_dir", type=Path, help="the run's shadowgraph/analysis/droplets_<thr> folder")
    ap.add_argument("--name", required=True, help="short name, e.g. ccd_131450 -> data/ccd_131450_sizes.csv")
    ap.add_argument("--bin-um", type=float, default=2.0, help="bin width (um), default 2")
    a = ap.parse_args(argv)
    out = ROOT / "data" / f"{a.name}_sizes.csv"
    try:
        d = sizes.import_run(a.droplets_dir, out, a.bin_um)
    except (OSError, ValueError, KeyError) as e:
        print(f"could not import: {e}", file=sys.stderr)
        return 2
    print(f"{out}: {d.count.sum():.0f} sized (weighted), {d.below_dmin:.0f} below d_min {d.d_min_um:g} um")
    for line in d.header:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
