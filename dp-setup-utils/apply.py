"""Deploya il data product su CDE con la CLI cde: python-env, resource, job Spark e DAG. Le DDL restano manuali.

Uso: python dp-setup-utils/apply.py <env> [--plan], dopo `make render`. Con --plan stampa i comandi senza eseguirli.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import render
import yaml

SPEC_KEYS = {
    "name",
    "type",
    "applicationFile",
    "pyFiles",
    "mountResources",
    "pythonEnvResource",
    "env",
    "workloadCredentials",
    "args",
    "sizing",
}
WAIT = "attendi"
READY_MINUTES = 30
STATE = re.compile(r"with (\w+) status", re.IGNORECASE)


def _flag(key: str) -> str:
    return "--" + re.sub(r"(?<!^)(?=[A-Z])", "-", key).lower()


def _rendered(env: str, path: Path) -> str:
    return f"dist/{env}/{path.relative_to(render.ROOT).as_posix()}"


def spark_job(spec: dict, create: bool) -> list[str]:
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise ValueError(f"{spec.get('name')}: campi che il deploy non sa tradurre: {sorted(unknown)}")
    cmd = ["cde", "job", "create" if create else "update", "--name", spec["name"]]
    if create:
        cmd += ["--type", spec["type"]]
    cmd += ["--application-file", spec["applicationFile"]]
    for py_file in spec.get("pyFiles", []):
        cmd += ["--py-file", py_file]
    for index, resource in enumerate(spec.get("mountResources", []), start=1):
        cmd += [f"--mount-{index}-resource", resource]
    if "pythonEnvResource" in spec:
        cmd += ["--python-env-resource-name", spec["pythonEnvResource"]]
    for key, value in spec.get("env", {}).items():
        cmd += ["--conf", f"spark.kubernetes.driverEnv.{key}={value}", "--conf", f"spark.executorEnv.{key}={value}"]
    for credential in spec.get("workloadCredentials", []):
        cmd += ["--workload-credential", credential]
    for key, value in spec.get("sizing", {}).items():
        cmd += [_flag(key), str(value)]
    for arg in spec.get("args", []):
        cmd += ["--arg", arg]
    return cmd


def airflow_job(name: str, resource: str) -> list[str]:
    # Niente opzioni di schedule, pausa compresa: per un job Airflow la CLI le rifiuta, stanno nel DAG.
    cmd = ["cde", "job", "create", "--name", name, "--type", "airflow", "--dag-file", f"{name}.py"]
    return cmd + ["--mount-1-resource", resource]


def requirements(job: str) -> Path | None:
    path = render.ROOT / "data" / "jobs" / job / "requirements.txt"
    return path if path.is_file() else None


def python_env(dp: str, job: str, env: str, path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:8]
    return f"{dp}-{job}-pyenv-{env}-{digest}"


def commands(env: str, wheels: dict[str, str], exists: Callable[[str, str], bool]) -> list[list[str]]:
    ctx = render.context(env)
    dp = ctx["dp"]["name"]
    cmds: list[list[str]] = []

    def resource(name: str) -> None:
        if not exists("resource", name):
            cmds.append(["cde", "resource", "create", "--name", name, "--type", "files"])

    def upload(name: str, path: str, *extra: str) -> None:
        cmds.append(["cde", "resource", "upload", "--name", name, "--local-path", path, *extra])

    for job in render.jobs():
        name = f"{dp}-{job}-{env}"
        resource(name)
        upload(name, f"dist/wheels/{job}/{wheels[job]}")
        upload(name, f"data/jobs/{job}/launcher.py")
        pyenv = None
        if reqs := requirements(job):
            # Una python-env non si modifica: requirements.txt cambiato, nome nuovo.
            pyenv = python_env(dp, job, env, reqs)
            if not exists("resource", pyenv):
                create = ["cde", "resource", "create", "--name", pyenv, "--type", "python-env"]
                cmds.append([*create, "--python-version", "python3"])
                upload(pyenv, f"data/jobs/{job}/requirements.txt")
            cmds.append([WAIT, pyenv])
        for path in sorted((render.ROOT / "data" / "jobs" / job / "cde_cfg").glob("*.yaml")):
            spec = yaml.safe_load(render.render_file(path, env, wheels))
            if pyenv and "pythonEnvResource" in spec:
                hint = "la crea il deploy da requirements.txt: togli pythonEnvResource dalla definizione"
                raise ValueError(f"{spec['name']}: {hint}")
            if pyenv:
                spec["pythonEnvResource"] = pyenv
            cmds.append(spark_job(spec, create=not exists("job", spec["name"])))

    dags = [path for path in render.deployable_files() if path.parent.name == "dags"]
    if dags:
        dags_resource = f"{dp}-dags-{env}"
        resource(dags_resource)
        for path in dags:
            dag = f"{dp}-{path.stem.removeprefix('dag_')}-{env}"
            upload(dags_resource, _rendered(env, path), "--resource-path", f"{dag}.py")
            if not exists("job", dag):
                cmds.append(airflow_job(dag, dags_resource))
    return cmds


def ddl(env: str) -> list[str]:
    return [_rendered(env, path) for path in render.deployable_files() if path.suffix == ".sql"]


def _succeeds(*args: str) -> bool:
    return subprocess.run(["cde", *args], cwd=render.ROOT, capture_output=True).returncode == 0


def _exists(kind: str, name: str) -> bool:
    return _succeeds(kind, "describe", "--name", name)


def wait_ready(name: str) -> None:
    started = time.monotonic()
    check = f"cde resource list-events --name {name}"
    while True:
        events = subprocess.run(shlex.split(check), cwd=render.ROOT, capture_output=True, text=True)
        states = STATE.findall(events.stdout or "")
        state = states[-1].lower() if states else ""
        if state == "ready":
            print()
            return
        if state in ("failed", "error"):
            sys.exit(f"\nla build della python-env è fallita ({check}): correggi requirements.txt e rilancia il deploy")
        if time.monotonic() - started > READY_MINUTES * 60:
            sys.exit(f"\nla python-env non è pronta dopo {READY_MINUTES} minuti: controlla con {check}, poi rilancia")
        print(".", end="", flush=True)
        time.sleep(15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env", choices=render.envs())
    parser.add_argument("--plan", action="store_true", help="stampa i comandi senza eseguirli")
    args = parser.parse_args()
    if shutil.which("cde") is None:
        sys.exit("CLI cde non trovata: make cde-setup spiega come installarla")
    if not _succeeds("job", "list"):
        sys.exit("la CLI cde non raggiunge il vcluster: make cde-setup mostra l'errore e cosa controllare")
    print("DDL da applicare a mano prima del deploy, se non lo sono già:")
    for path in ddl(args.env):
        print(f"  {path}")
    try:
        cmds = commands(args.env, render.built_wheels(), _exists)
    except ValueError as error:
        sys.exit(str(error))
    for cmd in cmds:
        if cmd[0] == WAIT:
            print(f"# attende che la python-env {cmd[1]} sia pronta: la build può richiedere qualche minuto")
            if not args.plan:
                wait_ready(cmd[1])
            continue
        print(shlex.join(cmd))
        if not args.plan and subprocess.run(cmd, cwd=render.ROOT).returncode != 0:
            sys.exit(f"comando fallito: {shlex.join(cmd)}")


if __name__ == "__main__":
    main()
