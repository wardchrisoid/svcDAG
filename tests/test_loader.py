import json
import os
import tempfile

import pytest

from svcdag.exceptions import SchemaError
from svcdag.loader import load
from svcdag.models import ServiceConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_config(data: dict) -> str:
    """Write a dict as a temporary JSON file and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, f)
    f.close()
    return f.name


def load_temp(data: dict) -> list[ServiceConfig]:
    path = write_config(data)
    try:
        return load(path)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Valid configs
# ---------------------------------------------------------------------------

class TestValidConfigs:
    def test_simple_config(self):
        svcs = load("tests/configs/simple.json")
        names = {s.name for s in svcs}
        assert names == {"database", "cache", "api_server", "worker"}

    def test_diamond_config(self):
        svcs = load("tests/configs/diamond.json")
        names = {s.name for s in svcs}
        assert names == {"database", "auth_service", "user_service", "api_gateway"}

    def test_no_deps_config(self):
        svcs = load("tests/configs/no_deps.json")
        assert all(s.dependencies == [] for s in svcs)

    def test_cycle_config_loads(self):
        # Cycle detection is the graph's job; loader should accept this fine
        svcs = load("tests/configs/cycle.json")
        assert len(svcs) == 3

    def test_defaults_applied(self):
        svcs = load_temp({
            "services": {
                "db": {"command": ["./db"]}
            }
        })
        svc = svcs[0]
        assert svc.startup_timeout == 5.0
        assert svc.shutdown_timeout == 5.0
        assert svc.dependencies == []
        assert svc.readiness_check is None

    def test_custom_timeouts(self):
        svcs = load_temp({
            "services": {
                "db": {
                    "command": ["./db"],
                    "startup_timeout": 10.0,
                    "shutdown_timeout": 3.0,
                }
            }
        })
        svc = svcs[0]
        assert svc.startup_timeout == 10.0
        assert svc.shutdown_timeout == 3.0

    def test_readiness_check_parsed(self):
        svcs = load_temp({
            "services": {
                "db": {
                    "command": ["./db"],
                    "readiness_check": ["./check_db"],
                }
            }
        })
        assert svcs[0].readiness_check == ["./check_db"]

    def test_integer_timeout_coerced_to_float(self):
        svcs = load_temp({
            "services": {
                "db": {"command": ["./db"], "startup_timeout": 10}
            }
        })
        assert isinstance(svcs[0].startup_timeout, float)

    def test_multi_word_command(self):
        svcs = load_temp({
            "services": {
                "db": {"command": ["./db", "--port", "5432"]}
            }
        })
        assert svcs[0].command == ["./db", "--port", "5432"]


# ---------------------------------------------------------------------------
# Schema errors — root level
# ---------------------------------------------------------------------------

class TestRootSchemaErrors:
    def test_missing_services_key(self):
        with pytest.raises(SchemaError, match="'services'"):
            load_temp({"wrong_key": {}})

    def test_services_not_an_object(self):
        with pytest.raises(SchemaError, match="'services'"):
            load_temp({"services": ["db"]})

    def test_empty_services(self):
        with pytest.raises(SchemaError, match="at least one"):
            load_temp({"services": {}})

    def test_root_not_an_object(self):
        path = write_config([])  # JSON array at root
        try:
            with pytest.raises(SchemaError, match="root"):
                load(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Schema errors — per service
# ---------------------------------------------------------------------------

class TestServiceSchemaErrors:
    def test_missing_command(self):
        with pytest.raises(SchemaError, match="command"):
            load_temp({"services": {"db": {"dependencies": []}}})

    def test_empty_command(self):
        with pytest.raises(SchemaError, match="non-empty"):
            load_temp({"services": {"db": {"command": []}}})

    def test_command_not_a_list(self):
        with pytest.raises(SchemaError, match="non-empty list"):
            load_temp({"services": {"db": {"command": "./db"}}})

    def test_command_entries_not_strings(self):
        with pytest.raises(SchemaError, match="strings"):
            load_temp({"services": {"db": {"command": [1, 2, 3]}}})

    def test_dependencies_not_a_list(self):
        with pytest.raises(SchemaError, match="dependencies"):
            load_temp({"services": {"db": {"command": ["./db"], "dependencies": "other"}}})

    def test_startup_timeout_negative(self):
        with pytest.raises(SchemaError, match="startup_timeout"):
            load_temp({"services": {"db": {"command": ["./db"], "startup_timeout": -1}}})

    def test_startup_timeout_zero(self):
        with pytest.raises(SchemaError, match="startup_timeout"):
            load_temp({"services": {"db": {"command": ["./db"], "startup_timeout": 0}}})

    def test_shutdown_timeout_negative(self):
        with pytest.raises(SchemaError, match="shutdown_timeout"):
            load_temp({"services": {"db": {"command": ["./db"], "shutdown_timeout": -5}}})

    def test_readiness_check_empty_list(self):
        with pytest.raises(SchemaError, match="readiness_check"):
            load_temp({"services": {"db": {"command": ["./db"], "readiness_check": []}}})

    def test_readiness_check_not_strings(self):
        with pytest.raises(SchemaError, match="strings"):
            load_temp({"services": {"db": {"command": ["./db"], "readiness_check": [1]}}})

    def test_service_body_not_object(self):
        with pytest.raises(SchemaError):
            load_temp({"services": {"db": "bad"}})


# ---------------------------------------------------------------------------
# Dependency reference errors
# ---------------------------------------------------------------------------

class TestDependencyReferenceErrors:
    def test_unknown_dependency(self):
        with pytest.raises(SchemaError, match="not defined"):
            load_temp({
                "services": {
                    "api": {"command": ["./api"], "dependencies": ["missing_service"]}
                }
            })

    def test_self_dependency(self):
        with pytest.raises(SchemaError, match="cannot depend on itself"):
            load_temp({
                "services": {
                    "db": {"command": ["./db"], "dependencies": ["db"]}
                }
            })
