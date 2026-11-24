from __future__ import annotations

import re

import pytest
import render
import yaml

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
QUALITY_KEYS = {
    "dqJob",
    "database",
    "dlLayer",
    "contracts",
    "schedule",
    "pool",
    "watermarkColumn",
    "sodaCloudEnabled",
    "primaryKeys",
    "xrefDatasets",
}


def test_job_completi():
    for job in render.jobs():
        folder = render.ROOT / "data" / "jobs" / job
        assert IDENTIFIER.match(job), f"data/jobs/{job}: il nome della cartella è anche il nome del package"
        for required in ("launcher.py", "pyproject.toml", f"src/{job}/__init__.py"):
            assert (folder / required).is_file(), f"data/jobs/{job}: manca {required}"
        assert list((folder / "cde_cfg").glob("*.yaml")), f"data/jobs/{job}: manca la definizione in cde_cfg/"


@pytest.mark.skipif(not (render.ROOT / "quality").is_dir(), reason="data product senza Modulo Quality")
def test_config_quality(env):
    path = render.ROOT / "quality" / "config" / f"{env}.yaml"
    assert path.is_file(), f"manca quality/config/{env}.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    unexpected, missing = sorted(set(cfg) - QUALITY_KEYS), sorted(QUALITY_KEYS - set(cfg))
    assert not unexpected and not missing, f"{path.name}: campi inattesi {unexpected}, mancanti {missing}"
    assert IDENTIFIER.match(cfg["dlLayer"]), f"dlLayer finisce nei nomi delle tabelle di quality: {cfg['dlLayer']}"
    assert "/" in cfg["contracts"]["repository"], "contracts.repository: formato atteso owner/repo"
    assert isinstance(cfg["sodaCloudEnabled"], bool), "sodaCloudEnabled va scritto true o false"
    ports = {port["name"] for port in render.context(env)["dp"]["outputPorts"]}
    for key in ("primaryKeys", "xrefDatasets"):
        unknown = set(cfg[key]) - ports
        assert not unknown, f"{path.name}: {key} cita porte che non sono output port: {sorted(unknown)}"
