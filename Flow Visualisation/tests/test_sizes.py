"""The measured size distribution: the importer follows master_log's rule; the weights; the band metrics."""
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from droplet_transport import analysis, sizes

REPO = Path(__file__).resolve().parents[2]


def fake_measurement(tmp_path, rng):
    """A droplets_0.30/ folder in the 3.1.0 layout: in_volume, weight, in_focus, diameter_um."""
    m = tmp_path / "droplets_0.30"
    m.mkdir()
    with open(m / "droplet_sizes.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "diameter_um", "in_focus", "in_volume", "weight"])
        for i in range(3000):
            in_vol = rng.random() < 0.7
            d = float(rng.lognormal(np.log(25), 0.6))
            sized = in_vol and d >= 30
            w.writerow([f"f{i % 40}", f"{d:.3f}", "1" if sized else "0", "1" if in_vol else "0",
                        f"{rng.uniform(0.6, 1.0):.4f}" if in_vol else "0"])
    (m / "summary.json").write_text(json.dumps({
        "provenance": {"sizer_version": "3.1.0", "sizer_d_min_um": 30.0},
        "concentration": {"frames": 40, "volume_mm3": 2.4, "crowded_factor": 1.1}}))
    return m


def test_import_matches_master_log_band_concentrations(tmp_path):
    sys.path.insert(0, str(REPO / "AI" / "Real_Data_Code"))
    try:
        import master_log
    finally:
        sys.path.pop(0)
    m = fake_measurement(tmp_path, np.random.default_rng(7))
    dist = sizes.import_run(m, tmp_path / "out.csv", bin_um=2.0)
    bands = master_log.band_concentrations(m)
    assert dist.d_min_um == 30.0
    mid = (dist.lo_um + dist.hi_um) / 2
    mine = {"<30 um (/cm3)": dist.below_dmin,
            "30-40 um (/cm3)": dist.count[(mid >= 30) & (mid < 40)].sum(),
            "40-60 um (/cm3)": dist.count[(mid >= 40) & (mid < 60)].sum(),
            "60-100 um (/cm3)": dist.count[(mid >= 60) & (mid < 100)].sum(),
            "100+ um (/cm3)": dist.count[mid >= 100].sum()}
    k = 1.1 / (40 * 2.4) * 1000.0                       # master_log's per-cm^3 scale
    for name, v in mine.items():
        assert bands[name] == pytest.approx(v * k, abs=0.002), name
    again = sizes.load(tmp_path / "out.csv")
    assert again.total == pytest.approx(dist.total) and again.header[0].startswith("Measured")


def test_import_refuses_an_old_sizer(tmp_path):
    m = fake_measurement(tmp_path, np.random.default_rng(1))
    (m / "summary.json").write_text(json.dumps({"provenance": {"sizer_version": "2.2.0"}}))
    with pytest.raises(ValueError, match="3.x"):
        sizes.import_run(m, tmp_path / "o.csv")


def test_weights_spread_bins_over_the_fired_cells():
    dist = sizes.Distribution(np.array([30.0, 40.0]), np.array([40.0, 50.0]), np.array([10.0, 20.0]),
                              below_dmin=30.0, d_min_um=30.0, source="x", header=[])
    fired = np.arange(10, 61, 10.0)                     # cells 5-15, 15-25, ..., 55-65
    n, info = sizes.weights(fired, dist, below_from_um=10.0)
    # below d_min: 30 over 10-30 um -> 15 um/um: cell 5-15 gets 5 um (7.5), 15-25 gets 15, 25-35 gets 5 (7.5)
    assert n == pytest.approx([7.5, 15.0, 7.5 + 5.0, 5.0 + 10.0, 10.0, 0.0])
    assert info["share_not_fired"] == pytest.approx(0.0)
    assert n.sum() == pytest.approx(dist.total)


def test_band_metrics_by_hand():
    ps = pd.DataFrame({"size_um": [20.0, 40.0, 80.0], "target": [1.0, 0.5, 0.0]})
    m = analysis.band_metrics(ps, (30, 60), np.array([10.0, 4.0, 1.0]))
    assert m["delivery_number"] == pytest.approx(0.5)
    assert m["purity_number"] == pytest.approx(2.0 / 12.0)
    assert m["delivery_volume"] == pytest.approx(0.5)
    assert m["purity_volume"] == pytest.approx(128000 / 208000)
    assert m["arrivals_below_band_number"] == pytest.approx(10.0 / 12.0)
    plain = analysis.band_metrics(ps, (30, 60), None)
    assert plain["delivery_number"] == pytest.approx(0.5) and plain["purity_number"] is None
