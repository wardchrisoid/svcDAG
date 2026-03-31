class SchemaError(Exception):
    """Raised when the JSON config fails validation."""


class CycleDetectedError(Exception):
    """Raised when a dependency cycle is found in the service graph."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(
            f"Dependency cycle detected. Services involved: {', '.join(cycle)}"
        )


class StartupError(Exception):
    """Raised when a service fails to start."""

    def __init__(
        self,
        failed_service: str,
        never_started: list[str],
        message: str,
    ) -> None:
        self.failed_service = failed_service
        self.never_started = never_started
        super().__init__(
            f"Service '{failed_service}' failed to start. "
            f"Never started: {never_started}. {message}"
        )
