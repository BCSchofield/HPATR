"""Phase 9 (2026-10-13): re-analyse the CCD day (2026-10-12) headless, the way the Response surface tab
does (tab_rsm.models_and_options -> rsm_publish.publish), into a NEW output folder. The first analysis
(Taguchi/CCD/CCD 4-factor 12-10-2026/) is not touched.

Same model and goals as the first analysis's rsm_model.json (atomised max x3, mean diameter min x2,
count CV min x1; all four factors as the surface; orifice restricted to the inserts), with this
session's defaults: no spray < 2 %, pressure-limited runs out of the fit, orifice on a log scale,
count band 30-50 um, liquid stage 2.3.0.

    python reanalyse_ccd.py <output folder> [--limited exclude|delivered|set] [--linear-orifice]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/Users/benschofield/Documents/GitHub/HPATR")
from src.ai.Taguchi_Analysis_UI import rsm_detect as rsm  # noqa: E402
from src.ai.Taguchi_Analysis_UI import rsm_publish as rp  # noqa: E402
from src.ai.Taguchi_Analysis_UI import run_discovery as rd  # noqa: E402
from src.ai.Taguchi_Analysis_UI import size_bins, stats  # noqa: E402
from src.ai.Taguchi_Analysis_UI.tab_rsm import goal_for_fit  # noqa: E402

DAY = Path("/Volumes/LaCie/Experiments/2026/10/12")
FIRST = Path("/Volumes/LaCie/Experiments/Taguchi/CCD/CCD 4-factor 12-10-2026")

ap = argparse.ArgumentParser()
ap.add_argument("out", type=Path)
ap.add_argument("--limited", default="exclude", choices=["exclude", "delivered", "set"])
ap.add_argument("--linear-orifice", action="store_true")
ap.add_argument("--band", type=float, nargs=2, metavar=("LO", "HI"),
                help="the droplet count size band in um (default: the app's 30-50)")
ap.add_argument("--model", type=Path, help="an rsm_model.json to use as saved (goals, roles, options) instead of "
                                           "the first analysis's with this session's defaults")
a = ap.parse_args()
if a.out.resolve() == FIRST.resolve():
    sys.exit("refusing to write into the first analysis")

if a.model:
    model = json.loads(a.model.read_text(encoding="utf-8"))
    model.setdefault("limited", "exclude")
    model.setdefault("log", ["orifice"])
else:
    model = json.loads((FIRST / "rsm_model.json").read_text(encoding="utf-8"))
    model["limited"] = a.limited
    model["log"] = [] if a.linear_orifice else ["orifice"]

scan = rd.find_runs([DAY])
runs = rd.load_runs(scan.runs, check_reuse=False)
print(len(runs), "runs found")
design = rsm.from_runs(runs)
det = design.detect()
label = {f.key: f.label.split(" (")[0] for f in det.factors}
axis = [k for k, r in model["roles"].items() if r == "surface"]
models = [rp.ModelSpec("(a) " + " × ".join(label.get(k, k) for k in axis), axis, {}, time_term=model["time"])]
discrete = {k: [float(x) for x in t.replace(";", ",").split(",") if x.strip()] for k, t in model["discrete"].items()}
goals = [goal_for_fit(g) for g in model["goals"]]

a.out.mkdir(parents=True, exist_ok=True)
(a.out / "rsm_model.json").write_text(json.dumps(model, indent=2), encoding="utf-8")
t0 = time.time()


def log(text, level="info"):
    print(f"[{time.time() - t0:6.0f}s] {level:5s} {text}", flush=True)


res = rp.publish(design, a.out, models, thr=0.30, goals=goals, discrete=discrete,
                 title=("Response-surface analysis" if a.model else
                        "Response-surface analysis (re-analysis, liquid stage 2.3.0)"),
                 progress=lambda i, n, name: log(f"run {i}/{n} {name}"), log=log,
                 analysis_opts=(stats.AnalysisOptions(band_um=tuple(a.band)) if a.band else stats.AnalysisOptions()), limited=model["limited"], log_scale=model["log"],
                 bin_width=size_bins.DEFAULT_WIDTH_UM, bin_max=size_bins.DEFAULT_MAX_UM)
print("refused:", res.refused)
print("problems:", res.problems)
for name in ("report", "workbook", "csv", "deck"):
    print(f"  {name:9s} {getattr(res, name)}")
print("next runs:", res.next_runs[:1] if res.next_runs else None)
print(f"done in {res.seconds:.0f}s")
