# svcdag

Deterministic startup and shutdown of dependent services via a DAG.

`svcdag` is a Python library for orchestrating external subprocesses in dependency order. Define your services in a JSON config file; svcdag resolves the dependency graph, starts everything in the right order, and shuts it all down cleanly — with or without readiness checks.

---

## Install

```bash
pip install svcdag
```

## Quick start

```python
from svcdag import Orchestrator

with Orchestrator.from_file("services.json") as orch:
    input("Services running. Press Enter to shut down...")
# all services stopped automatically
```

Or manage lifecycle manually:

```python
from svcdag import Orchestrator, StartupError

orch = Orchestrator.from_file("services.json")

try:
    result = orch.start()
    print(f"Started: {result.started}")
except StartupError as e:
    print(f"Failed: {e.failed_service}")
    print(f"Never reached: {e.never_started}")
finally:
    result = orch.stop()
    if result.force_killed:
        print(f"Force-killed: {result.force_killed}")
```

---

## Config format

```json
{
  "services": {
    "database": {
      "command": ["./bin/database", "--port", "5432"],
      "dependencies": [],
      "startup_timeout": 5.0,
      "shutdown_timeout": 5.0,
      "readiness_check": ["./bin/check_db_ready"]
    },
    "cache": {
      "command": ["./bin/cache"],
      "dependencies": []
    },
    "api_server": {
      "command": ["./bin/api"],
      "dependencies": ["database", "cache"]
    },
    "worker": {
      "command": ["./bin/worker"],
      "dependencies": ["api_server"]
    }
  }
}
```

### Service fields

| Field | Required | Default | Description |
|---|---|---|---|
| `command` | Yes | — | Argv list to launch the process |
| `dependencies` | No | `[]` | Names of services that must be running first |
| `startup_timeout` | No | `5.0` | Seconds to wait for the process to become ready |
| `shutdown_timeout` | No | `5.0` | Seconds to wait for graceful exit before force-killing |
| `readiness_check` | No | `null` | Command to poll (exit 0 = ready) within `startup_timeout` |

---

## Behavior

### Startup

1. The JSON config is loaded and validated.
2. Dependencies are resolved via topological sort (Kahn's algorithm). A `CycleDetectedError` is raised immediately if a cycle is found.
3. Services are started level by level — services with no dependencies first, then their dependents, and so on. Within each level, services start in alphabetical order.
4. Each service is launched via `subprocess.Popen`.
5. **Without `readiness_check`**: the process is observed for a short window. If it exits during that window, startup fails.
6. **With `readiness_check`**: the check command is polled until it exits with code 0, or `startup_timeout` is exceeded.
7. If any service fails to start, all already-running services are shut down in reverse order before `StartupError` is raised.

### Shutdown

1. Services stop in reverse dependency order (reverse alphabetical within each level).
2. Each service receives a graceful termination signal.
3. If a service does not exit within `shutdown_timeout`, it is force-killed.
4. `stop()` is best-effort — it always returns a `LifecycleResult` and never raises.

---

## API reference

### `Orchestrator`

```python
Orchestrator(services: list[ServiceConfig])
Orchestrator.from_file(path: str | Path) -> Orchestrator
```

| Method / Property | Description |
|---|---|
| `start() -> LifecycleResult` | Start all services. Raises `StartupError` on failure. |
| `stop() -> LifecycleResult` | Stop all services. Always returns, never raises. |
| `state -> OrchestratorState \| None` | Current state: `STARTING`, `RUNNING`, `STOPPING`, or `None`. |
| Context manager | `__enter__` calls `start()`, `__exit__` calls `stop()`. |

### `LifecycleResult`

```python
@dataclass
class LifecycleResult:
    success: bool
    started: list[str]       # services successfully started (startup)
    failed: str | None       # service that caused abort (unused by stop())
    never_started: list[str] # services skipped due to cascade failure
    force_killed: list[str]  # services that had to be force-killed (shutdown)
    errors: dict[str, str]   # service name -> error message
```

### Exceptions

| Exception | When raised |
|---|---|
| `SchemaError` | Config file is missing required fields or has invalid types |
| `CycleDetectedError` | A dependency cycle is detected (`.cycle` attribute lists involved services) |
| `StartupError` | A service fails to start (`.failed_service`, `.never_started` attributes) |

---

## Debug tool

A `show_order.py` script is included to inspect the startup order of a config without launching any processes:

```bash
python show_order.py services.json
```

Output:
```
Config: services.json
Services: 4

=== Startup order (by level) ===
  Level 0: cache
           database
  Level 1: api_server  (deps: database, cache)
  Level 2: worker  (deps: api_server)

=== Flat serial order ===
  1. cache
  2. database
  3. api_server
  4. worker

=== Shutdown order (reverse) ===
  1. worker
  2. api_server
  3. database
  4. cache
```

---

## What svcdag is not

- **Not a process supervisor** — services that crash after startup are not restarted
- **Not a config manager** — environment variables and config files are your responsibility
- **Not a service discovery tool**
- **Does not persist state** across runs

---

## Requirements

- Python 3.11+
- No external dependencies

## License

MIT
