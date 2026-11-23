#!/bin/bash
# Overnight, 2026-11-14 (CFDOF_GUIDE.md 8.11): solve Chamber_v3 and its two designs (the CAD's step closed, layers
# on every atomiser face), one after another (each uses 10 cores), then the droplets through all three
# (settings/droplets_chamber_v3.yaml).
# ~10.5 h: Chamber_v3 ~40 min, Stream and Gentle ~1.5 h each, the droplets ~6.5 h (estimates from the first solves and
# the 2026-11-14 sweep). A solve that fails only loses its own droplet runs; the sweep carries on with the rest.
# Each solve's output: <case>/case/allrun.out and log.simpleFoam. The droplets: the terminal, then comparison.md.

C=/Users/benschofield/OpenFOAM/cfdof_cases
FV="/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation"

for n in Chamber_v3 Chamber_v3_stream_30 Chamber_v3_gentle_30; do
    echo "$(date +%H:%M) solving $n ..."
    ( cd "$C/$n/case" && ./Allrun > allrun.out 2>&1 )
    echo "$(date +%H:%M) $n: finished (exit $?; saved: $(ls "$C/$n/case/processor0" | grep -E '^[0-9]+$' | sort -n | tr '\n' ' '))"
done

echo "$(date +%H:%M) the droplets ..."
cd "$FV" && /Users/benschofield/anaconda3/envs/phantom/bin/python3 run_droplets.py settings/droplets_chamber_v3.yaml
echo "$(date +%H:%M) all done"
