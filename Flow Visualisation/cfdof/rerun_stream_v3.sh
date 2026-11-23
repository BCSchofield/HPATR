#!/bin/bash
# 2026-11-15 (CFDOF_GUIDE.md 8.11): Stream's three flows through the droplets again
# (settings/droplets_chamber_v3_stream.yaml), now that the runner restarts a stage a stuck droplet stalls. Then
# compares them with the 2026-11-15_0145 sweep's Chamber_v3 and Gentle runs (unchanged, only read).
# ~2.5 h (each flow ~50 min, one after another; a stuck droplet costs ~6 min).
# Output: droplet_runs/<date>_<time>_chamber_v3_stream/ (Stream's runs), then
# droplet_runs/<date>_<time>_chamber_v3_all/comparison.md (all seven flows: the one to read).

PY=/Users/benschofield/anaconda3/envs/phantom/bin/python3
FV="/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation"
R=/Users/benschofield/OpenFOAM/droplet_runs
V3=$R/2026-11-15_0145_chamber_v3/data
NEW=$R/$(date +%Y-%m-%d_%H%M)_chamber_v3_stream

cd "$FV" || exit 1
echo "$(date +%H:%M) Stream's droplets -> $NEW ..."
$PY run_droplets.py settings/droplets_chamber_v3_stream.yaml --out "$NEW"

folders=("$V3/Chamber_v3")
labels="Chamber_v3"
for n in 2000 3000 4000; do
    if [ -f "$NEW/data/Stream_$n/droplets.csv" ]; then
        folders+=("$NEW/data/Stream_$n")
        labels="$labels,Stream $n"
    fi
done
for n in 2000 3000 4000; do
    folders+=("$V3/Gentle_$n")
    labels="$labels,Gentle $n"
done
ALL=$R/$(date +%Y-%m-%d_%H%M)_chamber_v3_all
echo "$(date +%H:%M) comparing all seven -> $ALL ..."
$PY run_droplets.py --compare "${folders[@]}" --labels "$labels" --show gusts_on_after_290s --out "$ALL"
echo "$(date +%H:%M) all done: $ALL/comparison.md"
