from dataclasses import dataclass, field
from enum import Enum


@dataclass
class ServiceConfig:
    name: str
    command: list[str]
    dependencies: list[str] = field(default_factory=list)
    startup_timeout: float = 5.0
    shutdown_timeout: float = 5.0
    readiness_check: list[str] | None = None


@dataclass
class LifecycleResult:
    success: bool
    started: list[str] = field(default_factory=list)
    failed: str | None = None
    never_started: list[str] = field(default_factory=list)
    force_killed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class OrchestratorState(Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
