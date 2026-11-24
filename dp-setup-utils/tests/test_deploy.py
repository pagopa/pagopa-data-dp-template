from __future__ import annotations

import re
import shlex
import subprocess

import apply
import pytest
import render
import yaml

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
DAG_FILES = [path for path in render.deployable_files() if path.parent.name == "dags"]


def _env_file(env: str) -> dict:
    return yaml.safe_load((render.ROOT / "envs" / f"{env}.yaml").read_text(encoding="utf-8"))


def test_file_di_ambiente(env):
    cfg = _env_file(env)
    assert cfg["name"] == env, f"{env}.yaml: name deve essere {env}, il suffisso dei nomi su CDE"
    for key in ("data", "inputs"):
        assert IDENTIFIER.match(cfg["databases"][key]), f"{env}.yaml: databases.{key} finisce nelle DDL e nei job"
    assert isinstance(cfg["dags"]["schedulePaused"], bool), f"{env}.yaml: dags.schedulePaused va scritto true o false"
    assert isinstance(cfg["credentials"], list), f"{env}.yaml: credentials è una lista, anche vuota"


def test_database_distinti_per_ambiente():
    databases = {env: _env_file(env)["databases"]["data"] for env in render.envs()}
    assert len(set(databases.values())) == len(databases), f"test e prod condividono il Data Lake: {databases}"


def test_traduzione_della_definizione():
    spec = {
        "name": "dp-x-y-test",
        "type": "spark",
        "applicationFile": "launcher.py",
        "pyFiles": ["y.whl"],
        "mountResources": ["dp-x-y-test"],
        "env": {"ENV": "test"},
        "workloadCredentials": ["github-token"],
        "args": ["--database=db"],
        "sizing": {"driverCores": 1, "maxExecutors": 4},
    }
    assert shlex.join(apply.spark_job(spec, create=True)) == (
        "cde job create --name dp-x-y-test --type spark --application-file launcher.py --py-file y.whl"
        " --mount-1-resource dp-x-y-test"
        " --conf spark.kubernetes.driverEnv.ENV=test --conf spark.executorEnv.ENV=test"
        " --workload-credential github-token --driver-cores 1 --max-executors 4 --arg --database=db"
    )
    assert apply.spark_job(spec, create=False)[:5] == ["cde", "job", "update", "--name", "dp-x-y-test"]
    assert "--type" not in apply.spark_job(spec, create=False)
    with pytest.raises(ValueError, match="sizng"):
        apply.spark_job({**spec, "sizng": {}}, create=True)


def test_primo_deploy(env, wheels):
    ctx = render.context(env)
    dp = ctx["dp"]["name"]
    cmds = [shlex.join(cmd) for cmd in apply.commands(env, wheels, lambda kind, name: False)]
    for job in render.jobs():
        name = f"{dp}-{job}-{env}"
        assert f"cde resource create --name {name} --type files" in cmds
        assert f"cde resource upload --name {name} --local-path dist/wheels/{job}/{wheels[job]}" in cmds
        assert f"cde resource upload --name {name} --local-path data/jobs/{job}/launcher.py" in cmds
        assert any(cmd.startswith(f"cde job create --name {name} --type spark ") for cmd in cmds), name
    for path in DAG_FILES:
        dag = f"{dp}-{path.stem.removeprefix('dag_')}-{env}"
        rendered = f"dist/{env}/{path.relative_to(render.ROOT).as_posix()}"
        assert f"cde resource upload --name {dp}-dags-{env} --local-path {rendered} --resource-path {dag}.py" in cmds
        create = f"cde job create --name {dag} --type airflow --dag-file {dag}.py"
        assert f"{create} --mount-1-resource {dp}-dags-{env}" in cmds
    assert not [cmd for cmd in cmds if "--schedule" in cmd], "per i job Airflow la CLI rifiuta lo schedule: sta nel DAG"


def test_deploy_successivo(env, wheels):
    cmds = apply.commands(env, wheels, lambda kind, name: True)
    assert not [cmd for cmd in cmds if "create" in cmd], "se tutto esiste già su CDE il deploy non crea nulla"
    updates = [cmd for cmd in cmds if cmd[:3] == ["cde", "job", "update"]]
    assert len(updates) == len(render.jobs()), "ogni job Spark si aggiorna a ogni deploy"


@pytest.fixture
def cde(monkeypatch, wheels):
    executed: list[list[str]] = []

    def run(cmd, **kwargs):
        executed.append(cmd)
        # Senza "ready", con un requirements.txt nel data product il deploy aspetterebbe la python-env 30 minuti.
        stdout = "marking resource with ready status" if "list-events" in cmd else ""
        return subprocess.CompletedProcess(cmd, 1 if "describe" in cmd else 0, stdout)

    monkeypatch.setattr(apply.shutil, "which", lambda name: name)
    monkeypatch.setattr(apply.subprocess, "run", run)
    monkeypatch.setattr(apply.render, "built_wheels", lambda: wheels)
    return executed


def _changes(executed: list[list[str]]) -> list[list[str]]:
    reads = ("describe", "list-events")
    return [cmd for cmd in executed if cmd[1:3] != ["job", "list"] and not any(read in cmd for read in reads)]


@pytest.mark.parametrize("plan", [True, False])
def test_plan_e_deploy(env, wheels, cde, monkeypatch, capsys, plan):
    monkeypatch.setattr("sys.argv", ["apply.py", env, *(["--plan"] if plan else [])])
    apply.main()
    commands = apply.commands(env, wheels, lambda kind, name: False)
    expected = [cmd for cmd in commands if cmd[0] != apply.WAIT]
    waits = [cmd[1] for cmd in commands if cmd[0] == apply.WAIT]
    assert _changes(cde) == ([] if plan else expected)
    checked = [cmd[cmd.index("--name") + 1] for cmd in cde if "list-events" in cmd]
    assert checked == ([] if plan else waits), "il deploy aspetta ogni python-env prima del suo job, il plan no"
    printed = capsys.readouterr().out
    assert all(shlex.join(cmd) in printed for cmd in expected)
    assert all(f"python-env {name} sia pronta" in printed for name in waits)


@pytest.fixture
def requirements(tmp_path, monkeypatch):
    """Un requirements.txt nel primo job, senza toccare il repo."""
    if not render.jobs():
        pytest.skip("data product senza Modulo Dati")
    job, path = render.jobs()[0], tmp_path / "requirements.txt"
    path.write_text("requests==2.32.3\n", encoding="utf-8")
    monkeypatch.setattr(apply, "requirements", lambda name: path if name == job else None)
    return job, path


def test_python_env_da_requirements(env, wheels, requirements):
    job, path = requirements
    dp = render.context(env)["dp"]["name"]
    pyenv = apply.python_env(dp, job, env, path)
    assert re.fullmatch(rf"{dp}-{job}-pyenv-{env}-[0-9a-f]{{8}}", pyenv)
    first = apply.commands(env, wheels, lambda kind, name: False)
    create = ["cde", "resource", "create", "--name", pyenv, "--type", "python-env", "--python-version", "python3"]
    upload = ["cde", "resource", "upload", "--name", pyenv, "--local-path", f"data/jobs/{job}/requirements.txt"]
    spark_job = next(cmd for cmd in first if cmd[:5] == ["cde", "job", "create", "--name", f"{dp}-{job}-{env}"])
    assert first.index(create) < first.index(upload) < first.index([apply.WAIT, pyenv]) < first.index(spark_job)
    assert spark_job[spark_job.index("--python-env-resource-name") + 1] == pyenv
    again = apply.commands(env, wheels, lambda kind, name: True)
    assert create not in again and [apply.WAIT, pyenv] in again, "una python-env che c'è già si controlla soltanto"
    path.write_text("requests==2.32.4\n", encoding="utf-8")
    assert apply.python_env(dp, job, env, path) != pyenv, "requirements.txt cambiato, python-env nuova"


def test_python_env_dichiarata_anche_a_mano(env, wheels, requirements, monkeypatch):
    render_file = apply.render.render_file
    monkeypatch.setattr(apply.render, "render_file", lambda *args: render_file(*args) + "pythonEnvResource: a-mano\n")
    with pytest.raises(ValueError, match="togli pythonEnvResource"):
        apply.commands(env, wheels, lambda kind, name: False)


def test_plan_non_aspetta_la_python_env(env, cde, requirements, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["apply.py", env, "--plan"])
    apply.main()
    assert "# attende che la python-env" in capsys.readouterr().out
    assert not [cmd for cmd in cde if "list-events" in cmd]


def test_attende_che_la_python_env_sia_pronta(monkeypatch):
    def events(*outputs):
        queue = iter(outputs)

        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, next(queue))

        monkeypatch.setattr(apply.subprocess, "run", run)

    monkeypatch.setattr(apply.time, "sleep", lambda seconds: None)
    events("", "marking resource with building status", "marking resource with ready status")
    apply.wait_ready("pyenv")
    events("marking resource with failed status")
    with pytest.raises(SystemExit, match="fallita"):
        apply.wait_ready("pyenv")
