from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dp-setup-utils"))

import render  # noqa: E402

FAKE_WHEELS = {job: f"{job}-0.0.0-py3-none-any.whl" for job in render.jobs()}

# Il CdeRunJobOperator del provider Cloudera legge questa connection quando il DAG viene caricato.
os.environ.setdefault("AIRFLOW_CONN_CDE_RUNTIME_API", "http://dummy")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "env" in metafunc.fixturenames:
        metafunc.parametrize("env", render.envs())


@pytest.fixture
def wheels() -> dict[str, str]:
    return FAKE_WHEELS


@pytest.fixture
def render_file():
    def _render_file(path: Path, env: str) -> str:
        return render.render_file(path, env, FAKE_WHEELS)

    return _render_file


def _install_cde_operator_stub() -> None:
    """Registra un finto CdeRunJobOperator quando Airflow c'è ma il provider Cloudera no."""
    try:
        if importlib.util.find_spec("cloudera.airflow.providers.operators.cde") is not None:
            return
    except ModuleNotFoundError:
        pass
    try:
        from airflow.models import BaseOperator
    except ImportError:
        return

    class CdeRunJobOperator(BaseOperator):
        template_fields = ("variables", "overrides")

        def __init__(self, job_name, variables=None, overrides=None, **kwargs):
            super().__init__(**kwargs)
            self.job_name = job_name
            self.variables = variables or {}
            self.overrides = overrides or {}

    for name in ("cloudera", "cloudera.airflow", "cloudera.airflow.providers", "cloudera.airflow.providers.operators"):
        sys.modules.setdefault(name, types.ModuleType(name))
    stub = types.ModuleType("cloudera.airflow.providers.operators.cde")
    stub.CdeRunJobOperator = CdeRunJobOperator
    sys.modules[stub.__name__] = stub


_install_cde_operator_stub()
