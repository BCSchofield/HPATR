"""Test-session guards.

1. Never write the user's real app preferences (pane_runs.app_settings checks this).

2. Destroy every test's Qt widgets DETERMINISTICALLY, between tests.
   Widgets left behind sit in reference cycles (bound-method slots, lambdas), and
   Python's cycle collector frees them whenever it next runs -- which can be in
   the middle of a LATER test's Qt event dispatch. Deleting a QWidget while Qt is
   delivering events is a segfault, which is why the suite crashed rarely, in a
   different test each time (twice, in Phases 5 and 6). Here each test's top-level
   widgets are closed and deleted, posted deletions flushed, and gc run, all
   outside any event processing.
"""
import gc
import os
import sys

import pytest

os.environ["TAGUCHI_UI_NO_SETTINGS"] = "1"

# 3. Never touch this machine's real ETA memory (~/.hpatr/eta_calibration.json): every test that
#    runs a worker gets a throwaway calibration file even if it forgets to set one itself.
import tempfile as _tempfile
os.environ["TAGUCHI_UI_CALIBRATION"] = os.path.join(_tempfile.mkdtemp(prefix="taguchi_calib_"),
                                                     "calib.json")


@pytest.fixture(autouse=True)
def _destroy_qt_widgets_between_tests():
    yield
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    app.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    app.processEvents()
