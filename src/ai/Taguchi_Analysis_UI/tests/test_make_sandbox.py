"""The sandbox builder's guard: the real data tree is off limits, a sibling folder is fine."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.make_sandbox import build


@pytest.fixture
def exp():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "Experiments"
        for name, _, _ in fakes.REAL_10_05[:2]:
            fakes.make_run(root, name)
        yield root


def test_sandbox_beside_the_data_is_allowed_and_mirrors_the_real_tree(exp):
    made = build(exp / "2026" / "10" / "05", exp / "Sandbox" / "T", 2, log=lambda m: None)
    assert [m.name for m in made] == [fakes.REAL_10_05[0][0], fakes.REAL_10_05[1][0]]
    run = made[0]
    assert run.parent == exp / "Sandbox" / "T" / "2026" / "10" / "05"
    cine = next((run / "shadowgraph" / "raw" / "CINE").iterdir())
    assert cine.is_symlink() and cine.resolve().parent.parent.parent.parent.name == run.name
    assert (run / "run_summary.xlsx").is_file() and not (run / "run_summary.xlsx").is_symlink()
    assert (run / "cone").is_dir() and not any((run / "shadowgraph" / "analysis").iterdir())


@pytest.mark.parametrize("inside", ["2026", "2026/10", "2026/10/05", "2026/10/05/x"])
def test_sandbox_inside_the_real_data_tree_is_refused(exp, inside):
    with pytest.raises(SystemExit, match="inside the real data tree"):
        build(exp / "2026" / "10" / "05", exp / inside, 1, log=lambda m: None)


def test_existing_non_sandbox_folder_is_never_overwritten(exp):
    sb = exp / "Sandbox" / "T"
    real_looking = sb / "2026" / "10" / "05" / fakes.REAL_10_05[0][0]
    fakes.make_run(sb, fakes.REAL_10_05[0][0])                 # a REAL cine file, not a symlink
    with pytest.raises(SystemExit, match="not a sandbox run"):
        build(exp / "2026" / "10" / "05", sb, 1, fresh=True, log=lambda m: None)
    assert real_looking.exists()


def test_falls_back_to_a_hard_link_when_symlinks_are_not_allowed(exp, monkeypatch):
    """Windows without Developer Mode refuses symlinks; a hard link still avoids a copy."""
    def no_symlinks(self, target, target_is_directory=False):
        raise OSError("A required privilege is not held by the client")
    monkeypatch.setattr(Path, "symlink_to", no_symlinks)
    made = build(exp / "2026" / "10" / "05", exp / "Sandbox" / "T", 1, log=lambda m: None)
    cine = next((made[0] / "shadowgraph" / "raw" / "CINE").iterdir())
    src = next((exp / "2026" / "10" / "05" / made[0].name / "shadowgraph" / "raw" / "CINE").iterdir())
    assert not cine.is_symlink() and os.path.samefile(cine, src)      # same file, no copy
    # and a re-run recognises its own hard-linked sandbox run instead of refusing it
    assert build(exp / "2026" / "10" / "05", exp / "Sandbox" / "T", 1, log=lambda m: None) == made


def test_explains_what_to_do_when_no_link_is_possible(exp, monkeypatch):
    def refuse(*a, **k):
        raise OSError("not supported")
    monkeypatch.setattr(Path, "symlink_to", refuse)
    monkeypatch.setattr(os, "link", refuse)
    with pytest.raises(SystemExit, match="Developer Mode"):
        build(exp / "2026" / "10" / "05", exp / "Sandbox" / "T", 1, log=lambda m: None)
