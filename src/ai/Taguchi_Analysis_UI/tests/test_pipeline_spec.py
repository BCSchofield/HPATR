"""Tests for the pipeline contract.

The most important tests here are the MUTATION tests: they edit a copy of
the real pipeline (rename a flag, drop a choice, remove a parameter) and
assert preflight catches it. Without them, a preflight that silently passed
everything would look exactly like a working one.

Run (stdlib unittest; pytest also works if installed):
    python -m unittest src.ai.Taguchi_Analysis_UI.tests.test_pipeline_spec -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from src.ai.Taguchi_Analysis_UI import paths
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec


def _quiet_import(name):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        return spec.rdc_module(name)


class LivePipelineTests(unittest.TestCase):
    """Against the real AI/Real_Data_Code, as it is on disk now."""

    def test_preflight_passes_on_live_pipeline(self):
        report = spec.preflight()
        self.assertTrue(report.ok, "\n".join(report.render()))

    def test_measurement_dir_matches_process_capture_source(self):
        # The contract's folder name must be the one the code builds, not the
        # one its (stale) docstring describes.
        src = (paths.RDC_DIR / "process_capture.py").read_text()
        self.assertIn('f"droplets_{score_thresh:.2f}"', src)
        self.assertEqual(spec.MEAS_DIR.format(thr=0.3), "droplets_0.30")

    def test_timing_keys_match_process_capture_stage_names(self):
        src = (paths.RDC_DIR / "process_capture.py").read_text()
        for key in spec.TIMING_KEYS:
            self.assertIn(f'_Stage("{key}")', src, f"stage '{key}' not in process_capture.py")


class ScriptMutationTests(unittest.TestCase):
    """Edit a COPY of classical_liquid.py; preflight must notice."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Mirror the repo layout: the scripts reach config_loader through
        # HERE.parents[1] / "src", and config_loader finds config/ beside it.
        # Only Real_Data_Code is COPIED (it gets mutated); src/ and config/
        # are symlinked, read-only.
        self.rdc = self.tmp / "AI" / "Real_Data_Code"
        shutil.copytree(paths.RDC_DIR, self.rdc,
                        ignore=shutil.ignore_patterns("__pycache__", "._*"))
        (self.tmp / "src").symlink_to(paths.SRC_DIR)
        (self.tmp / "config").symlink_to(paths.REPO_ROOT / "config")
        self.script = self.rdc / "classical_liquid.py"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mutate(self, old, new):
        text = self.script.read_text()
        self.assertIn(old, text, "mutation target not found -- test needs updating")
        self.script.write_text(text.replace(old, new))

    def test_unmutated_copy_passes(self):
        problems, ok = spec.check_script(spec.CLASSICAL, self.script)
        self.assertEqual(problems, [])
        self.assertIsNotNone(ok)

    def test_renamed_flag_is_caught(self):
        self._mutate('"--images-mode"', '"--img-mode"')
        problems, _ = spec.check_script(spec.CLASSICAL, self.script)
        self.assertTrue(any(p.level == "error" and "--images-mode" in p.message
                            for p in problems), problems)

    def test_removed_root_flag_is_caught(self):
        self._mutate('ap.add_argument("--root"', 'ap.add_argument("--run-root"')
        problems, _ = spec.check_script(spec.CLASSICAL, self.script)
        self.assertTrue(any("--root" in p.message for p in problems), problems)

    def test_dropped_choice_is_caught(self):
        self._mutate('choices=["extremes", "all"], default=None',
                     'choices=["extremes"], default=None')
        problems, _ = spec.check_script(spec.CLASSICAL, self.script)
        self.assertTrue(any("'all'" in p.message for p in problems), problems)

    def test_broken_script_is_caught(self):
        self.script.write_text("raise SystemExit(3)\n")
        problems, _ = spec.check_script(spec.CLASSICAL, self.script)
        self.assertTrue(any("exited 3" in p.message for p in problems), problems)

    def test_missing_script_is_caught(self):
        self.script.unlink()
        problems, _ = spec.check_script(spec.CLASSICAL, self.script)
        self.assertTrue(any("not found" in p.message for p in problems), problems)

    def test_flag_only_in_docstring_does_not_count(self):
        # A docstring example mentioning a flag must not mask its removal.
        self.script.write_text(
            '"""Example:  python classical_liquid.py --root <run> --out-dir x\n'
            '--score-thresh --images-mode {extremes,all}"""\n'
            'import argparse\n'
            'ap = argparse.ArgumentParser(description=__doc__,\n'
            '    formatter_class=argparse.RawDescriptionHelpFormatter)\n'
            'ap.add_argument("--unrelated")\n'
            'ap.parse_args()\n')
        problems, _ = spec.check_script(spec.CLASSICAL, self.script)
        missing = {f for f in spec.CLASSICAL.flags if any(f in p.message for p in problems)}
        self.assertEqual(missing, set(spec.CLASSICAL.flags), problems)

    def test_edited_script_is_reread_not_cached(self):
        spec.check_script(spec.CLASSICAL, self.script)          # warm the cache
        self._mutate('"--images-mode"', '"--img-mode"')
        problems, _ = spec.check_script(spec.CLASSICAL, self.script)
        self.assertTrue(problems, "stale --help served from cache after an edit")


class ImportMutationTests(unittest.TestCase):
    """Fake modules standing in for edited pipeline modules."""

    def _mod(self, fn):
        m = types.ModuleType("fake")
        m.process_capture = fn
        return m

    def test_matching_signature_passes(self):
        def process_capture(cine, run_dir, *, stride=10, score_thresh=0.3, device=None,
                            model_dir=None, images="extremes", ci_stride=None, bg_frames=40,
                            limit=None, reuse=False, log=print, sharpness_rule=False):
            pass
        problems, ok = spec.check_import(spec.PROCESS_CAPTURE, self._mod(process_capture))
        self.assertEqual(problems, [])

    def test_removed_parameter_is_caught(self):
        def process_capture(cine, run_dir, *, stride=10, score_thresh=0.3, device=None,
                            model_dir=None, ci_stride=None, bg_frames=40,
                            limit=None, reuse=False, log=print):   # no `images`
            pass
        problems, _ = spec.check_import(spec.PROCESS_CAPTURE, self._mod(process_capture))
        self.assertTrue(any("images" in p.message for p in problems), problems)

    def test_new_required_parameter_is_caught(self):
        def process_capture(cine, run_dir, calibration, *, stride=10, score_thresh=0.3,
                            device=None, model_dir=None, images="extremes", ci_stride=None,
                            bg_frames=40, limit=None, reuse=False, log=print):
            pass
        problems, _ = spec.check_import(spec.PROCESS_CAPTURE, self._mod(process_capture))
        self.assertTrue(any("calibration" in p.message for p in problems), problems)

    def test_missing_function_is_caught(self):
        problems, _ = spec.check_import(spec.PROCESS_CAPTURE, types.ModuleType("fake"))
        self.assertTrue(any("no longer exists" in p.message for p in problems), problems)

    def test_kwargs_catchall_accepts_any_param(self):
        def process_capture(cine, run_dir, **kwargs):
            pass
        problems, _ = spec.check_import(spec.PROCESS_CAPTURE, self._mod(process_capture))
        self.assertEqual(problems, [])


class BuilderTests(unittest.TestCase):

    RUN = Path("/Volumes/LaCie/Experiments/Sandbox/TaguchiUI_Test/runs/S1_x")

    def test_classical_always_targets_the_run_never_the_default(self):
        # classical_liquid.py defaults --root to 2026/09/28/Trial_1 and
        # --out-dir to skeletonisation_testing. Both must ALWAYS be overridden.
        for opts in spec.all_option_combinations():
            cmd = spec.classical_cmd(self.RUN, spec.RunSettings(), opts)
            self.assertEqual(cmd[cmd.index("--root") + 1], str(self.RUN))
            out = cmd[cmd.index("--out-dir") + 1]
            self.assertTrue(out.startswith(str(self.RUN)), out)
            self.assertNotIn("Trial_1", " ".join(cmd))
            self.assertNotIn("skeletonisation", " ".join(cmd))

    def test_classical_and_measurement_share_the_threshold(self):
        s = spec.RunSettings(score_thresh=0.45)
        cmd = spec.classical_cmd(self.RUN, s, spec.default_options())
        self.assertEqual(cmd[cmd.index("--score-thresh") + 1], "0.45")
        self.assertTrue(cmd[cmd.index("--out-dir") + 1].endswith("liquid_0.45"))
        kw = spec.process_capture_kwargs(self.RUN, s, spec.default_options(), print,
                                         cine=self.RUN / "a.cine")
        self.assertEqual(kw["score_thresh"], 0.45)

    def test_images_option_reaches_both_stages(self):
        for value in ("extremes", "all", None):
            opts = dict(spec.default_options(), images=value)
            cmd = spec.classical_cmd(self.RUN, spec.RunSettings(), opts)
            kw = spec.process_capture_kwargs(self.RUN, spec.RunSettings(), opts, print,
                                             cine=self.RUN / "a.cine")
            self.assertEqual(kw["images"], value)
            if value:
                self.assertEqual(cmd[cmd.index("--images-mode") + 1], value)
            else:
                self.assertNotIn("--images-mode", cmd)

    def test_unset_settings_are_omitted_so_pipeline_defaults_apply(self):
        kw = spec.process_capture_kwargs(self.RUN, spec.RunSettings(), spec.default_options(),
                                         print, cine=self.RUN / "a.cine")
        for key in ("device", "model_dir", "ci_stride", "bg_frames", "limit"):
            self.assertNotIn(key, kw)
        kw = spec.process_capture_kwargs(self.RUN, spec.RunSettings(limit=40, device="mps"),
                                         spec.default_options(), print, cine=self.RUN / "a.cine")
        self.assertEqual((kw["limit"], kw["device"]), (40, "mps"))

    def test_defaults_are_read_live_not_hardcoded(self):
        pc = _quiet_import("process_capture")
        original = pc.DEFAULT_SCORE_THRESH
        try:
            pc.DEFAULT_SCORE_THRESH = 0.42
            self.assertEqual(spec.effective(spec.RunSettings()).score_thresh, 0.42)
            cmd = spec.classical_cmd(self.RUN, spec.RunSettings(), spec.default_options())
            self.assertTrue(cmd[cmd.index("--out-dir") + 1].endswith("liquid_0.42"))
        finally:
            pc.DEFAULT_SCORE_THRESH = original

    def test_undeclared_flag_in_builder_is_refused(self):
        with self.assertRaises(AssertionError):
            spec._check_declared(["--root", "--sneaky"], spec.CLASSICAL.flags, "test")


class OptionTests(unittest.TestCase):

    def test_round_trip_for_every_option_combination(self):
        for opts in spec.all_option_combinations():
            self.assertEqual(spec.resolve_options(spec.ticks_for(opts)), opts)

    def test_defaults_draw_extremes_only_and_no_optional_packs(self):
        self.assertEqual(spec.default_options(),
                         {"images": "extremes", "flat_csvs": False, "odd_pack": False})

    def test_every_frame_beats_extremes(self):
        ticks = spec.default_ticks() | {"meas_all"}
        self.assertEqual(spec.resolve_options(ticks)["images"], "all")

    def test_extreme_images_are_mandatory_and_cannot_be_unticked(self):
        # Decided with the user: extremes are always made. There is no tick
        # state that yields zero PNGs.
        self.assertTrue(spec.OUTPUTS_BY_ID["meas_extremes"].mandatory)
        self.assertTrue(spec.OUTPUTS_BY_ID["clas_extremes"].mandatory)
        ticks = {o.id for o in spec.OUTPUTS if o.mandatory}      # nothing optional ticked
        self.assertEqual(spec.resolve_options(ticks)["images"], "extremes")

    def test_every_frame_replaces_extremes_in_the_expected_outputs(self):
        extremes = {"meas_extremes", "clas_extremes"}
        for images, expect_extremes in (("extremes", True), ("all", False)):
            ids = {o.id for o in spec.active_outputs(dict(spec.default_options(), images=images),
                                                     scope="run")}
            self.assertEqual(extremes <= ids, expect_extremes, images)
            self.assertEqual({"meas_all", "clas_all"} <= ids, not expect_extremes, images)

    def test_mandatory_outputs_are_never_optional(self):
        for o in spec.OUTPUTS:
            if o.mandatory:
                self.assertIsNone(o.option, o.id)
            else:
                self.assertIn(o.option, spec.OPTIONS_BY_ID, o.id)


class RuntimeCheckTests(unittest.TestCase):

    def setUp(self):
        self.run = Path(tempfile.mkdtemp()) / "090432_3000sccm_300rpm_4000sps_or1.2_bh1"
        self.n = 5

    def tearDown(self):
        shutil.rmtree(self.run.parent, ignore_errors=True)

    def _build(self, images="extremes"):
        """A synthetic run folder with exactly what the contract promises."""
        raw = self.run / "shadowgraph" / "raw"
        an = self.run / "shadowgraph" / "analysis"
        meas, clas = an / "droplets_0.30", an / "liquid_0.30"
        for d in (raw / "frames" / "8bit", raw / "frames" / "16bit", meas, clas):
            d.mkdir(parents=True, exist_ok=True)
        stems = [f"frame_{i:04d}_n{i * 10}" for i in range(self.n)]
        for s in stems:
            (raw / "frames" / "8bit" / f"{s}.png").touch()
            (raw / "frames" / "16bit" / f"{s}.tiff").touch()
        (raw / "extraction_metadata.json").write_text(json.dumps({"frame_count": self.n}))
        for f in ("instances.json", "frame_runs.json", "background_median.tiff"):
            (raw / f).touch()
        (an / "predictions.json").touch()
        for f in ("droplet_sizes.csv", "object_areas.csv", "per_frame.csv", "summary.json",
                  "size_histograms.png"):
            (meas / f).touch()
        for f in ("classical_summary.json", "classical_per_frame.csv",
                  "classical_components.csv", "size_histograms.png"):
            (clas / f).touch()
        if images == "extremes":
            for s in stems[:3]:
                (meas / f"{s}.png").touch()
            (clas / "extreme_images").mkdir()
            for s in stems[:2]:
                (clas / "extreme_images" / f"{s}.png").touch()
        elif images == "all":
            (clas / "images").mkdir()
            for s in stems:
                (meas / f"{s}.png").touch()
                (clas / "images" / f"{s}.png").touch()

    def _opts(self, images):
        return dict(spec.default_options(), images=images)

    def test_complete_run_verifies_clean_for_each_images_mode(self):
        for images in ("extremes", "all", None):
            with self.subTest(images=images):
                shutil.rmtree(self.run, ignore_errors=True)
                self._build(images)
                problems = spec.verify_run_outputs(self.run, spec.RunSettings(),
                                                   self._opts(images))
                self.assertEqual(problems, [])

    def test_missing_mandatory_file_is_reported(self):
        self._build()
        (self.run / "shadowgraph" / "analysis" / "droplets_0.30" / "summary.json").unlink()
        problems = spec.verify_run_outputs(self.run, spec.RunSettings(), self._opts("extremes"))
        self.assertTrue(any("summary.json" in p.where for p in problems), problems)

    def test_partial_every_frame_run_is_reported(self):
        self._build("all")
        (self.run / "shadowgraph" / "analysis" / "liquid_0.30" / "images"
         / "frame_0000_n0.png").unlink()
        problems = spec.verify_run_outputs(self.run, spec.RunSettings(), self._opts("all"))
        self.assertTrue(any("images" in p.where and "found 4" in p.message
                            for p in problems), problems)

    def test_appledouble_sidecars_are_not_counted(self):
        self._build()
        (self.run / "shadowgraph" / "raw" / "frames" / "8bit" / "._frame_0000_n0.png").touch()
        problems = spec.verify_run_outputs(self.run, spec.RunSettings(), self._opts("extremes"))
        self.assertEqual(problems, [])

    def test_measurement_dir_check(self):
        good = {"_measurement_dir": str(spec.meas_dir(self.run, 0.30))}
        self.assertEqual(spec.check_measurement_dir(good, self.run, 0.30), [])
        bad = {"_measurement_dir": str(self.run / "shadowgraph/analysis/measurement_0.30")}
        self.assertEqual(spec.check_measurement_dir(bad, self.run, 0.30)[0].level, "error")
        self.assertEqual(spec.check_measurement_dir({}, self.run, 0.30)[0].level, "error")

    def test_unknown_stage_seconds_key_warns(self):
        v = spec.check_stage_seconds({"_stage_seconds": {"inference": 1.0, "denoise": 2.0}})
        self.assertEqual([(x.level, "denoise" in x.message) for x in v], [("warn", True)])

    def test_find_cine_requires_exactly_one(self):
        cine_dir = self.run / "shadowgraph" / "raw" / "CINE"
        cine_dir.mkdir(parents=True)
        with self.assertRaises(ValueError):
            spec.find_cine(self.run)
        (cine_dir / "recording_1.cine").touch()
        (cine_dir / "._recording_1.cine").touch()        # exFAT sidecar, ignored
        self.assertEqual(spec.find_cine(self.run).name, "recording_1.cine")
        (cine_dir / "recording_2.cine").touch()
        with self.assertRaises(ValueError):
            spec.find_cine(self.run)


class SelfCheckCliTests(unittest.TestCase):

    def test_self_check_exits_zero_and_fresh_report_parses(self):
        proc = subprocess.run([sys.executable, "-m", "src.ai.Taguchi_Analysis_UI",
                               "--self-check"], capture_output=True, text=True,
                              cwd=str(paths.REPO_ROOT), timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PREFLIGHT PASSED", proc.stdout)
        report = spec.preflight_fresh()
        self.assertTrue(report.ok, "\n".join(report.render()))
        self.assertEqual(set(report.script_hashes), set(spec.CHAIN_SCRIPTS))


if __name__ == "__main__":
    unittest.main()
