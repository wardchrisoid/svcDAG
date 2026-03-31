import platform
import sys

import pytest

from svcdag.exceptions import CycleDetectedError, StartupError
from svcdag.graph import execution_order
from svcdag.models import LifecycleResult, OrchestratorState, ServiceConfig
from svcdag.orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Subprocess command constants — use the current interpreter so they always
# exist on any machine running the tests.
# ---------------------------------------------------------------------------

SLEEP_CMD = [sys.executable, "-c", "import time; time.sleep(100)"]
EXIT_0_CMD = [sys.executable, "-c", ""]            # exits 0 immediately
EXIT_1_CMD = [sys.executable, "-c", "import sys; sys.exit(1)"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def single_svc():
    return ServiceConfig(name="svc", command=SLEEP_CMD)


@pytest.fixture
def two_svcs():
    return [
        ServiceConfig(name="alpha", command=SLEEP_CMD),
        ServiceConfig(name="beta", command=SLEEP_CMD, dependencies=["alpha"]),
    ]


@pytest.fixture
def three_chain():
    """a -> b -> c linear chain."""
    return [
        ServiceConfig(name="a", command=SLEEP_CMD),
        ServiceConfig(name="b", command=SLEEP_CMD, dependencies=["a"]),
        ServiceConfig(name="c", command=SLEEP_CMD, dependencies=["b"]),
    ]


@pytest.fixture
def started_orchestrator(single_svc):
    orch = Orchestrator([single_svc])
    orch.start()
    yield orch
    orch.stop()


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestStateTransitions:
    def test_initial_state_is_none(self, single_svc):
        orch = Orchestrator([single_svc])
        assert orch.state is None

    def test_state_running_after_start(self, started_orchestrator):
        assert started_orchestrator.state == OrchestratorState.RUNNING

    def test_state_none_after_stop(self, single_svc):
        orch = Orchestrator([single_svc])
        orch.start()
        orch.stop()
        assert orch.state is None

    def test_state_reset_after_startup_error(self):
        svc = ServiceConfig(name="svc", command=EXIT_1_CMD)
        orch = Orchestrator([svc])
        with pytest.raises(StartupError):
            orch.start()
        assert orch.state is None

    def test_state_reset_after_cycle_error(self):
        svcs = [
            ServiceConfig(name="a", command=SLEEP_CMD, dependencies=["b"]),
            ServiceConfig(name="b", command=SLEEP_CMD, dependencies=["a"]),
        ]
        orch = Orchestrator(svcs)
        with pytest.raises(CycleDetectedError):
            orch.start()
        assert orch.state is None


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

class TestStartup:
    def test_start_returns_lifecycle_result(self, started_orchestrator):
        # started_orchestrator already called start(); re-test return value
        svc = ServiceConfig(name="svc2", command=SLEEP_CMD)
        orch = Orchestrator([svc])
        result = orch.start()
        orch.stop()
        assert isinstance(result, LifecycleResult)
        assert result.success is True

    def test_start_records_started_names(self, two_svcs):
        orch = Orchestrator(two_svcs)
        result = orch.start()
        orch.stop()
        assert set(result.started) == {"alpha", "beta"}

    def test_start_called_twice_raises(self, started_orchestrator):
        with pytest.raises(RuntimeError, match="already in state"):
            started_orchestrator.start()

    def test_start_with_readiness_check_succeeds(self):
        svc = ServiceConfig(
            name="svc",
            command=SLEEP_CMD,
            readiness_check=EXIT_0_CMD,
            startup_timeout=5.0,
        )
        orch = Orchestrator([svc])
        result = orch.start()
        orch.stop()
        assert result.success is True

    def test_start_with_failing_readiness_check_raises(self):
        svc = ServiceConfig(
            name="svc",
            command=SLEEP_CMD,
            readiness_check=EXIT_1_CMD,
            startup_timeout=0.3,
        )
        orch = Orchestrator([svc])
        with pytest.raises(StartupError) as exc_info:
            orch.start()
        assert exc_info.value.failed_service == "svc"

    def test_immediate_exit_raises_startup_error(self):
        svc = ServiceConfig(name="svc", command=EXIT_1_CMD)
        orch = Orchestrator([svc])
        with pytest.raises(StartupError) as exc_info:
            orch.start()
        assert exc_info.value.failed_service == "svc"

    def test_startup_failure_cleans_up_prior_services(self):
        svcs = [
            ServiceConfig(name="alpha", command=SLEEP_CMD),
            ServiceConfig(name="beta", command=EXIT_1_CMD, dependencies=["alpha"]),
        ]
        orch = Orchestrator(svcs)
        with pytest.raises(StartupError):
            orch.start()

        # alpha should have been cleaned up — its process is no longer in _processes
        assert orch._processes == {}

    def test_never_started_populated_correctly(self, three_chain):
        # Override middle service to fail; 'c' should be in never_started
        svcs = [
            ServiceConfig(name="a", command=SLEEP_CMD),
            ServiceConfig(name="b", command=EXIT_1_CMD, dependencies=["a"]),
            ServiceConfig(name="c", command=SLEEP_CMD, dependencies=["b"]),
        ]
        orch = Orchestrator(svcs)
        with pytest.raises(StartupError) as exc_info:
            orch.start()
        assert exc_info.value.failed_service == "b"
        assert exc_info.value.never_started == ["c"]

    def test_never_started_empty_when_last_fails(self):
        svc = ServiceConfig(name="only", command=EXIT_1_CMD)
        orch = Orchestrator([svc])
        with pytest.raises(StartupError) as exc_info:
            orch.start()
        assert exc_info.value.never_started == []

    def test_cycle_raises_cycle_detected_error(self):
        svcs = [
            ServiceConfig(name="a", command=SLEEP_CMD, dependencies=["b"]),
            ServiceConfig(name="b", command=SLEEP_CMD, dependencies=["a"]),
        ]
        orch = Orchestrator(svcs)
        with pytest.raises(CycleDetectedError):
            orch.start()

    def test_bad_command_raises_startup_error(self):
        svc = ServiceConfig(name="svc", command=["__nonexistent_binary__"])
        orch = Orchestrator([svc])
        with pytest.raises(StartupError) as exc_info:
            orch.start()
        assert exc_info.value.failed_service == "svc"


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_stop_returns_lifecycle_result(self, started_orchestrator):
        result = started_orchestrator.stop()
        assert isinstance(result, LifecycleResult)
        assert result.success is True

    def test_stop_before_start_is_safe(self, single_svc):
        orch = Orchestrator([single_svc])
        result = orch.stop()
        assert result.success is True
        assert result.force_killed == []
        assert result.errors == {}

    def test_stop_terminates_process(self, single_svc):
        orch = Orchestrator([single_svc])
        orch.start()
        proc = orch._processes["svc"]
        orch.stop()
        assert proc.poll() is not None

    def test_stop_on_already_dead_process(self):
        # Process must outlive the startup settle window (0.5s), then die on its own.
        # startup_timeout=0.3 → settle = min(0.5, 0.3) = 0.3s.
        # Process sleeps 0.7s, so it's alive during the 0.3s settle, then exits.
        import time
        svc = ServiceConfig(
            name="svc",
            command=[sys.executable, "-c", "import time; time.sleep(0.7)"],
            startup_timeout=0.3,
        )
        orch = Orchestrator([svc])
        orch.start()
        time.sleep(0.8)  # let the process die naturally
        result = orch.stop()
        assert result.success is True

    def test_stop_is_idempotent(self, single_svc):
        orch = Orchestrator([single_svc])
        orch.start()
        orch.stop()
        result = orch.stop()  # second call
        assert result.success is True

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason="terminate() is immediate on Windows; TimeoutExpired never raised",
    )
    def test_force_killed_populated(self):
        # Process that ignores SIGTERM (Unix only)
        signal_ignorer = [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(100)",
        ]
        svc = ServiceConfig(name="svc", command=signal_ignorer, shutdown_timeout=0.5)
        orch = Orchestrator([svc])
        orch.start()
        result = orch.stop()
        assert "svc" in result.force_killed


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_context_manager_starts_and_stops(self, single_svc):
        orch = Orchestrator([single_svc])
        with orch:
            assert orch.state == OrchestratorState.RUNNING
        assert orch.state is None

    def test_context_manager_stops_on_inner_exception(self, single_svc):
        orch = Orchestrator([single_svc])
        proc = None
        with pytest.raises(ValueError):
            with orch:
                proc = orch._processes["svc"]
                raise ValueError("simulated error")
        assert proc is not None
        assert proc.poll() is not None  # process was cleaned up

    def test_from_file_returns_orchestrator(self):
        orch = Orchestrator.from_file("tests/configs/simple.json")
        assert isinstance(orch, Orchestrator)
        assert len(orch._services) == 4


# ---------------------------------------------------------------------------
# Startup ordering
# ---------------------------------------------------------------------------

class TestStartupOrdering:
    def test_started_list_follows_execution_order(self, two_svcs):
        orch = Orchestrator(two_svcs)
        result = orch.start()
        orch.stop()
        expected = execution_order(two_svcs)
        assert result.started == expected

    def test_started_list_alphabetical_within_level(self):
        # Both services have no dependencies — should start alphabetically
        svcs = [
            ServiceConfig(name="zebra", command=SLEEP_CMD),
            ServiceConfig(name="apple", command=SLEEP_CMD),
        ]
        orch = Orchestrator(svcs)
        result = orch.start()
        orch.stop()
        assert result.started == ["apple", "zebra"]
