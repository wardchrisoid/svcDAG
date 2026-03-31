"""
Debug utility: load a svcdag JSON config and print the startup order
without starting any processes.

Usage:
    python show_order.py tests/configs/simple.json
"""

import json
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent / "src"))

from svcdag.exceptions import CycleDetectedError, SchemaError
from svcdag.graph import build_levels, execution_order
from svcdag.loader import load


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python show_order.py <config.json>")
        sys.exit(1)

    config_path = sys.argv[1]

    try:
        services = load(config_path)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Failed to load config: {e}")
        sys.exit(1)
    except SchemaError as e:
        print(f"Schema error: {e}")
        sys.exit(1)

    try:
        levels = build_levels(services)
    except CycleDetectedError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Config: {config_path}")
    print(f"Services: {len(services)}\n")

    print("=== Startup order (by level) ===")
    for i, level in enumerate(levels):
        prefix = f"  Level {i}:"
        for j, name in enumerate(level):
            svc = next(s for s in services if s.name == name)
            deps = f"  (deps: {', '.join(svc.dependencies)})" if svc.dependencies else ""
            if j == 0:
                print(f"{prefix} {name}{deps}")
            else:
                print(f"{'':>{len(prefix)}} {name}{deps}")

    print()
    order = execution_order(services)
    print("=== Flat serial order ===")
    for i, name in enumerate(order, 1):
        print(f"  {i}. {name}")

    print()
    print("=== Shutdown order (reverse) ===")
    for i, name in enumerate(reversed(order), 1):
        print(f"  {i}. {name}")


if __name__ == "__main__":
    main()
