from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

import new_job
import pytest
import render
import setup
import yaml

MODELS = [job for job in render.jobs() if job != new_job.EXPORT_JOB]
pytestmark = pytest.mark.skipif(not MODELS, reason="data product senza job da cui partire")
DESCRIPTOR = yaml.safe_load((render.ROOT / "data-product.yaml").read_text(encoding="utf-8"))
IS_BLUEPRINT = DESCRIPTOR["name"] == setup.BLUEPRINT


@pytest.fixture
def source():
    return MODELS[0]


@pytest.fixture
def jobs_dir(tmp_path, source):
    shutil.copytree(render.ROOT / "data" / "jobs" / source, tmp_path / source, ignore=new_job.BUILD_ARTIFACTS)
    return tmp_path


def _module_file(folder, module: str):
    return folder / "src" / f"{module.replace('.', '/')}.py"


@pytest.mark.parametrize(("spark", "inputs"), [(True, ["raw_a", "raw_b"]), (True, []), (False, ["raw_a"])])
def test_job_nuovo(jobs_dir, source, spark, inputs):
    copied = jobs_dir / source
    (copied / "src" / source / "logica.py").write_text("VALORE = 1\n", encoding="utf-8")
    (copied / "tests" / "unit" / "test_logica.py").write_text(f"from {source} import logica\n", encoding="utf-8")
    (copied / "requirements.txt").write_text("requests\n", encoding="utf-8")
    folder = new_job.new_job("nuovo_job", source, jobs_dir, spark, inputs)
    files = {path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8") for path in folder.rglob("*.*")}
    assert "src/nuovo_job/__init__.py" in files and "src/nuovo_job/common/config/base.py" in files
    assert [path for path in files if source in path] == []
    assert [path for path, text in files.items() if f"{source}." in text] == []
    not_copied = {"src/nuovo_job/logica.py", "tests/unit/test_logica.py", "requirements.txt"}
    assert not not_copied & set(files), "codice, test e dipendenze del job di partenza non si copiano"
    entrypoint = files["src/nuovo_job/entrypoints/run_nuovo_job.py"]
    assert entrypoint == new_job.entrypoint("nuovo_job", spark, inputs)
    assert ("SparkSession" in entrypoint) == spark
    assert ("INPUT_TABLES = " in entrypoint) == spark
    assert all((f'    "{name}",\n' in entrypoint) == spark for name in inputs), "con Spark legge le input port"
    assert re.search(r'^name = "nuovo_job"$', files["pyproject.toml"], re.MULTILINE)
    for module in re.findall(r'= "([\w.]+):\w+"', files["pyproject.toml"]):
        assert _module_file(folder, module).is_file(), f"[project.scripts] punta a {module}, che non c'è"
    for module in re.findall(r"^from ([\w.]+) import", files["launcher.py"], re.MULTILINE):
        assert _module_file(folder, module).is_file(), f"launcher.py importa {module}, che non c'è"
    tests = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    result = subprocess.run(tests, cwd=folder, env={**os.environ, "PYTHONPATH": "src"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-4000:]


@pytest.mark.parametrize(("name", "error"), [("Nuovo", "minuscole"), ("json", "modulo Python")])
def test_nomi_rifiutati(jobs_dir, source, name, error):
    with pytest.raises(ValueError, match=error):
        new_job.new_job(name, source, jobs_dir)


def test_il_job_export_non_e_un_modello(jobs_dir):
    with pytest.raises(ValueError, match="job di export"):
        new_job.new_job("nuovo_job", new_job.EXPORT_JOB, jobs_dir)


def test_job_esistente(jobs_dir, source):
    with pytest.raises(ValueError, match="già un job"):
        new_job.new_job(source, source, jobs_dir)


def test_si_o_no():
    assert [new_job.yes_no(raw) for raw in ("s", "Sì", "1", "n", "no", "0")] == [True] * 3 + [False] * 3
    with pytest.raises(ValueError, match="s o n"):
        new_job.yes_no("forse")


@pytest.mark.skipif(not IS_BLUEPRINT, reason="solo nella blueprint: nei data product il codice dei job è dell'utente")
def test_esempi_della_blueprint_uguali_a_un_job_nuovo():
    for job in MODELS:
        folder = render.ROOT / "data" / "jobs" / job
        entrypoint = folder / "src" / job / "entrypoints" / f"run_{job}.py"
        expected = new_job.entrypoint(job, spark=True, inputs=new_job.input_ports(render.ROOT))
        assert entrypoint.read_text(encoding="utf-8") == expected, job
        smoke_test = folder / "tests" / "unit" / "test_smoke.py"
        assert smoke_test.read_text(encoding="utf-8") == new_job.smoke_test(job, spark=True), job
