"""Shared helpers for the Flow Visualisation tests: a plain scenario to change per test."""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = {
    "name": "test", "chamber": {"size_mm": [300, 200, 350]},
    "gas": {"temperature_C": 20, "pressure_Pa": 101325, "standard_density_kg_m3": 1.184},
    "liquid": {"density_kg_m3": 1070},
    "inlets": [{"name": "right inlet", "wall": "right", "centre_mm": {"y": 100, "z": 175}, "shape": "round",
                "diameter_mm": 6, "flow_sccm": 8000}],
    "outlets": [{"name": "left outlet", "wall": "left", "centre_mm": {"y": 100, "z": 175}, "shape": "round",
                 "diameter_mm": 25}],
    "spray": {"nozzle_mm": [150, 100, 350], "tilt_deg": 0, "lean_toward_deg": 0, "gas_flow_sccm": 8995,
              "orifice_mm": 1.2, "orifice_cd": 0.527,
              "droplets": {"standoff_mm": 25, "start_radius_mm": 5, "cone_half_angle_deg": 10, "speed_m_s": 6,
                           "sizes_um": {"from": 10, "to": 200, "step": 10}, "per_size": 20}},
    "target": {"outlet": "left outlet", "band_um": [30, 60]},
    "planes": [{"axis": "z", "at_mm": 175, "name": "inlet height"}],
    "physics": {"gravity": True, "drag": "schiller_naumann", "entrainment": True},
    "run": {"seed": 1, "step_mm": 0.5, "max_step_s": 0.01, "max_time_s": 30, "paths_per_size": 2,
            "path_sizes_um": [10, 50, 100]},
}


@pytest.fixture
def base():
    return copy.deepcopy(BASE)
