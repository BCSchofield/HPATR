"""Put cfMesh's allowDiscontinuity back on the atomiser's layers after CfdOF's Write mesh, which drops it
(CFDOF_GUIDE.md 8.11). Without it cfMesh spreads the atomiser's layer count to the faces round it, and the mesh at the
nozzle tip skews (85-90 faces). Run it after every Write mesh of a Chamber_v3 case, before Run mesher:

    /Users/benschofield/anaconda3/envs/phantom/bin/python3 add_layer_discontinuity.py ~/OpenFOAM/cfdof_cases/<case>/meshCase

It finds the atomiser's layer patches by matching each layered patch's surface (constant/triSurface/patch_0_N.stl)
to the AtomiserLayers and NozzleBlockLayers refinement surfaces (same faces, same bounding box).
"""
import re
import sys
from pathlib import Path

NAMES = ("AtomiserLayers", "NozzleBlockLayers")


def bbox(stl: Path) -> tuple:
    v = [tuple(float(x) for x in line.split()[1:4]) for line in open(stl) if line.lstrip().startswith("vertex")]
    return tuple(round(min(p[i] for p in v), 6) for i in range(3)) + tuple(round(max(p[i] for p in v), 6) for i in range(3))


def main(mesh_case: Path) -> int:
    tri, md = mesh_case / "constant" / "triSurface", mesh_case / "system" / "meshDict"
    want = {bbox(tri / f"{n}.stl"): n for n in NAMES if (tri / f"{n}.stl").exists()}
    if len(want) != len(NAMES):
        print(f"{mesh_case}: no {' / '.join(NAMES)} surfaces in constant/triSurface (is it a Chamber_v3 case?)")
        return 1
    txt = md.read_text()
    layers = txt[txt.index("patchBoundaryLayers"):]
    found = {}
    for n in re.findall(r'"(patch_0_\d+)"', layers):
        if (tri / f"{n}.stl").exists() and bbox(tri / f"{n}.stl") in want:
            found[want[bbox(tri / f"{n}.stl")]] = n
    if len(found) != len(NAMES):
        print(f"{md}: found {found}, expected a layered patch for each of {NAMES}; nothing changed")
        return 1
    for name, patch in found.items():
        block = re.search(r'"%s"\s*\{[^}]*\}' % patch, txt).group(0)
        if "allowDiscontinuity" in block:
            print(f"{name} ({patch}): already has allowDiscontinuity")
            continue
        txt = txt.replace(block, block[:-1].rstrip() + "\n            allowDiscontinuity 1;\n        }", 1)
        print(f"{name} ({patch}): allowDiscontinuity added")
    md.write_text(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).expanduser()))
