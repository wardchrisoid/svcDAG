import subprocess
import sys
import time
from pathlib import Path

from svcdag.exceptions import StartupError
from svcdag.graph import build_levels
from svcdag.loader import load
from svcdag.models import LifecycleResult, OrchestratorState, ServiceConfig

_READINESS_POLL_INTERVAL: float = 0.1
# How long to observe a process (with no readiness_check) before declaring it started.
# Must be long enough for a fast-failing process to exit; 0.5s comfortably covers
# typical Python interpreter startup time (~50–100ms).
_STARTUP_SETTLE_SECS: float = 0.5

# Suppress console windows on Windows when spawning subprocesses
_POPEN_KWARGS: dict = {}
if sys.platform == "win32":
    _POPEN_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


class Orchestrator:
    def __init__(self, services: list[ServiceConfig]) -> None:
        self._services: list[ServiceConfig] = services
        self._svc_map: dict[str, ServiceConfig] = {s.name: s for s in services}
        self._processes: dict[str, subprocess.Popen] = {}
        self._state: OrchestratorState | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> "Orchestrator":
        return cls(load(path))

    @property
    def state(self) -> OrchestratorState | None:
        return self._state

    def start(self) -> LifecycleResult:
        if self._state is not None:
            raise RuntimeError(
                f"Cannot start: orchestrator is already in state '{self._state.value}'."
            )

        self._state = OrchestratorState.STARTING
        try:
            levels = build_levels(self._services)

            for level in levels:
                for name in level:
                    svc = self._svc_map[name]
                    try:
                        proc = subprocess.Popen(svc.command, **_POPEN_KWARGS)
                    except Exception as e:
                        self._emergency_shutdown()
                        never_started = self._compute_never_started(name)
                        self._state = None
                        raise StartupError(
                            failed_service=name,
                            never_started=never_started,
                            message=str(e),
                        ) from e

                    self._processes[name] = proc
                    error = _wait_ready(proc, svc)
                    if error:
                        never_started = self._compute_never_started(name)
                        self._emergency_shutdown()
                        self._state = None
                        raise StartupError(
                            failed_service=name,
                            never_started=never_started,
                            message=error,
                        )

        except StartupError:
            raise
        except Exception:
            self._state = None
            raise

        self._state = OrchestratorState.RUNNING
        return LifecycleResult(success=True, started=list(self._processes.keys()))

    def stop(self) -> LifecycleResult:
        if not self._processes:
            return LifecycleResult(success=True)

        self._state = OrchestratorState.STOPPING
        force_killed: list[str] = []
        errors: dict[str, str] = {}

        try:
            levels = build_levels(self._services)
        except Exception as e:
            self._state = None
            return LifecycleResult(success=False, errors={"__graph__": str(e)})

        for level in reversed(levels):
            for name in reversed(level):
                proc = self._processes.pop(name, None)
                if proc is None:
                    continue
                svc = self._svc_map[name]
                try:
                    killed = _terminate(proc, svc.shutdown_timeout)
                    if killed:
                        force_killed.append(name)
                except Exception as e:
                    errors[name] = str(e)

        self._state = None
        return LifecycleResult(
            success=len(errors) == 0,
            force_killed=force_killed,
            errors=errors,
        )

    def _compute_never_started(self, failed_name: str) -> list[str]:
        return sorted(
            s.name
            for s in self._services
            if s.name not in self._processes and s.name != failed_name
        )

    def _emergency_shutdown(self) -> None:
        """Best-effort cleanup of running processes during a startup failure."""
        for name, proc in reversed(list(self._processes.items())):
            svc = self._svc_map[name]
            try:
                _terminate(proc, svc.shutdown_timeout)
            except Exception:
                pass
        self._processes = {}

    def __enter__(self) -> "Orchestrator":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


def _wait_ready(proc: subprocess.Popen, svc: ServiceConfig) -> str | None:
    """
    Check that a process is alive and ready.
    Returns None on success, or an error message string on failure.
    """
    if svc.readiness_check is None:
        # Poll for a short window so fast-failing processes have time to exit.
        settle = min(_STARTUP_SETTLE_SECS, svc.startup_timeout)
        deadline = time.monotonic() + settle
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return f"Process exited with return code {proc.returncode}."
            time.sleep(_READINESS_POLL_INTERVAL)
        # Final check after settle window
        if proc.poll() is not None:
            return f"Process exited with return code {proc.returncode}."
        return None

    deadline = time.monotonic() + svc.startup_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return (
                f"Process exited with return code {proc.returncode} "
                f"before readiness check passed."
            )
        result = subprocess.run(
            svc.readiness_check,
            capture_output=True,
            **_POPEN_KWARGS,
        )
        if result.returncode == 0:
            return None
        time.sleep(_READINESS_POLL_INTERVAL)

    return f"Readiness check timed out after {svc.startup_timeout}s."


def _terminate(proc: subprocess.Popen, timeout: float) -> bool:
    """
    Gracefully terminate a process. Returns True if it had to be force-killed.
    Note: on Windows, terminate() calls TerminateProcess() which is immediate,
    so the graceful period is effectively zero and force_kill will not occur.
    """
    if proc.poll() is not None:
        return False
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
        return False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return True
