from svcdag.exceptions import CycleDetectedError
from svcdag.models import ServiceConfig


def build_levels(services: list[ServiceConfig]) -> list[list[str]]:
    """
    Topological sort via Kahn's algorithm.

    Returns a list of levels, where each level is a sorted list of service
    names that can be started after all previous levels are running.
    Services with no dependencies are in level 0.

    Raises CycleDetectedError if a cycle is detected.
    """
    all_names = {s.name for s in services}
    in_degree: dict[str, int] = {s.name: 0 for s in services}
    # dependents[x] = list of services that depend on x (i.e. x must start first)
    dependents: dict[str, list[str]] = {s.name: [] for s in services}

    for s in services:
        for dep in s.dependencies:
            dependents[dep].append(s.name)
            in_degree[s.name] += 1

    # Seed with all nodes that have no dependencies
    current_level = sorted(name for name, deg in in_degree.items() if deg == 0)
    levels: list[list[str]] = []
    visited: set[str] = set()

    while current_level:
        levels.append(current_level)
        next_level = []
        for name in current_level:
            visited.add(name)
            for dependent in dependents[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_level.append(dependent)
        current_level = sorted(next_level)

    if len(visited) != len(all_names):
        # Some nodes were never reached — they form a cycle
        cycle_nodes = sorted(all_names - visited)
        raise CycleDetectedError(cycle_nodes)

    return levels


def execution_order(services: list[ServiceConfig]) -> list[str]:
    """
    Returns the flat, sequential startup order for all services.
    Useful for debug inspection without actually starting anything.
    """
    levels = build_levels(services)
    return [name for level in levels for name in level]
