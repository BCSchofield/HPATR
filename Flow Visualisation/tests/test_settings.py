"""The settings file: tags, units, validation, sweeps."""
import textwrap

import numpy as np
import pytest

from droplet_transport import settings

YAML = textwrap.dedent("""
    name: tagged
    chamber:
      size_mm: !design [300, 200, 350]
    gas:
      temperature_C: !estimated 20
    liquid:
      density_kg_m3: !estimated 1070
    inlets:
      - name: right inlet
        wall: right
        centre_mm: !design {y: 100, z: 175}
        diameter_mm: !design 6
        flow_sccm: !estimated 8000
    outlets:
      - name: left outlet
        wall: left
        centre_mm: {y: 100, z: 175}
        diameter_mm: 25
    spray:
      nozzle_mm: !design [150, 100, 350]
      gas_flow_sccm: !measured 8995
      orifice_mm: !measured 1.2
      orifice_cd: !measured 0.527
      droplets:
        standoff_mm: !estimated 25
        speed_m_s: !estimated 6
        sizes_um: {from: 10, to: 200, step: 2}
        per_size: 5
    target:
      outlet: left outlet
      band_um: !design [30, 60]
    """)


def write(tmp_path, text, name="s.yaml"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_tags_units_and_defaults(tmp_path):
    [scn] = settings.load(write(tmp_path, YAML))
    assert scn.basis["inlets.0.flow_sccm"] == ("estimated", 8000)
    assert scn.basis["spray.gas_flow_sccm"] == ("measured", 8995)
    assert scn.basis["inlets.0.centre_mm"] == ("design choice", {"y": 100, "z": 175})
    assert scn.basis["chamber.size_mm"] == ("design choice", [300, 200, 350])
    assert "outlets.0.diameter_mm" not in scn.basis                     # untagged
    assert scn.box == pytest.approx([0.3, 0.2, 0.35])
    assert scn.inlets[0].centre == pytest.approx([0.3, 0.1, 0.175])
    assert scn.inlets[0].direction == pytest.approx([-1, 0, 0])         # square to the wall, inwards
    assert scn.outlets[0].normal == pytest.approx([1, 0, 0])
    assert scn.spray.axis == pytest.approx([0, 0, -1])
    assert scn.spray.start_centre == pytest.approx([0.15, 0.1, 0.325])
    assert scn.spray.sizes_um[0] == 10 and scn.spray.sizes_um[-1] == 200 and scn.spray.sizes_um.size == 96
    assert scn.target_outlet == "left outlet" and scn.band_um == (30.0, 60.0)


def test_tilt_and_lean():
    import math
    scn = settings.build({**_plain(), "spray": {**_plain()["spray"], "tilt_deg": 30, "lean_toward_deg": 180}}, {})
    assert scn.spray.axis == pytest.approx([-math.sin(math.radians(30)), 0, -math.cos(math.radians(30))], abs=1e-12)


def _plain():
    import yaml
    return settings._strip(yaml.load(YAML, Loader=settings._Loader), "", {})


@pytest.mark.parametrize("change, message", [
    (lambda p: p["inlets"][0].update(centre_mm={"y": 100, "z": 348}), "does not fit"),
    (lambda p: p["inlets"][0].update(centre_mm={"x": 100, "z": 175}), "needs exactly"),
    (lambda p: p["inlets"][0].update(wall="ceiling"), "wall"),
    (lambda p: p["target"].update(outlet="nowhere"), "not one of the outlets"),
    (lambda p: p["spray"]["droplets"].update(standoff_mm=400), "not inside the chamber"),
    (lambda p: p["inlets"][0].update(direction=[1, 0, 0]), "into the chamber"),
    (lambda p: p.update(outlets=[]), "at least one"),
    (lambda p: p["target"].update(band_um=[60, 30]), "low < high"),
])
def test_validation(change, message):
    p = _plain()
    change(p)
    with pytest.raises(settings.SettingsError, match=message):
        settings.build(p, {})


def test_slot_port_contains():
    p = _plain()
    p["outlets"] = [{"name": "slot", "wall": "left", "centre_mm": {"y": 100, "z": 175}, "shape": "slot",
                     "width_mm": 4, "length_mm": 100, "long_side_along": "y"}]
    p["target"]["outlet"] = "slot"
    scn = settings.build(p, {})
    s = scn.outlets[0]
    pts = np.array([[0, 0.149, 0.175], [0, 0.151, 0.175], [0, 0.1, 0.1769], [0, 0.1, 0.1771]])
    assert s.contains(pts).tolist() == [True, False, True, False]
    assert s.area == pytest.approx(0.004 * 0.1)


def test_sweep_expands_every_combination(tmp_path):
    text = YAML + textwrap.dedent("""
        sweep:
          - path: inlets.0.diameter_mm
            values: [4, 6, 10]
          - path: inlets.0.flow_sccm
            values: [8000, 16000]
        """)
    scns = settings.load(write(tmp_path, text))
    assert len(scns) == 6
    assert scns[0].label == "inlets.0.diameter_mm=4, inlets.0.flow_sccm=8000"
    assert [round(s.inlets[0].diameter * 1000) for s in scns] == [4, 4, 6, 6, 10, 10]
    assert scns[1].basis["inlets.0.flow_sccm"] == ("estimated (swept)", 16000)
    assert scns[0].basis["inlets.0.diameter_mm"] == ("design choice (swept)", 4)


def test_sweep_of_a_missing_setting_says_so(tmp_path):
    text = YAML + "sweep:\n  - path: inlets.0.diameter\n    values: [4]\n"
    with pytest.raises(settings.SettingsError, match="no setting"):
        settings.load(write(tmp_path, text))


def test_the_shipped_settings_files_load():
    from droplet_transport import cfd_droplets
    for f in sorted((settings.ROOT / "settings").glob("*.yaml")):
        if "slide_test" in settings.read_yaml(f)[0]:            # a Phase 3a droplets file (run_droplets.py)
            assert cfd_droplets.load(f), f
        else:
            assert settings.load(f), f


def test_a_file_can_start_from_a_base(tmp_path):
    write(tmp_path, YAML, "first.yaml")
    child = write(tmp_path, textwrap.dedent("""
        base: first.yaml
        name: child
        spray:
          tilt_deg: !design 30
        inlets:
          - name: low inlet
            wall: right
            centre_mm: {y: 100, z: 60}
            diameter_mm: 4
            flow_sccm: 9000
        """), "child.yaml")
    [scn] = settings.load(child)
    assert scn.name == "child"
    assert scn.basis["spray.tilt_deg"] == ("design choice", 30)
    assert scn.basis["spray.gas_flow_sccm"] == ("measured", 8995)          # kept from the base
    assert "inlets.0.flow_sccm" not in scn.basis                            # the base's inlets were replaced
    assert [p.name for p in scn.inlets] == ["low inlet"] and scn.inlets[0].centre[2] == pytest.approx(0.06)
    assert scn.spray.orifice_cd == pytest.approx(0.527)
    assert settings.base_files(child) == [(tmp_path / "first.yaml").resolve()]


def test_base_loops_are_refused(tmp_path):
    write(tmp_path, "base: b.yaml\n", "a.yaml")
    write(tmp_path, "base: a.yaml\n", "b.yaml")
    with pytest.raises(settings.SettingsError, match="loop"):
        settings.load(tmp_path / "a.yaml")


def test_sweep_labels(tmp_path):
    text = YAML + textwrap.dedent("""
        sweep:
          - path: target.band_um
            values: [[30, 60], [10, 30]]
          - path: inlets.0.diameter_mm
            values: [4, 6]
          - path: spray.nozzle_mm
            values: [[150, 100, 350], [120, 100, 350]]
            labels: [centre, left of centre]
        """)
    shown = settings.sweep_shown(write(tmp_path, text))
    assert shown == [("target.band_um", ["30/60", "10/30"]), ("inlets.0.diameter_mm", [4, 6]),
                     ("spray.nozzle_mm", ["centre", "left of centre"])]
    assert settings.compact({"from": [90, 80, 0], "to": [130, 120, 2]}) == "90/80/0 to 130/120/2"
