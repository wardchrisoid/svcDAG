import json
from pathlib import Path

from svcdag.exceptions import SchemaError
from svcdag.models import ServiceConfig


def load(path: str | Path) -> list[ServiceConfig]:
    """
    Load and validate a svcdag JSON config file.

    Raises:
        OSError: if the file cannot be read.
        json.JSONDecodeError: if the file is not valid JSON.
        SchemaError: if the config structure or field types are invalid.
    """
    with open(path) as f:
        raw = json.load(f)

    _validate_root(raw)

    services_raw: dict = raw["services"]
    services = [_parse_service(name, cfg) for name, cfg in services_raw.items()]

    _validate_dependency_references(services)

    return services


# ---------------------------------------------------------------------------
# Internal validation helpers
# ---------------------------------------------------------------------------

def _validate_root(raw: object) -> None:
    if not isinstance(raw, dict):
        raise SchemaError("Config root must be a JSON object.")
    if "services" not in raw:
        raise SchemaError("Config must have a top-level 'services' key.")
    if not isinstance(raw["services"], dict):
        raise SchemaError("'services' must be a JSON object.")
    if len(raw["services"]) == 0:
        raise SchemaError("'services' must define at least one service.")


def _parse_service(name: str, cfg: object) -> ServiceConfig:
    if not isinstance(cfg, dict):
        raise SchemaError(f"Service '{name}' must be a JSON object.")

    # command — required, non-empty list of strings
    if "command" not in cfg:
        raise SchemaError(f"Service '{name}' is missing required field 'command'.")
    command = cfg["command"]
    if not isinstance(command, list) or len(command) == 0:
        raise SchemaError(f"Service '{name}': 'command' must be a non-empty list.")
    if not all(isinstance(c, str) for c in command):
        raise SchemaError(f"Service '{name}': all 'command' entries must be strings.")

    # dependencies — optional, list of non-empty strings
    dependencies = cfg.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise SchemaError(f"Service '{name}': 'dependencies' must be a list.")
    if not all(isinstance(d, str) and d for d in dependencies):
        raise SchemaError(
            f"Service '{name}': all 'dependencies' entries must be non-empty strings."
        )

    # startup_timeout — optional, positive number
    startup_timeout = cfg.get("startup_timeout", 5.0)
    if not isinstance(startup_timeout, (int, float)) or startup_timeout <= 0:
        raise SchemaError(
            f"Service '{name}': 'startup_timeout' must be a positive number."
        )

    # shutdown_timeout — optional, positive number
    shutdown_timeout = cfg.get("shutdown_timeout", 5.0)
    if not isinstance(shutdown_timeout, (int, float)) or shutdown_timeout <= 0:
        raise SchemaError(
            f"Service '{name}': 'shutdown_timeout' must be a positive number."
        )

    # readiness_check — optional, non-empty list of strings or null
    readiness_check = cfg.get("readiness_check", None)
    if readiness_check is not None:
        if not isinstance(readiness_check, list) or len(readiness_check) == 0:
            raise SchemaError(
                f"Service '{name}': 'readiness_check' must be a non-empty list or null."
            )
        if not all(isinstance(c, str) for c in readiness_check):
            raise SchemaError(
                f"Service '{name}': all 'readiness_check' entries must be strings."
            )

    return ServiceConfig(
        name=name,
        command=command,
        dependencies=dependencies,
        startup_timeout=float(startup_timeout),
        shutdown_timeout=float(shutdown_timeout),
        readiness_check=readiness_check,
    )


def _validate_dependency_references(services: list[ServiceConfig]) -> None:
    known = {s.name for s in services}
    for s in services:
        for dep in s.dependencies:
            if dep not in known:
                raise SchemaError(
                    f"Service '{s.name}' depends on '{dep}', which is not defined."
                )
            if dep == s.name:
                raise SchemaError(f"Service '{s.name}' cannot depend on itself.")
