"""provenance.py -- which pipeline, model and settings produced these numbers.

Every deliverable (report, workbook, JSON) carries the same block, so a result found in six
months can be tied to the code and the settings that made it. Only what is actually known is
stated: a field with no source is reported as "not recorded", never guessed.
"""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import jobstate, paths
from . import pipeline_spec as spec

UNKNOWN = "not recorded"


@dataclass
class Provenance:
    generated: str
    revision: str                       # git short hash of the repo
    pipeline_dirty: bool                # uncommitted edits under AI/Real_Data_Code
    sizer_versions: list[str]
    score_threshold: float
    n_boot: int
    seed: int
    bin_edges: list
    ci_strides: list[int]
    model_dir: str = UNKNOWN
    device: str = UNKNOWN
    stride: str = UNKNOWN
    images_mode: str = UNKNOWN
    host: str = ""
    python: str = ""
    n_runs: int = 0
    output_dir: str = ""
    extras: dict = field(default_factory=dict)

    def rows(self) -> list[tuple[str, str]]:
        """(label, value) pairs, in display order, for the report and the workbook."""
        rev = self.revision + (" + uncommitted edits to the pipeline" if self.pipeline_dirty else "")
        edges = ", ".join("∞" if e == float("inf") else f"{e:g}" for e in self.bin_edges)
        return [
            ("Generated", self.generated),
            ("Repository revision", rev),
            ("Sizer version(s)", ", ".join(self.sizer_versions) or UNKNOWN),
            ("Score threshold", f"{self.score_threshold:g}"),
            ("Frame stride (batch)", self.stride),
            ("CI stride (decorrelation)", ", ".join(str(s) for s in self.ci_strides) or UNKNOWN),
            ("Bootstrap", f"{self.n_boot} replicates, seed {self.seed}" if self.n_boot
             else "not run"),
            ("Model directory", self.model_dir),
            ("Inference device", self.device),
            ("Per-frame images", self.images_mode),
            ("Size bin edges (µm)", edges),
            ("Runs analysed", str(self.n_runs)),
            ("Host", f"{self.host}; Python {self.python}"),
        ]


def _job_settings(output_dir: Path) -> dict:
    job = jobstate.load_job(Path(output_dir) / jobstate.JOB_DIRNAME) or {}
    return {"settings": job.get("settings") or {}, "options": job.get("options") or {}}


def collect(results, bins, output_dir: Path) -> Provenance:
    sha, dirty = paths.repo_commit("AI/Real_Data_Code")
    versions = sorted({r.sizer_version or "pre-2.0.0" for r in results.runs})
    j = _job_settings(output_dir)
    st, op = j["settings"], j["options"]
    p = Provenance(
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        revision=sha, pipeline_dirty=dirty, sizer_versions=versions,
        score_threshold=results.thr, n_boot=results.n_boot, seed=results.seed,
        bin_edges=list(bins.edges) if bins is not None else [],
        ci_strides=sorted({int(r.rec.get("ci_stride") or 1) for r in results.runs}),
        host=f"{platform.system()} {platform.release()}", python=sys.version.split()[0],
        n_runs=len(results.runs), output_dir=str(output_dir))
    if st:                                     # a batch ran from this folder: None means "pipeline default"
        p.model_dir = str(st["model_dir"]) if st.get("model_dir") else "pipeline default"
        p.device = str(st["device"]) if st.get("device") else "pipeline default (auto)"
        p.stride = str(st["stride"]) if st.get("stride") is not None else "pipeline default"
    if op.get("images"):
        p.images_mode = "every frame" if op["images"] == "all" else "extreme frames only"
    return p
