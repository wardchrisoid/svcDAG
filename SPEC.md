# svcdag — Service Lifecycle Orchestrator

## What it is
A Python library for deterministic startup and shutdown of dependent services,
defined via a JSON config file. Services are modeled as external subprocesses.
The library resolves dependency order via a DAG and manages process lifecycle.

## Input: JSON config
{
  "services": {
    "database": {
      "command": ["./bin/database", "--port", "5432"],
      "dependencies": [],
      "startup_timeout": 5.0,
      "readiness_check": ["./bin/check_db_ready"]  // optional
    },
    "api_server": {
      "command": ["./bin/api"],
      "dependencies": ["database"]
    }
  }
}

## Core behavior

### Startup
1. Load and validate JSON schema
2. Cycle detection via Kahn's algorithm — abort if cycle found
3. Topological sort — produces execution levels
4. Within each level, start services in alphabetical order
5. Each service started via subprocess.Popen
6. Readiness: poll PID alive for startup_timeout duration (default 5s)
   - If readiness_check command provided, run it and require exit code 0
7. On failure: abort entire startup, shutdown already-running services
   in reverse order, report failed service + cascade of never-started services

### Shutdown
1. Reverse topological level order
2. Send SIGTERM to all services in level concurrently
3. Wait shutdown_timeout (default 5s)
4. SIGKILL any survivors
5. Report any force-killed services

## What this library is NOT
- Not a service supervisor (no restart on crash)
- Not a config manager (env vars, config files are caller's responsibility)
- Not a service discovery tool
- Does not persist state across runs

## Project structure
src/svcdag/
    __init__.py
    models.py        # Service dataclass, LifecycleResult
    graph.py         # DAG construction, Kahn's algorithm, cycle detection
    loader.py        # JSON loading and schema validation
    orchestrator.py  # Startup/shutdown execution logic, Popen management
    exceptions.py    # CycleDetectedError, StartupError, SchemaError
tests/
    test_graph.py
    test_loader.py
    test_orchestrator.py
pyproject.toml
README.md
SPEC.md
```