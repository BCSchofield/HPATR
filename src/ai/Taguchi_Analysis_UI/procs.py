"""procs.py -- every OS-specific process operation, and nothing else.

The plan's rule: OS differences live in THIS module only, so the rest of the
worker is plain cross-platform Python. Each function branches on IS_WINDOWS
once, visibly. The Windows branches cannot run on the Mac this was written on;
they are unit-tested by asserting the exact flags handed to the OS
(tests/test_procs.py) and must be exercised for real on the lab PC.

    spawn_detached   start the worker so it survives the UI closing
    is_alive         is this pid our worker, still running? (zombie- and reuse-safe)
    kill_tree        stop a worker AND the pipeline subprocesses it started
    reap_orphans     after a crash, kill pipeline children the dead worker left behind
    keep_awake       stop the machine sleeping through an 18-hour batch
    windows_job      Windows: tie child processes' lives to the worker's
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import paths

IS_WINDOWS = os.name == "nt"

# Windows process-creation flags (winbase.h)
CREATE_NO_WINDOW = 0x08000000           # a console of its OWN with no window. Not DETACHED_PROCESS:
                                        # a worker with NO console makes Windows open a NEW, visible
                                        # console window for every stage it launches (python.exe is a
                                        # console program), and closing one of those kills that stage
                                        # -- the handoff's "blank CMD window" trap. With CREATE_NO_WINDOW
                                        # the stages inherit the worker's invisible console instead.
                                        # Not CREATE_NEW_CONSOLE either: that is a visible window.
CREATE_NEW_PROCESS_GROUP = 0x00000200   # Ctrl-C / Ctrl-Break in the launcher can't reach it
CREATE_BREAKAWAY_FROM_JOB = 0x01000000  # survive a launcher that runs inside a Job object
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5

WORKER_MODULE = "src.ai.Taguchi_Analysis_UI.worker"
# A process is ours only if its command line mentions one of these. Used before
# killing anything found by process group, so a reused pgid can never take down
# an unrelated program.
OURS = ("Taguchi_Analysis_UI", "Real_Data_Code")


def _kernel32():
    """kernel32 with every function this module calls DECLARED. Without argtypes, ctypes
    passes Python ints as 32-bit C ints; on 64-bit Windows a HANDLE does not fit --
    GetCurrentProcess()'s pseudo-handle comes back as 2**64-1 and passing it on raises
    ctypes.ArgumentError ("int too long to convert"), which would kill the worker at start."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    H, D, B = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    for name, res, args in (
            ("OpenProcess", H, (D, B, D)),
            ("GetExitCodeProcess", B, (H, ctypes.POINTER(D))),
            ("CloseHandle", B, (H,)),
            ("GetCurrentProcess", H, ()),
            ("CreateJobObjectW", H, (ctypes.c_void_p, wintypes.LPCWSTR)),
            ("SetInformationJobObject", B, (H, ctypes.c_int, ctypes.c_void_p, D)),
            ("AssignProcessToJobObject", B, (H, H)),
            ("SetThreadExecutionState", ctypes.c_uint, (ctypes.c_uint,))):
        fn = getattr(k32, name)
        fn.restype, fn.argtypes = res, args
    return k32


def _psutil():
    try:
        import psutil
        return psutil
    except Exception:
        return None


# ---- liveness -------------------------------------------------------------------

def create_time(pid: int) -> float | None:
    ps = _psutil()
    if ps is None:
        return None
    try:
        return ps.Process(pid).create_time()
    except Exception:
        return None


def _reap(pid: int) -> bool:
    """POSIX: collect `pid` if it is OUR exited child. Returns True if it had exited.
    Without this, a worker that exits while the UI is still open stays a zombie,
    and os.kill(pid, 0) on a zombie SUCCEEDS -- the UI would think it still alive."""
    if IS_WINDOWS:
        return False
    try:
        got, _ = os.waitpid(pid, os.WNOHANG)
        return got == pid
    except ChildProcessError:
        return False
    except OSError:
        return False


def is_alive(pid: int | None, created: float | None = None) -> bool:
    """Is `pid` running and (if `created` is given) still the SAME process?

    `created` defeats pid reuse: after a crash and a reboot, the old pid number
    can belong to something else entirely."""
    if not pid:
        return False
    if _reap(pid):
        return False
    ps = _psutil()
    if ps is not None:
        try:
            p = ps.Process(pid)
            if p.status() == ps.STATUS_ZOMBIE:
                return False
            if created is not None and abs(p.create_time() - created) > 1.0:
                return False
            return True
        except ps.NoSuchProcess:
            return False
        except ps.AccessDenied:
            return True
        except Exception:
            pass
    if IS_WINDOWS:
        import ctypes
        k32 = _kernel32()
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            from ctypes import wintypes
            code = wintypes.DWORD()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# ---- spawning ------------------------------------------------------------------------

def worker_command(job_dir: Path, args=(), python: str | None = None) -> list[str]:
    # sys.executable on purpose: process_capture launches every stage with
    # sys.executable, so the interpreter that starts the worker decides the whole
    # chain's (the handoff records this biting on the lab PC, where torch is in the
    # system Python 3.11, not a conda env).
    return [python or console_python(), "-u", "-m", WORKER_MODULE, "--job", str(job_dir),
            *[str(a) for a in args]]


def console_python(exe: str | None = None) -> str:
    """The console interpreter. If the app was started with pythonw.exe (no console),
    use the python.exe beside it: CREATE_NO_WINDOW only works for a console program,
    and a worker without a console would pop up a window for every stage."""
    exe = exe or sys.executable
    p = Path(exe)
    if p.name.lower() == "pythonw.exe" and (p.parent / "python.exe").exists():
        return str(p.parent / "python.exe")
    return exe


def spawn_detached(job_dir: Path, args=(), python: str | None = None) -> subprocess.Popen:
    """Start the worker fully detached; it keeps running if the UI closes or crashes.

    Returns the Popen. KEEP IT while the UI is open and call .poll() now and then:
    on POSIX that reaps the worker when it exits, so it never lingers as a zombie.
    `.breakaway` records whether the Windows job breakaway was granted.
    """
    job_dir = Path(job_dir)
    cmd = worker_command(job_dir, args, python)
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    log = open(job_dir / "worker.log", "ab")
    kw = dict(cwd=str(paths.REPO_ROOT), stdin=subprocess.DEVNULL, stdout=log,
              stderr=subprocess.STDOUT, env=env, close_fds=True)
    try:
        if IS_WINDOWS:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0                                   # SW_HIDE
            base = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            try:
                p = subprocess.Popen(cmd, creationflags=base | CREATE_BREAKAWAY_FROM_JOB,
                                     startupinfo=si, **kw)
                p.breakaway = True
            except OSError as exc:
                # The launcher's Job object forbids breakaway. Start anyway, and say
                # so: the worker may then die with the launcher.
                if getattr(exc, "winerror", None) != ERROR_ACCESS_DENIED:
                    raise
                p = subprocess.Popen(cmd, creationflags=base, startupinfo=si, **kw)
                p.breakaway = False
        else:
            # setsid(): a new session with no controlling terminal, so closing the
            # terminal (SIGHUP) or the UI cannot reach it.
            p = subprocess.Popen(cmd, start_new_session=True, **kw)
            p.breakaway = True
    finally:
        log.close()                    # the child holds its own handle
    return p


# ---- stopping --------------------------------------------------------------------------

def group_alive(pgid: int | None) -> bool:
    if IS_WINDOWS or not pgid:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_tree(pid: int, pgid: int | None = None, grace: float = 5.0) -> None:
    """Stop the worker and every pipeline subprocess under it.

    SAFETY RULE: a process GROUP is signalled only if the worker LEADS it
    (pgid == pid, true when spawn_detached started it in its own session).
    A worker started by hand from a terminal or script shares that shell's group;
    signalling the recorded group then would kill the user's shell and everything
    else in it -- found by a mutation test that did exactly that to the test run.
    Otherwise the worker's actual descendants are found and stopped one by one.

    Windows: taskkill /T kills the tree."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    if pgid and pgid != pid:
        pgid = None                                   # not ours to signal
    ps = _psutil()
    if pgid is None:
        if ps is None:
            _signal(pid, signal.SIGTERM)
            _wait_gone(pid, grace)
            _signal(pid, signal.SIGKILL)
            _reap(pid)
            return
        try:
            root = ps.Process(pid)
            victims = [root] + root.children(recursive=True)
        except ps.NoSuchProcess:
            _reap(pid)
            return
        for v in victims:
            try:
                v.terminate()
            except ps.Error:
                pass
        _, alive = ps.wait_procs(victims, timeout=grace)
        for v in alive:
            try:
                v.kill()
            except ps.Error:
                pass
        _reap(pid)
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        _reap(pid)
        return
    end = time.monotonic() + grace
    while time.monotonic() < end:
        _reap(pid)
        if not _group_has_live_members(pgid):
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    _reap(pid)


def _signal(pid: int, sig) -> None:
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _wait_gone(pid: int, timeout: float) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end and is_alive(pid):
        time.sleep(0.1)


def _group_has_live_members(pgid: int) -> bool:
    ps = _psutil()
    if ps is None:
        return group_alive(pgid)
    for p in ps.process_iter(["pid", "status"]):
        try:
            if os.getpgid(p.info["pid"]) == pgid and p.info["status"] != ps.STATUS_ZOMBIE:
                return True
        except (ProcessLookupError, PermissionError, OSError):
            continue
    return False


def reap_orphans(prev_worker: dict | None, log=print) -> int:
    """After a worker died, kill pipeline subprocesses it left running.

    Without this, a resumed worker and an orphaned tiled_inference from the dead
    one would write the same predictions.json at the same time. POSIX only:
    on Windows the worker's kill-on-close Job object (windows_job) means children
    die with it. Only processes whose command line is OURS are touched, and only
    if the old worker started after the last boot -- a reused process group must
    never take down an unrelated program. Returns how many were killed."""
    if IS_WINDOWS or not prev_worker:
        return 0
    pgid, pid = prev_worker.get("pgid"), prev_worker.get("pid")
    if is_alive(pid, prev_worker.get("create_time")):
        return 0
    if not pgid or pgid != pid:
        # The dead worker did not lead its own process group (started by hand, not by
        # spawn_detached), so its children cannot be found safely by group.
        log("note: the previous worker was not started detached; cannot check for "
            "orphaned pipeline processes -- if a stage is still running, stop it first")
        return 0
    ps = _psutil()
    if ps is None:
        if group_alive(pgid):
            log("warning: cannot check for orphaned pipeline processes without psutil; "
                "if a stage from the previous worker is still running, stop it first")
        return 0
    started = prev_worker.get("started_epoch") or 0
    if started and started < ps.boot_time():
        return 0
    victims = []
    for p in ps.process_iter(["pid", "cmdline", "status"]):
        try:
            if p.info["status"] == ps.STATUS_ZOMBIE or os.getpgid(p.info["pid"]) != pgid:
                continue
            if any(tag in " ".join(p.info["cmdline"] or []) for tag in OURS):
                victims.append(p)
        except (ProcessLookupError, PermissionError, OSError, ps.Error):
            continue
    for p in victims:
        try:
            log(f"stopping orphaned pipeline process {p.pid} left by the previous worker")
            p.terminate()
        except ps.Error:
            pass
    _, alive = ps.wait_procs(victims, timeout=5)
    for p in alive:
        try:
            p.kill()
        except ps.Error:
            pass
    return len(victims)


# ---- long-run hygiene --------------------------------------------------------------------

def keep_awake() -> str:
    """Stop the machine sleeping mid-batch. Best-effort; returns what it did."""
    try:
        if sys.platform == "darwin" and shutil.which("caffeinate"):
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return "caffeinate -i (macOS will not idle-sleep while the batch runs)"
        if IS_WINDOWS:
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            if not _kernel32().SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
                return "could not prevent sleep: SetThreadExecutionState failed"
            return "SetThreadExecutionState (Windows will not sleep while the batch runs)"
    except Exception as exc:
        return f"could not prevent sleep: {exc}"
    return "no sleep prevention on this platform"


def windows_job():
    """Windows: put this process in a Job object with KILL_ON_JOB_CLOSE, so every
    child it starts dies when it does -- no orphans, by construction. Returns the
    handle (keep it referenced for the process lifetime) or None elsewhere."""
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9
    k32 = _kernel32()
    h = k32.CreateJobObjectW(None, None)
    if not h:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(h, JobObjectExtendedLimitInformation,
                                       ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    if not k32.AssignProcessToJobObject(h, k32.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    return h
