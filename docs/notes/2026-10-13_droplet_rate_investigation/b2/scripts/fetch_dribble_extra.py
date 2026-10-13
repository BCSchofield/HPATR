"""Read 30 extra consecutive frames (1630..1659) from the C3 dribble cine, the densest period of
in-focus droplets in its stride-10 per_frame.csv. Read-only on the LaCie; writes to ./cache."""
from pathlib import Path
import numpy as np
from cine_reader import Cine
HERE = Path(__file__).resolve().parent
cine_path = next(Path("/Volumes/LaCie/Experiments/2026/10/12/112022_11000sccm_100rpm_5000sps_or0.5_bh0.5/shadowgraph/raw/CINE").glob("recording_*.cine"))
out = HERE / "cache" / "dribble_C3_D.npy"
if not out.exists():
    with Cine(cine_path) as cine:
        st = []
        for n in range(1630, 1660):
            cine.load_frame(n)
            st.append(np.asarray(cine.frame).astype(np.uint16).copy())
    np.save(out, np.stack(st))
print("ok", out)
