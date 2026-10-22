"""Resource-limited execution of an ALLOWLISTED command inside a throwaway workspace.

What this sandbox provides (and what it does not — see SECURITY.md):
  * Only commands from a fixed catalogue can run; clients never supply argv or paths.
  * Scrubbed environment (no inherited secrets), HOME inside the workspace, stdin closed.
  * rlimits: CPU, address space, file size, open files, processes, no core dumps.
  * Wall-clock timeout + cooperative cancellation; the whole process group is SIGKILLed.
  * Output captured with a hard size cap and secret redaction.
  * Network isolation via a new network namespace (``unshare -rn``) when the host supports it.
    If it does not, execution FAILS CLOSED unless NIGHTSHIFT_SANDBOX_REQUIRE_NETNS=0 is set explicitly.
  * NOT provided: filesystem confinement. Repository tests are untrusted code; run NightShift in a
    container/VM (or CodeBuild) for untrusted repositories. Investigation never executes repository code.
"""
from __future__ import annotations

import os
try:
    import resource
except ImportError:
    resource = None
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PermanentError
from .redact import REDACTOR

COMMANDS = {
    "python-unittest": [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"],
}
COMMAND_LABELS = {"none": "none (no regression gate — repairs are blocked)", "python-unittest": "python -m unittest discover -s tests"}


def command_keys() -> list[str]:
    return ["none", *COMMANDS.keys()]


@dataclass
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    cancelled: bool
    duration_seconds: float
    truncated: bool
    isolation: dict = field(default_factory=dict)


class Sandbox:
    def __init__(self, settings):
        self.settings = settings
        self._probe: dict | None = None

    # -- capability probe ---------------------------------------------------------------
    def preflight(self, refresh: bool = False) -> dict:
        if self._probe is not None and not refresh:
            return self._probe
        netns = False
        reason = None
        unshare = shutil.which("unshare")
        if unshare:
            try:
                r = subprocess.run([unshare, "-rn", "--", "true"], capture_output=True, timeout=10)
                netns = r.returncode == 0
                if not netns:
                    reason = "unshare -rn failed (user namespaces may be disabled)"
            except (OSError, subprocess.TimeoutExpired):
                reason = "unshare probe failed"
        else:
            reason = "unshare not found"
        required = bool(getattr(self.settings, "sandbox_require_netns", True))
        available = netns or not required
        self._probe = {
            "available": available,
            "backend": "unshare-netns+rlimits" if netns else "rlimits-only",
            "network_isolated": netns,
            "filesystem_confined": False,
            "require_netns": required,
            "reason": None if available else (reason or "network isolation unavailable"),
            "note": "Process-level isolation only. Run inside a container/VM for untrusted repositories.",
        }
        return self._probe

    # -- execution ----------------------------------------------------------------------
    def run(self, command_key: str, cwd: Path, *, timeout: float | None = None, cancel_cb=None) -> SandboxResult:
        if command_key not in COMMANDS:
            raise PermanentError("COMMAND_NOT_ALLOWED", f"command key {command_key!r} is not in the allowlist")
        return self._run(list(COMMANDS[command_key]), cwd, timeout=timeout, cancel_cb=cancel_cb)

    def _run(self, argv: list[str], cwd: Path, *, timeout: float | None = None, cancel_cb=None) -> SandboxResult:
        probe = self.preflight()
        if not probe["available"]:
            raise PermanentError("SANDBOX_UNSAFE", probe["reason"] or "no safe sandbox available")
        cwd = Path(cwd).resolve()
        if not cwd.is_dir():
            raise PermanentError("SANDBOX_UNSAFE", "workspace directory missing")
        timeout = float(timeout or self.settings.sandbox_timeout_seconds)
        cap = int(self.settings.sandbox_output_cap_bytes)
        mem = int(self.settings.sandbox_memory_bytes)
        home = cwd / ".nightshift-home"
        home.mkdir(exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": str(home), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "NIGHTSHIFT_SANDBOX": "1", "TMPDIR": str(home),
        }
        full = (["unshare", "-rn", "--"] if probe["network_isolated"] else []) + argv

        def limits():
            if resource is None:
                return
            cpu = int(timeout) + 5
            for res, val in (
                (resource.RLIMIT_CPU, (cpu, cpu)),
                (resource.RLIMIT_AS, (mem, mem)),
                (resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024)),
                (resource.RLIMIT_NOFILE, (256, 256)),
                (resource.RLIMIT_CORE, (0, 0)),
                (resource.RLIMIT_NPROC, (512, 512)),
            ):
                try:
                    resource.setrlimit(res, val)
                except (ValueError, OSError):
                    pass

        started = time.monotonic()
        kwargs = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
            if resource is not None:
                kwargs["preexec_fn"] = limits
        proc = subprocess.Popen(full, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **kwargs)
        bufs = {"out": bytearray(), "err": bytearray()}
        truncated = {"v": False}

        def pump(stream, key):
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                room = cap - len(bufs[key])
                if room > 0:
                    bufs[key].extend(chunk[:room])
                if len(chunk) > room:
                    truncated["v"] = True  # keep draining so the child never blocks on a full pipe

        threads = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
                   threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
        for t in threads:
            t.start()

        def kill():
            try:
                if hasattr(os, "killpg"):
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass

        timed_out = cancelled = False
        pending_exc: BaseException | None = None
        try:
            while True:
                try:
                    proc.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancel_cb is not None:
                    try:
                        if cancel_cb():
                            cancelled = True
                            kill()
                            break
                    except BaseException as e:  # noqa: BLE001 — cancel/pause/lease-lost signals; re-raised after cleanup
                        pending_exc = e
                        kill()
                        break
                if time.monotonic() - started > timeout:
                    timed_out = True
                    kill()
                    break
        finally:
            kill()  # make sure no stray child (e.g. a backgrounded process) outlives the run
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            for t in threads:
                t.join(timeout=2)
        if pending_exc is not None:
            raise pending_exc
        text = lambda b: REDACTOR.text(bytes(b).decode("utf-8", "replace"))
        return SandboxResult(
            exit_code=proc.returncode, stdout=text(bufs["out"]), stderr=text(bufs["err"]), timed_out=timed_out,
            cancelled=cancelled, duration_seconds=round(time.monotonic() - started, 3), truncated=truncated["v"],
            isolation={"backend": probe["backend"], "network_isolated": probe["network_isolated"],
                       "filesystem_confined": False},
        )
