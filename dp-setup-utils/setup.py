"""Inizializza il data product dalla blueprint: identità, moduli, primo job e porte al posto dell'esempio.

Uso: python dp-setup-utils/setup.py [NOME=VALORE ...], di solito con `make setup`: chiede i valori che non riceve.
Con --next-steps stampa solo i prossimi passi, come `make help`.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cde_setup
import new_job
import yaml

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = "dp-demo-blueprint"
KEYS = (
    "DOMAIN",
    "USE_CASE",
    "DESCRIPTION",
    "OWNER",
    "MODULES",
    "JOB",
    "SPARK",
    "QUALITY_LAYER",
    "CONTRACTS_REF",
    "INPUTS",
    "OUTPUTS",
    "YES",
)
MODULES = ("data", "quality")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
USE_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
OWNER = re.compile(r"^@[\w.-]+(/[\w.-]+)?$")
CONTRACT = re.compile(r"^[\w./-]+\.ya?ml$")
REF = re.compile(r"^\w(?:[\w.-]|/(?!/))*(?<![./])$")
GIT_STATUS = {"M": "modificato", "A": "creato", "?": "creato", "D": "cancellato", "R": "rinominato"}

Ask = Callable[[str, str, Callable[[str], object]], object]


@dataclass(frozen=True)
class Choices:
    domain: str
    use_case: str
    description: str
    owner: str
    modules: tuple[str, ...]
    job: str | None
    spark: bool
    quality_layer: str | None
    contracts_ref: str | None
    inputs: tuple[tuple[str, str], ...]
    outputs: tuple[tuple[str, str], ...]

    @property
    def name(self) -> str:
        return f"dp-{self.domain.replace('_', '-')}-{self.use_case}"


def _matching(pattern: re.Pattern, message: str) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        if not pattern.match(raw):
            raise ValueError(f"{raw or 'valore vuoto'}: {message}")
        return raw

    return parse


_domain = _matching(IDENTIFIER, "il dominio è un identificatore SQL, per esempio gpd")
_use_case = _matching(USE_CASE, "lo use case è in minuscolo, con i trattini, per esempio kpi o kpi-giornalieri")
_owner = _matching(OWNER, "l'owner è un handle GitHub che comincia con @, per esempio @pagopa/pagopa-tech")
_layer = _matching(IDENTIFIER, "il layer è un identificatore SQL, per esempio silver")
_contract = _matching(CONTRACT, "il path del contratto è un file .yaml del repo dei contratti")


def _ref(raw: str) -> str:
    if not REF.match(raw) or ".." in raw:
        raise ValueError(f"{raw or 'valore vuoto'}: il branch è un nome git, per esempio main o dqf-update-pagopa-dc")
    return raw


def _description(raw: str) -> str:
    if not raw or "\n" in raw:
        raise ValueError("la descrizione è una riga, non vuota")
    return raw


def _modules(raw: str) -> tuple[str, ...]:
    chosen = {item.strip() for item in raw.split(",") if item.strip()}
    if not chosen or chosen - set(MODULES):
        raise ValueError(f"{raw or 'valore vuoto'}: i moduli sono data, quality o tutti e due, separati da virgola")
    return tuple(module for module in MODULES if module in chosen)


def _job(examples: list[str]) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        if not IDENTIFIER.match(raw):
            raise ValueError(f"{raw or 'valore vuoto'}: il job è anche un package Python, quindi minuscole, cifre e _")
        if raw not in examples and importlib.util.find_spec(raw) is not None:
            raise ValueError(f"{raw}: c'è già un modulo Python con questo nome, che il package del job nasconderebbe")
        return raw

    return parse


def _port_name(taken: list[str]) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        if not IDENTIFIER.match(raw):
            raise ValueError(f"{raw or 'valore vuoto'}: il nome di una porta è un identificatore SQL, per esempio kpi")
        if raw in taken:
            raise ValueError(f"{raw}: c'è già una porta con questo nome")
        return raw

    return parse


def _ports(raw: str, required: bool) -> list[tuple[str, str]]:
    ports = []
    for item in filter(None, (part.strip() for part in raw.split(","))):
        name, _, path = item.partition("=")
        if not IDENTIFIER.match(name.strip()):
            raise ValueError(f"{name}: il nome di una porta è un identificatore SQL")
        ports.append((name.strip(), path.strip()))
    if required and not ports:
        raise ValueError("serve almeno una output port")
    if len({name for name, _ in ports}) != len(ports):
        raise ValueError(f"{raw}: nomi di porta ripetuti")
    return ports


def _ask(question: str, default: str, parse: Callable[[str], object]) -> object:
    while True:
        raw = input(f"{question} [{default}]: " if default else f"{question}: ").strip() or default
        try:
            return parse(raw)
        except ValueError as error:
            print(f"  {error}")


def given(pairs: list[str]) -> dict[str, str]:
    values = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or key not in KEYS:
            raise ValueError(f"{pair}: atteso NOME=VALORE, con NOME fra {', '.join(KEYS)}")
        values[key] = value.strip()
    return values


def _jobs(root: Path) -> list[str]:
    return sorted(path.name for path in (root / "data" / "jobs").glob("*") if path.is_dir())


def default_contract(domain: str, port: str) -> str:
    return f"src/data/pagopa/{domain}/dc-{domain.replace('_', '-')}-{port.replace('_', '-')}.yaml"


def collect(answers: dict[str, str], root: Path, ask: Ask = _ask) -> Choices:
    unattended = "YES" in answers
    heading: list[str] = []

    def section(title: str) -> None:
        heading[:] = [title]

    def asking(question: str, default: str, parse: Callable[[str], object]):
        if heading:
            print(f"\n{heading.pop()}")
        return ask(question, default, parse)

    def value(key: str, question: str, default: str, parse: Callable[[str], object]):
        if key in answers:
            return parse(answers[key])
        if not unattended:
            return asking(question, default, parse)
        try:
            return parse(default)
        except ValueError:
            raise ValueError(f"manca {key}: con YES=1 passalo come variabile, make setup {key}=...") from None

    def ports(key: str, kind: str, required: bool) -> tuple[tuple[str, str], ...]:
        if key in answers or unattended:
            listed = value(key, "", "", lambda raw: _ports(raw, required))
            return tuple((name, _contract(path) if path else default_contract(domain, name)) for name, path in listed)
        found: list[tuple[str, str]] = []
        more = required or asking(f"Aggiungere una {kind} port? (s/n)", "n", new_job.yes_no)
        question = f"Nome della {kind} port, identificatore SQL"
        if kind == "input":
            question = "Nome della input port, uguale a quello della tabella da leggere"
        while more:
            name = asking(question, "", _port_name([name for name, _ in found]))
            path = asking(f"Path del data contract di {name}", default_contract(domain, name), _contract)
            found.append((name, path))
            more = asking(f"Aggiungere un'altra {kind} port? (s/n)", "n", new_job.yes_no)
        return tuple(found)

    section("Identità del data product")
    domain = value("DOMAIN", "Sorgente/Dominio/Area utile a perimetrare lo scope (es. gpd, fdr)", "", _domain)
    use_case_question = "Keyword di identificazione dello use case, in minuscolo con i trattini (es. kpi, send-data)"
    use_case = value("USE_CASE", use_case_question, "", _use_case)
    description = value("DESCRIPTION", "Descrizione breve del Data Product", "", _description)
    owner_question = "Owner, handle GitHub del team (es. @pagopa/pagopa-team-qa o @pagopa/pagopa-tech)"
    owner = value("OWNER", owner_question, "", _owner)
    modules_question = "Modulo: data, quality (o tutti e due); separati da virgola"
    modules = value("MODULES", modules_question, ",".join(MODULES), _modules)
    job = quality_layer = contracts_ref = None
    spark = False
    if "data" in modules:
        section("Modulo Dati: si parte inizializzando un job")
        job = value("JOB", "Nome del primo job", use_case.replace("-", "_"), _job(_jobs(root)))
        spark = value("SPARK", f"{new_job.SPARK_QUESTION} (s/n)", "s", new_job.yes_no)
    if "quality" in modules:
        section("Modulo Quality: le informazioni per le sue tabelle")
        quality_question = f"Layer della quality (dlLayer), nel nome delle sue tabelle: <dlLayer>_dqf_{domain}_results"
        quality_layer = value("QUALITY_LAYER", quality_question, "silver", _layer)
        ref_question = "Branch dei contratti da cui la quality legge i check (es. main, dqf-update-pagopa-dc)"
        contracts_ref = value("CONTRACTS_REF", ref_question, "main", _ref)
    section("Porte: le tabelle che il data product legge (input) ed espone (output)")
    inputs = ports("INPUTS", "input", required=False)
    outputs = ports("OUTPUTS", "output", required=True)
    return Choices(
        domain, use_case, description, owner, modules, job, spark, quality_layer, contracts_ref, inputs, outputs
    )


def _example(spark: bool) -> str:
    return "esempio che legge le input port con Spark" if spark else "scheletro senza Spark"


def summary(choices: Choices) -> str:
    rows = [
        ("name", choices.name),
        ("description", choices.description),
        ("owner", choices.owner),
        ("moduli", ", ".join(choices.modules)),
    ]
    if choices.job:
        rows.append(("primo job", choices.job))
        rows.append(("esempio del job", _example(choices.spark)))
    if choices.quality_layer:
        rows.append(("layer della quality", choices.quality_layer))
        rows.append(("branch dei contratti", choices.contracts_ref))
    rows += [("input port", f"{name}  {path}") for name, path in choices.inputs] or [("input port", "nessuna")]
    rows += [("output port", f"{name}  {path}") for name, path in choices.outputs]
    width = max(len(label) for label, _ in rows)
    return "\n".join(["", "Riepilogo:", *(f"  {label.ljust(width)}  {value}" for label, value in rows), ""])


def _scalar(value: str) -> str:
    try:
        if yaml.safe_load(f"v: {value}") == {"v": value}:
            return value
    except yaml.YAMLError:
        pass
    return json.dumps(value, ensure_ascii=False)


def _ports_text(items: list[dict], indent: str = "  ") -> str:
    if not items:
        return " []\n"
    lines = []
    for item in items:
        for index, (key, value) in enumerate(item.items()):
            head = f"{indent}{'- ' if index == 0 else '  '}{key}:"
            nested = isinstance(value, list)
            lines.append(head + (_ports_text(value, indent + "    ") if nested else f" {_scalar(str(value))}\n"))
    return "\n" + "".join(lines)


def descriptor_text(dp: dict) -> str:
    modules = "".join(f"  {module}: {str(enabled).lower()}\n" for module, enabled in dp["modules"].items())
    return (
        f"name: {dp['name']}\ndomain: {dp['domain']}\nversion: {dp['version']}\n"
        f"description: {_scalar(dp['description'])}\nowner: {_scalar(dp['owner'])}\nstatus: {dp['status']}\n\n"
        f"modules:\n{modules}\n"
        f"inputPorts:{_ports_text(dp['inputPorts'])}\n"
        f"outputPorts:{_ports_text(dp['outputPorts'])}\n"
        f"observabilityPorts:{_ports_text(dp['observabilityPorts'])}"
    )


def _descriptor(choices: Choices) -> str:
    def ports(items: tuple[tuple[str, str], ...]) -> list[dict]:
        return [{"name": name, "dataContractPath": path} for name, path in items]

    return descriptor_text(
        {
            "name": choices.name,
            "domain": choices.domain,
            "version": "0.1.0",
            "description": choices.description,
            "owner": choices.owner,
            "status": "draft",
            "modules": {module: module in choices.modules for module in MODULES},
            "inputPorts": ports(choices.inputs),
            "outputPorts": ports(choices.outputs),
            "observabilityPorts": [],
        }
    )


def _readme(text: str, choices: Choices) -> str:
    text = re.sub(r"\A# .*\n\n.*\n", lambda _: f"# Data product {choices.name}\n\n{choices.description}\n", text)
    for title in ("Partire da questa blueprint", "L'esempio"):
        text = re.sub(rf"^## {re.escape(title)}\n.*?(?=^## )", "", text, flags=re.MULTILINE | re.DOTALL)
    return text


def ddl(port: str) -> str:
    return (
        f"-- TODO: nome della tabella e colonne come nel contratto della output port {port}.\n"
        f"CREATE TABLE IF NOT EXISTS ${{env.databases.data}}.{port} (\n"
        "    dl_id        STRING    COMMENT 'Chiave surrogata',\n"
        "    dl_event_tms TIMESTAMP COMMENT 'Ora evento: colonna watermark di default del dq-framework'\n"
        ")\n"
        "USING iceberg\n"
        "PARTITIONED BY (days(dl_event_tms))\n"
        "TBLPROPERTIES ('format-version' = '2');\n"
    )


def _quality(text: str, layer: str, ref: str) -> str:
    text = re.sub(r"^dlLayer: .*$", f"dlLayer: {layer}", text, flags=re.MULTILINE)
    contracts_ref = re.compile(r"^(contracts:\n(?:  .*\n)*?  ref: ).*$", re.MULTILINE)
    text, count = contracts_ref.subn(lambda match: match.group(1) + _scalar(ref), text)
    if not count:
        raise ValueError("la configurazione della quality non ha contracts.ref: mettici tu il branch dei contratti")
    for key in ("primaryKeys", "xrefDatasets"):
        text = re.sub(rf"^{key}:.*\n(?:  .*\n)*", f"{key}: {{}}\n", text, flags=re.MULTILINE)
    return text


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _check_blueprint(root: Path) -> dict:
    dp = yaml.safe_load((root / "data-product.yaml").read_text(encoding="utf-8"))
    if dp["name"] != BLUEPRINT:
        raise ValueError(f"{dp['name']} è già inizializzato: make setup serve solo sulla copia della blueprint")
    return dp


def apply(choices: Choices, root: Path) -> list[tuple[str, str, str]]:
    old = _check_blueprint(root)
    examples = _jobs(root)
    changes: list[tuple[str, str, str]] = []
    _write(root / "data-product.yaml", _descriptor(choices))
    changes.append(("modificato", "data-product.yaml", "identità, moduli e porte"))
    codeowners = root / "CODEOWNERS"
    _write(codeowners, codeowners.read_text(encoding="utf-8").replace(old["owner"], choices.owner))
    changes.append(("modificato", "CODEOWNERS", f"owner {choices.owner}"))
    readme = root / "README.md"
    _write(readme, _readme(readme.read_text(encoding="utf-8"), choices))
    changes.append(("modificato", "README.md", "titolo e descrizione, senza le sezioni sulla blueprint e sull'esempio"))
    if choices.job:
        jobs_dir = root / "data" / "jobs"
        inputs = [name for name, _ in choices.inputs]
        if choices.job not in examples:
            source = "ingestion" if "ingestion" in examples else examples[0]
            new_job.new_job(choices.job, source, jobs_dir, choices.spark, inputs)
            detail = f"struttura di data/jobs/{source}/, {_example(choices.spark)}"
            changes.append(("creato", f"data/jobs/{choices.job}/", detail))
        else:
            new_job.write_example(jobs_dir / choices.job, choices.job, choices.spark, inputs)
            changes.append(("modificato", f"data/jobs/{choices.job}/", _example(choices.spark)))
        for job in examples:
            if job != choices.job:
                shutil.rmtree(jobs_dir / job)
                changes.append(("cancellato", f"data/jobs/{job}/", "job di esempio"))
        dag = root / "data" / "dags" / "dag_pipeline.py"
        task = rf'\g<1>    job("{choices.job}")\n'
        text, count = re.subn(r"(\) as dag:\n)(?:    .*\n)+\Z", task, dag.read_text(encoding="utf-8"))
        if not count:
            raise ValueError(f"{dag.name} non è quello della blueprint: metti tu job(\"{choices.job}\") nel DAG")
        _write(dag, text)
        changes.append(("modificato", "data/dags/dag_pipeline.py", f'un solo task, job("{choices.job}")'))
        tables = root / "data" / "ddl" / "tables"
        for path in sorted(tables.glob("*.sql")):
            path.unlink()
            changes.append(("cancellato", f"data/ddl/tables/{path.name}", "DDL di esempio"))
        for number, (port, _) in enumerate(choices.outputs, start=1):
            name = f"V{number:03d}__create_{port}.sql"
            _write(tables / name, ddl(port))
            changes.append(("creato", f"data/ddl/tables/{name}", f"scheletro della output port {port}"))
    else:
        shutil.rmtree(root / "data")
        changes.append(("cancellato", "data/", "Modulo Dati"))
    if "quality" in choices.modules:
        for path in sorted((root / "quality" / "config").glob("*.yaml")):
            _write(path, _quality(path.read_text(encoding="utf-8"), choices.quality_layer, choices.contracts_ref))
            detail = f"dlLayer {choices.quality_layer}, branch dei contratti {choices.contracts_ref}"
            detail += ", primaryKeys e xrefDatasets vuoti"
            changes.append(("modificato", f"quality/config/{path.name}", detail))
    else:
        shutil.rmtree(root / "quality")
        changes.append(("cancellato", "quality/", "Modulo Quality"))
    return changes


def _table(rows: list[tuple[str, str, str]]) -> list[str]:
    width = max(len(path) for _, path, _ in rows)
    return [f"  {action.ljust(10)}  {path.ljust(width)}  {detail}".rstrip() for action, path, detail in rows]


def report(changes: list[tuple[str, str, str]], title: str = "Cosa ha cambiato il setup:") -> str:
    return "\n".join([title, *_table(changes)])


def pending_text(changes: list[str]) -> str:
    found: dict[str, set[str]] = {}
    for line in changes:
        path = line[3:]
        parts = path.split("/")
        if parts[:2] == ["data", "jobs"] and len(parts) > 3:
            path = "/".join(parts[:3]) + "/"
        found.setdefault(path, set()).add(GIT_STATUS.get(line[:2].strip()[:1], "modificato"))
    rows = [(actions.pop() if len(actions) == 1 else "modificato", path, "") for path, actions in sorted(found.items())]
    return "\n".join(_table(rows))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(["git", *args], 127, "", "git non trovato")


def pending(root: Path) -> list[str] | None:
    tracked = _git(root, "status", "--porcelain", "--untracked-files=no")
    if tracked.returncode != 0:
        return None
    untracked = _git(root, "status", "--porcelain", "--untracked-files=normal", "--", "data", "quality")
    return tracked.stdout.splitlines() + [line for line in untracked.stdout.splitlines() if line.startswith("??")]


def check_clean(root: Path) -> None:
    changes = pending(root)
    if changes:
        listed = pending_text(changes)
        raise ValueError(f"ci sono modifiche non committate:\n{listed}\ncommittale prima: così il setup si può rifare")


def undo(root: Path) -> list[str]:
    listed = _git(root, "ls-tree", "--name-only", "HEAD", "data/jobs/").stdout.split()
    created = [job for job in _jobs(root) if job not in {Path(path).name for path in listed}]
    restore = ("restore", "--source=HEAD", "--staged", "--worktree", "--", ".")
    clean = ("clean", "-fdxq", "--", "data", "quality")
    for args in (restore, clean):
        if _git(root, *args).returncode != 0:
            raise ValueError(f"git {' '.join(args)} non riuscito: controlla con git status")
    return created


def _setup_uncommitted(root: Path) -> bool:
    committed = _git(root, "show", "HEAD:data-product.yaml")
    return committed.returncode == 0 and yaml.safe_load(committed.stdout)["name"] == BLUEPRINT


def next_steps(root: Path) -> str:
    ready = yaml.safe_load((root / "data-product.yaml").read_text(encoding="utf-8"))["name"] != BLUEPRINT
    data, quality = (root / "data").is_dir(), (root / "quality").is_dir()
    jobs = _jobs(root)
    job = jobs[0] if ready and len(jobs) == 1 else "<job>"
    command, manual = "Comando", "A mano"
    steps: list[tuple[bool, str, str, tuple[tuple[str, str], ...]]] = []
    anytime: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []

    def step(required: bool, title: str, what: str, *how: tuple[str, str]) -> None:
        steps.append((required, title, what, how))

    if not ready:
        what = "Sostituisce l'esempio con il tuo data product: chiede nome, owner, moduli, primo job e porte."
        step(True, "Inizializza il data product", what, (command, "make setup"))
    elif _setup_uncommitted(root):
        what = "Controlla i file che il setup ha cambiato: finché non committi, make setup lo rifà con altre risposte."
        step(True, "Rivedi e committa il setup", what, (command, "git status, poi git commit"))
    if data:
        entrypoint = f"data/jobs/{job}/src/{job}/entrypoints/run_{job}.py"
        if not (root / entrypoint).is_file():
            entrypoint = f"data/jobs/{job}/src/{job}/entrypoints/, per ogni job"
        what = "Il codice Spark che legge le input port e scrive le tabelle, rieseguibile sullo stesso intervallo."
        step(True, "Scrivi la logica dei job", what, (manual, entrypoint))
        what = "Lo lancia nel Dev Container con la configurazione di dev, che non scrive tabelle."
        step(False, "Prova un job in locale", what, (command, f'make run-dev JOB={job} ARGS="--from <AAAA-MM-GG>"'))
        what = "Il nome e le colonne delle tabelle, come nei contratti, e quando deve girare la pipeline."
        step(True, "Completa DDL e schedule", what, (command, "make render ENV=test elenca i TODO che mancano"))
    if quality:
        what = (
            "Sposta lo schedule per non sovrapporti agli altri data product; "
            "chiavi e tabelle di confronto se servono."
        )
        step(False, "Configura la quality", what, (manual, "quality/config/test.yaml e prod.yaml"))
    what = (
        "Il lint (ruff) segnala nel codice Python nomi non definiti, import inutili e problemi di stile.\n"
        "I test verificano descrittore, DDL, DAG e definizioni dei job in test e prod, poi lanciano i test dei job.\n"
        "Sono gli stessi controlli che la CI ripete a ogni push."
    )
    step(True, "Controlla lint e test", what, (command, "make lint, poi make test"))
    if not cde_setup.configured():
        what = "Tre passi guidati, CLI cde, endpoint del vcluster e access key, poi collegamento e prerequisiti."
        step(True, "Configura l'accesso a CDE", what, (command, "make cde-setup"))
    ddls = (manual, "le DDL, come nella sezione Deploy del README")
    what = "Crea le tabelle, poi carica job e DAG su CDE: in test i DAG partono in pausa."
    step(True, "Deploya su test", what, ddls, (command, "make plan ENV=test, poi make deploy ENV=test"))
    what = "Come in test, quando lì i job girano: in prod i DAG non partono in pausa."
    prod = "make plan ENV=prod, poi make deploy ENV=prod, o il workflow CD"
    step(True, "Rilascia in prod", what, ddls, (command, prod))
    if data:
        what = "Un altro job, per esempio un'altra fase della pipeline, con la struttura di uno esistente."
        new = "make new-job JOB=<nome>, con SPARK=n per lo scheletro senza Spark"
        dag = 'job("<nome>") in data/dags/dag_pipeline.py'
        anytime.append(("Aggiungi un job", what, ((command, new), (manual, dag))))
    exposed = "con la sua DDL scheletro" if data else "e che la quality misurerà"
    what = f"Una tabella che il data product espone, {exposed}, o una che legge, con il nome della tabella."
    new_port = "make new-port PORT=<nome>, con INPUT=1 se è da leggere"
    anytime.append(("Aggiungi una input o output port", what, ((command, new_port),)))
    what = "Dove si monitora il data product: una dashboard Superset o i dataset su Soda Cloud, con i loro URL."
    observe = "make new-observability-port TYPE=superset URL=<url>, o TYPE=sodacloud"
    anytime.append(("Aggiungi una observability port, Soda o Superset", what, ((command, observe),)))

    width = len(str(len(steps)))
    indent = " " * (width + 4)
    lines = ["Prossimi passi, in ordine:"]
    for number, (required, title, what, how) in enumerate(steps, start=1):
        tag = "[obbligatorio]" if required else "[facoltativo]"
        lines += ["", f"  {number:>{width}}. {tag} {title}", *(f"{indent}{line}" for line in what.splitlines())]
        lines += [f"{indent}{label}: {text}" for label, text in how]
    lines += ["", "", "Quando servono, in qualsiasi momento:"]
    for title, what, how in anytime:
        lines += ["", f"{indent[:-2]}- {title}", f"{indent}{what}"]
        lines += [f"{indent}{label}: {text}" for label, text in how]
    return "\n".join(lines)


def _yes(question: str) -> bool:
    return input(f"{question} [s/N] ").strip().lower() in ("s", "si", "sì")


def _pip(*args: str) -> int:
    return subprocess.run([sys.executable, "-m", "pip", *args], cwd=ROOT).returncode


def _uninstall(jobs: list[str]) -> None:
    installed = []
    for job in jobs:
        try:
            importlib.metadata.version(job)
        except importlib.metadata.PackageNotFoundError:
            continue
        installed.append(job)
    if installed:
        _pip("uninstall", "-y", "-q", *installed)


def _left(undone: bool) -> str:
    return "il data product è tornato alla blueprint: rilancia make setup" if undone else "nessun file modificato"


def _redo(answers: dict[str, str]) -> None:
    name = yaml.safe_load((ROOT / "data-product.yaml").read_text(encoding="utf-8"))["name"]
    changes = pending(ROOT)
    if changes is None:
        raise ValueError(f"{name} è già inizializzato e senza git non si annulla: riparti da una copia della blueprint")
    if not _setup_uncommitted(ROOT):
        raise ValueError(f"{name} è già inizializzato e committato: per rifare il setup annulla il commit (git revert)")
    if "YES" in answers:
        raise ValueError(f"{name} è già inizializzato: per rifare il setup lancialo da un terminale, senza YES=1")
    print(f"{name} è già inizializzato, ma il setup non è ancora committato. Per rifarlo annullo queste modifiche:")
    print(pending_text(changes))
    if not _yes("Le annullo e ricomincio dalla blueprint?"):
        sys.exit("nessun file modificato")
    _uninstall(undo(ROOT))
    print("Tornato alla blueprint.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answers", nargs="*", metavar="NOME=VALORE", help=f"valori già decisi: {', '.join(KEYS)}")
    parser.add_argument("--next-steps", action="store_true", help="stampa i prossimi passi ed esce")
    args = parser.parse_args()
    if args.next_steps:
        print(next_steps(ROOT))
        return
    undone = False
    try:
        answers = given(args.answers)
        if yaml.safe_load((ROOT / "data-product.yaml").read_text(encoding="utf-8"))["name"] != BLUEPRINT:
            _redo(answers)
            undone = True
        check_clean(ROOT)
        examples = _jobs(ROOT)
        choices = collect(answers, ROOT)
        print(summary(choices))
        confirmed = "YES" in answers or _yes("Sostituisco l'esempio con questi valori?")
    except ValueError as error:
        sys.exit(str(error))
    except (EOFError, KeyboardInterrupt) as error:
        hint = ": senza terminale passa i valori come variabili, con YES=1" if isinstance(error, EOFError) else ""
        sys.exit(f"\nsetup interrotto, {_left(undone)}{hint}")
    if not confirmed:
        sys.exit(_left(undone))
    changes = apply(choices, ROOT)
    _uninstall([job for job in examples if job != choices.job])
    if choices.job and _pip("install", "-q", "-e", f"data/jobs/{choices.job}[dev]") != 0:
        print(f"installazione di {choices.job} non riuscita: rilanciala con make install")
    print(f"\n{report(changes)}\n\n{choices.name} è pronto.\n\n{next_steps(ROOT)}")


if __name__ == "__main__":
    main()
