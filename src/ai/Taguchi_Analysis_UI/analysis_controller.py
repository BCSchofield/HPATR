"""analysis_controller.py -- runs publish.publish() off the UI thread for the Analyse button.

The analysis reads ~1 s of bootstrap per run, so 27 runs is tens of seconds: far too long to
freeze the window. It runs on a plain daemon thread (like the preflight), logs through the
console's thread-safe queue (one line per run, so a stall is visible), and hands the result
back to the main thread with a queued signal.

The design is DEEP-COPIED when Analyse is pressed: the table stays editable while the
analysis runs, and what is analysed is exactly what was on screen at the click.

Analysing does NOT touch the batch worker: they share nothing except the run folders, which
the analysis only reads.
"""
from __future__ import annotations

import copy
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from . import publish as pub
from . import size_bins


class AnalysisController(QObject):
    changed = Signal()                  # busy / progress / result changed
    finished = Signal(object)           # publish.Deliverables, on the main thread
    _done = Signal(object)              # thread -> main

    def __init__(self, parent=None, publish_fn: Callable | None = None) -> None:
        super().__init__(parent)
        self.publish_fn = publish_fn or pub.publish        # tests inject a fake
        self.log: Callable = lambda text, level="info": None
        self.busy = False
        self.progress_text = ""
        self.started_at: float | None = None
        self.last: pub.Deliverables | None = None
        self._done.connect(self._on_done)

    # ---- state ----------------------------------------------------------------------------
    def status(self) -> str:
        if not self.busy:
            return ""
        secs = int(time.time() - (self.started_at or time.time()))
        return f"Analysing … {self.progress_text}  ({secs}s)"

    # ---- run ---------------------------------------------------------------------------------
    def start(self, design, output_dir: Path, *, thr: float | None, options: dict,
              bin_width: float = size_bins.DEFAULT_WIDTH_UM, bin_max: float = size_bins.DEFAULT_MAX_UM) -> bool:
        if self.busy:
            return False
        snapshot = copy.deepcopy(design)
        self.busy, self.progress_text, self.started_at = True, "starting", time.time()
        self.changed.emit()
        threading.Thread(target=self._work, args=(snapshot, Path(output_dir), thr, dict(options), bin_width, bin_max),
                         name="taguchi-analysis", daemon=True).start()
        return True

    def _work(self, design, output_dir: Path, thr, options, bin_width, bin_max) -> None:
        def progress(i: int, n: int, name: str) -> None:
            self.progress_text = f"run {i}/{n}"
            self.log(f"analysis: run {i}/{n}  {name}", "info")

        try:
            result = self.publish_fn(design, output_dir, thr=thr, options=options, bin_width=bin_width,
                                     bin_max=bin_max, progress=progress, log=self.log)
        except Exception as exc:                          # noqa: BLE001 -- shown to the user
            result = pub.Deliverables(output_dir)
            result.problems.append(f"analysis crashed: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc(limit=6), "error")
        self._done.emit(result)

    def _on_done(self, result) -> None:
        self.busy = False
        self.last = result
        self._summarise(result)
        self.changed.emit()
        self.finished.emit(result)

    # ---- what the user is told ------------------------------------------------------------------
    def _summarise(self, d) -> None:
        log = self.log
        if d.refused:
            log(f"analysis REFUSED: {d.refused}", "error")
            log("nothing was written; any earlier report in the folder is unchanged", "warn")
            return
        for p in d.problems:
            log(p, "error")
        if d.report is None and not d.problems:
            log("analysis finished but wrote no report", "error")
            return
        r = d.results
        log(f"analysis done in {d.seconds:.0f}s: {len(r.runs)} runs, {r.n_conditions} conditions, "
            f"error term = {r.error_source}", "ok" if not d.problems else "warn")
        if d.report:
            log(f"  report    {d.report}", "ok")
        if d.workbook:
            log(f"  workbook  {d.workbook}", "ok")
        if d.figures:
            log(f"  figures   {len(d.figures) // 2} (png + svg) in {d.figures[0].parent}", "ok")
        if d.csv_dir:
            log(f"  csv       {d.csv_dir}", "ok")
        if d.odd is not None:
            log(f"  odd pack  {d.odd.n_flags} flags, {d.odd.n_images} images"
                + (f" ({d.odd.note})" if d.odd.note else ""), "ok" if d.odd.csv_path else "info")
