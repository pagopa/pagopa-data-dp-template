from __future__ import annotations

import importlib.util

import apply
import pytest
import render
import yaml

JOB_SPECS = [path for path in render.deployable_files() if path.parent.name == "cde_cfg"]
DAG_FILES = [path for path in render.deployable_files() if path.suffix == ".py"]
PIPELINE_DAGS = [path for path in DAG_FILES if path.relative_to(render.ROOT).parts[0] == "data"]


def test_file_deployabili_risolti(env, render_file):
    for path in render.deployable_files():
        render_file(path, env)


def test_job_validi(env, render_file):
    dp_name = render.context(env)["dp"]["name"]
    names = []
    for path in JOB_SPECS:
        spec = yaml.safe_load(render_file(path, env))
        name = f"{dp_name}-{render.job_of(path)}-{env}"
        assert spec["name"] == name, f"{path.name}: atteso {name}, cioè <name>-<job>-<env>"
        assert name in spec["mountResources"], f"{path.name}: deve montare {name}, dove vanno wheel e launcher"
        unknown = set(spec) - apply.SPEC_KEYS
        assert not unknown, f"{path.name}: campi che il deploy non sa tradurre: {sorted(unknown)}"
        names.append(name)
    assert len(names) == len(set(names)), f"una sola definizione per job: {names}"


def test_todo_elencati():
    rendered = {render.ROOT / "data" / "ddl" / "x.sql": "CREATE TABLE t (\n    -- TODO: colonne\n);\n"}
    assert render.todos(rendered) == ["data/ddl/x.sql:2: -- TODO: colonne"]


def test_dag_sintatticamente_validi(env, render_file):
    for path in DAG_FILES:
        compile(render_file(path, env), str(path), "exec")


def _load_dags(path, env, render_file, tmp_path) -> list:
    from airflow.models import DAG

    rendered = tmp_path / path.name
    rendered.write_text(render_file(path, env), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(path.stem, rendered)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [value for value in vars(module).values() if isinstance(value, DAG)]


def test_dag_si_caricano(env, render_file, tmp_path):
    pytest.importorskip("airflow")
    dp_name = render.context(env)["dp"]["name"]
    for path in DAG_FILES:
        dag_id = f"{dp_name}-{path.stem.removeprefix('dag_')}-{env}"
        dags = [dag.dag_id for dag in _load_dags(path, env, render_file, tmp_path)]
        assert dags == [dag_id], f"{path.name}: atteso un solo DAG, {dag_id}, che è anche il nome del suo job su CDE"


def test_dag_in_pausa_come_da_ambiente(env, render_file, tmp_path):
    pytest.importorskip("airflow")
    paused = render.context(env)["env"]["dags"]["schedulePaused"]
    for path in DAG_FILES:
        for dag in _load_dags(path, env, render_file, tmp_path):
            assert dag.is_paused_upon_creation is paused, f"{path.name}: la pausa iniziale viene da dags.schedulePaused"


def test_pipeline_lancia_tutti_i_job(env, render_file, tmp_path):
    pytest.importorskip("airflow")
    dp_name = render.context(env)["dp"]["name"]
    jobs = {f"{dp_name}-{job}-{env}" for job in render.jobs()}
    launched = {
        task.job_name
        for path in PIPELINE_DAGS
        for dag in _load_dags(path, env, render_file, tmp_path)
        for task in dag.tasks
        if hasattr(task, "job_name")
    }
    assert launched <= jobs, f"task che lanciano job che non sono in data/jobs/: {sorted(launched - jobs)}"
    assert jobs <= launched, f"job che nessun DAG della pipeline lancia: {sorted(jobs - launched)}"
