"""Crea un job in data/jobs/ con il codice di esempio, copiando da un job esistente solo la struttura.

Uso: python dp-setup-utils/new_job.py <nuovo> --from <job> [--spark s|n]. Dal job di partenza copia pyproject,
definizione su CDE e common/, sostituendone il nome; entrypoint, launcher e test sono quelli di esempio. Con Spark il
job apre una SparkSession, legge le tabelle delle input port di data-product.yaml e le stampa; senza, è lo scheletro
con i parametri comuni. Senza --spark lo chiede.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import re
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
IGNORED = ("*.egg-info", "__pycache__", ".pytest_cache", "build", "dist", ".coverage")
BUILD_ARTIFACTS = shutil.ignore_patterns(*IGNORED)
YES, NO = ("s", "si", "sì", "y", "yes", "1", "true"), ("n", "no", "0", "false")
SPARK_QUESTION = "Partire da un job che apre una sessione Spark, legge le tabelle delle input port e le stampa?"


def yes_no(raw: str) -> bool:
    answer = raw.strip().lower()
    if answer not in YES + NO:
        raise ValueError(f"{raw or 'valore vuoto'}: rispondi s o n")
    return answer in YES


def input_ports(root: Path = ROOT) -> list[str]:
    descriptor = yaml.safe_load((root / "data-product.yaml").read_text(encoding="utf-8"))
    return [port["name"] for port in descriptor.get("inputPorts") or []]


def entrypoint(name: str, spark: bool, inputs: Sequence[str] = ()) -> str:
    pyspark, tables, read = "", "", ""
    todo = "leggere i dati dell'intervallo da args.input_database, o da args.database, e trasformarli."
    if spark:
        pyspark = "from pyspark.sql import SparkSession\n\n"
        listed = "(\n" + "".join(f'    "{table}",\n' for table in inputs) + ")" if inputs else "()"
        comment = "# Le input port di data-product.yaml, che hanno il nome della loro tabella.\n"
        tables = f"{comment}INPUT_TABLES = {listed}\n\n"
        read = (
            f'    spark = SparkSession.builder.appName("{name}").getOrCreate()\n'
            "    if args.input_database and INPUT_TABLES:\n"
            "        for table in INPUT_TABLES:\n"
            '            spark.table(f"{args.input_database}.{table}").show(truncate=False)\n'
            "    else:\n"
            '        spark.sql("SHOW DATABASES").show(truncate=False)\n'
        )
        todo = "al posto dell'esempio, leggere i dati dell'intervallo da args.input_database e trasformarli."
    return f"""from __future__ import annotations

import argparse
import logging

{pyspark}from {name}.common.config import load_config
from {name}.common.logging import setup_logging

logger = logging.getLogger(__name__)

{tables}
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", help="database in cui il job scrive")
    parser.add_argument("--input-database", help="database delle tabelle delle input port")
    parser.add_argument("--from", dest="date_from", help="inizio dell'intervallo da elaborare, ISO 8601")
    parser.add_argument("--to", dest="date_to", help="fine dell'intervallo da elaborare, ISO 8601")
    args = parser.parse_args(argv)
    config = load_config()
    setup_logging(config.log_level)
    logger.info("Avvio in %s con %s", config.env, vars(args))
{read}    # TODO: {todo}
    if not config.write_enabled:
        logger.info("Scrittura disattivata in %s: nessuna tabella modificata", config.env)
        return
    # TODO: scrivere in args.database, in modo che rieseguire lo stesso intervallo non duplichi i dati.


if __name__ == "__main__":
    main()
"""


def smoke_test(name: str, spark: bool) -> str:
    if not spark:
        return f"""import logging

import pytest
from {name}.entrypoints.run_{name} import main


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_main(monkeypatch, caplog, env):
    monkeypatch.setenv("ENV", env)
    with caplog.at_level(logging.INFO):
        main([])
    assert ("Scrittura disattivata" in caplog.text) == (env == "dev")
"""
    return f"""import logging
from types import SimpleNamespace

import pytest
from {name}.entrypoints import run_{name}


class FakeSpark:
    \"\"\"Al posto della SparkSession: i test non avviano Spark, che vuole Java.\"\"\"

    def __init__(self):
        self.read = []

    def table(self, name):
        self.read.append(name)
        return self

    def sql(self, query):
        self.read.append(query)
        return self

    def show(self, **kwargs):
        pass


@pytest.fixture
def spark(monkeypatch):
    fake = FakeSpark()
    builder = SimpleNamespace(appName=lambda name: builder, getOrCreate=lambda: fake)
    monkeypatch.setattr(run_{name}, "SparkSession", SimpleNamespace(builder=builder))
    return fake


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_main(monkeypatch, caplog, spark, env):
    monkeypatch.setenv("ENV", env)
    with caplog.at_level(logging.INFO):
        run_{name}.main([])
    assert spark.read == ["SHOW DATABASES"]
    assert ("Scrittura disattivata" in caplog.text) == (env == "dev")


def test_legge_le_input_port(spark):
    run_{name}.main(["--input-database", "pagopa"])
    tables = [f"pagopa.{{table}}" for table in run_{name}.INPUT_TABLES]
    assert spark.read == (tables or ["SHOW DATABASES"])
"""


def write_example(folder: Path, name: str, spark: bool, inputs: Sequence[str] = ()) -> None:
    files = {
        Path("launcher.py"): f"from {name}.entrypoints.run_{name} import main\n\nmain()\n",
        Path("src", name, "entrypoints", f"run_{name}.py"): entrypoint(name, spark, inputs),
        Path("tests", "unit", "test_smoke.py"): smoke_test(name, spark),
    }
    for path, text in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_text(text, encoding="utf-8", newline="\n")


def _rules(source: str, name: str) -> list[tuple[re.Pattern, str]]:
    old = re.escape(source)
    return [
        (re.compile(rf"(?<![\w.]){old}(?=\.|\s+import\b)|(?<=import ){old}(?![\w.])"), name),
        (re.compile(rf"(?<![\w-])run([_-]){old}(?!\w)"), rf"run\g<1>{name}"),
        (re.compile(rf'^name = "{old}"$', re.MULTILINE), f'name = "{name}"'),
    ]


def _structure(parts: tuple[str, ...]) -> bool:
    """Ciò che si copia del job di partenza: tutto tranne il suo codice, i suoi test e le sue dipendenze."""
    if parts[0] == "src":
        inner = parts[2:]
        return inner[:1] == ("common",) or inner in (("__init__.py",), ("entrypoints", "__init__.py"))
    if parts[0] == "tests":
        return parts[-1] == "__init__.py"
    return parts != ("requirements.txt",)


def new_job(name: str, source: str, jobs_dir: Path, spark: bool = True, inputs: Sequence[str] = ()) -> Path:
    if not IDENTIFIER.match(name):
        raise ValueError(f"{name}: è anche il nome del package, quindi minuscole, cifre e _, e prima una lettera")
    src, dst = jobs_dir / source, jobs_dir / name
    if not src.is_dir():
        raise ValueError(f"{source}: non c'è in data/jobs/, indica il job da cui partire con FROM=<job>")
    if dst.exists():
        raise ValueError(f"{name}: in data/jobs/ c'è già un job con questo nome, indica il nuovo con JOB=<nome>")
    if importlib.util.find_spec(name) is not None:
        raise ValueError(f"{name}: c'è già un modulo Python con questo nome, che il package del job nasconderebbe")
    rules = _rules(source, name)
    module = re.compile(rf"^run_{re.escape(source)}(?=\.)")
    for path in sorted(src.rglob("*")):
        parts = path.relative_to(src).parts
        if not path.is_file() or any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in IGNORED):
            continue
        if not _structure(parts):
            continue
        renamed = [name if parts[:index] == ("src",) and part == source else part for index, part in enumerate(parts)]
        target = dst.joinpath(*renamed[:-1], module.sub(f"run_{name}", renamed[-1]))
        target.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            target.write_bytes(content)
            continue
        for pattern, replacement in rules:
            text = pattern.sub(replacement, text)
        target.write_bytes(text.encode("utf-8"))
    write_example(dst, name, spark, inputs)
    return dst


def _ask_spark() -> bool:
    while True:
        try:
            raw = input(f"{SPARK_QUESTION} [S/n] ").strip() or "s"
        except EOFError:
            return True
        try:
            return yes_no(raw)
        except ValueError as error:
            print(f"  {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="nome del nuovo job")
    parser.add_argument("--from", dest="source", required=True, help="job da cui copiare la struttura")
    parser.add_argument("--spark", help="s per l'esempio che legge le input port con Spark, n per lo scheletro")
    args = parser.parse_args()
    try:
        spark = yes_no(args.spark) if args.spark is not None else _ask_spark()
        jobs_dir = ROOT / "data" / "jobs"
        folder = new_job(args.name, args.source, jobs_dir, spark, input_ports()).relative_to(ROOT).as_posix()
    except ValueError as error:
        sys.exit(str(error))
    example = "l'esempio che legge le input port con Spark" if spark else "lo scheletro senza Spark"
    print(f"Creato {folder}, con la struttura di data/jobs/{args.source} e {example}. Ora:")
    print(f"  - la logica in {folder}/src/{args.name}/entrypoints/run_{args.name}.py")
    print(f'  - il task nel DAG: job("{args.name}") in data/dags/dag_pipeline.py')
    print(f"  - se servono librerie che il runtime di CDE non ha, {folder}/requirements.txt")


if __name__ == "__main__":
    main()
