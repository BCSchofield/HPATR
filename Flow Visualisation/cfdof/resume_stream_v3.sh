#!/bin/bash
# 2026-11-15 (CFDOF_GUIDE.md 8.11): Stream's four runs of 290 s that stuck in the rerun (2000 gusts off, 3000 both,
# 4000 gusts on), carried on from their newest frames with the runner's guard: droplets are kept out of the cells
# OpenFOAM can't split into valid tets, each one removed counted as a hit on the wall its cell is on (the port's, at
# the capture's cone). Then all seven flows compared again (Chamber_v3 and Gentle from the 2026-11-15_0145 sweep,
# unchanged, only read). ~1 h (the four at once).
# Output: the rerun's flow folders updated in place, then droplet_runs/<date>_<time>_chamber_v3_all/comparison.md.

PY=/Users/benschofield/anaconda3/envs/phantom/bin/python3
FV="/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation"
R=/Users/benschofield/OpenFOAM/droplet_runs
S=$R/2026-11-15_1218_chamber_v3_stream/data
V3=$R/2026-11-15_0145_chamber_v3/data

cd "$FV" || exit 1
echo "$(date +%H:%M) carrying on Stream's stuck runs ..."
$PY run_droplets.py --resume "$S/Stream_2000" "$S/Stream_3000" "$S/Stream_4000"

ALL=$R/$(date +%Y-%m-%d_%H%M)_chamber_v3_all
echo "$(date +%H:%M) comparing all seven -> $ALL ..."
$PY run_droplets.py --compare "$V3/Chamber_v3" "$S/Stream_2000" "$S/Stream_3000" "$S/Stream_4000" \
    "$V3/Gentle_2000" "$V3/Gentle_3000" "$V3/Gentle_4000" \
    --labels "Chamber_v3,Stream 2000,Stream 3000,Stream 4000,Gentle 2000,Gentle 3000,Gentle 4000" \
    --show gusts_on_after_290s --out "$ALL"
echo "$(date +%H:%M) all done: $ALL/comparison.md"
