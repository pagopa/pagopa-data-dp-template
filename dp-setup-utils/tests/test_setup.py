from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest
import render
import setup
import yaml

pytestmark = pytest.mark.skipif(
    yaml.safe_load((render.ROOT / "data-product.yaml").read_text(encoding="utf-8"))["name"] != setup.BLUEPRINT,
    reason="data product già inizializzato: make setup serve solo sulla blueprint",
)
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "dist", "build", "__pycache__", "*.egg-info", ".pytest_cache", ".ruff_cache", ".venv"
)
ANSWERS = {
    "DOMAIN": "gpd",
    "USE_CASE": "kpi",
    "DESCRIPTION": "KPI sulle posizioni debitorie",
    "OWNER": "@pagopa/team-kpi",
    "MODULES": "data,quality",
    "JOB": "kpi",
    "SPARK": "s",
    "QUALITY_LAYER": "gold",
    "CONTRACTS_REF": "dqf-update-pagopa-dc",
    "INPUTS": "raw_positions",
    "OUTPUTS": "kpi_positions,kpi_daily=src/data/pagopa/gpd/kpi-daily.yaml",
}


def _no_questions(question, default, parse):
    raise AssertionError(f"domanda inattesa: {question}")


@pytest.fixture
def clone(tmp_path):
    root = tmp_path / "dp"
    shutil.copytree(render.ROOT, root, ignore=COPY_IGNORE)
    return root


@pytest.mark.parametrize(("modules", "spark"), [("data,quality", "s"), ("data", "n"), ("quality", "s")])
def test_setup_produce_un_data_product_valido(clone, modules, spark):
    choices = setup.collect({**ANSWERS, "MODULES": modules, "SPARK": spark}, clone, ask=_no_questions)
    changes = setup.apply(choices, clone)
    tests = [sys.executable, "-m", "pytest", "dp-setup-utils/tests", "-q", "-p", "no:cacheprovider"]
    result = subprocess.run(tests, cwd=clone, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-4000:]
    dp = yaml.safe_load((clone / "data-product.yaml").read_text(encoding="utf-8"))
    assert dp["name"] == "dp-gpd-kpi"
    assert [port["dataContractPath"] for port in dp["outputPorts"]] == [
        "src/data/pagopa/gpd/dc-gpd-kpi-positions.yaml",
        "src/data/pagopa/gpd/kpi-daily.yaml",
    ]
    readme = (clone / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Data product dp-gpd-kpi\n\nKPI sulle posizioni debitorie\n")
    assert "## Partire da questa blueprint" not in readme and "## L'esempio" not in readme
    report = setup.report(changes)
    assert all(path in report for _, path, _ in changes)
    assert ("Configura la quality" in setup.next_steps(clone)) == ("quality" in modules)
    if "data" in modules:
        assert setup._jobs(clone) == ["kpi"]
        detail = f"struttura di data/jobs/ingestion/, {setup._example(spark == 's')}"
        assert ("creato", "data/jobs/kpi/", detail) in changes
        entrypoint = clone / "data" / "jobs" / "kpi" / "src" / "kpi" / "entrypoints" / "run_kpi.py"
        code = entrypoint.read_text(encoding="utf-8")
        assert ("SparkSession" in code) == (spark == "s")
        assert ('    "raw_positions",\n' in code) == (spark == "s"), "legge le input port scelte"
        assert {path for action, path, _ in changes if action == "cancellato" and path.startswith("data/jobs/")} == {
            "data/jobs/deduplication/",
            "data/jobs/ingestion/",
        }
        tables = sorted(path.name for path in (clone / "data" / "ddl" / "tables").glob("*.sql"))
        assert tables == ["V001__create_kpi_positions.sql", "V002__create_kpi_daily.sql"]
        job_tests = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        env = {**os.environ, "PYTHONPATH": "src"}
        result = subprocess.run(job_tests, cwd=clone / "data" / "jobs" / "kpi", env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout[-4000:]
    else:
        assert not (clone / "data").exists()
    if "quality" in modules:
        quality = yaml.safe_load((clone / "quality" / "config" / "test.yaml").read_text(encoding="utf-8"))
        assert (quality["dlLayer"], quality["primaryKeys"], quality["xrefDatasets"]) == ("gold", {}, {})
        assert quality["contracts"]["ref"] == "dqf-update-pagopa-dc"
    else:
        assert not (clone / "quality").exists()


def test_job_con_il_nome_di_un_esempio_legge_le_input_port_scelte(clone):
    changes = setup.apply(setup.collect({**ANSWERS, "JOB": "ingestion"}, clone, ask=_no_questions), clone)
    assert ("modificato", "data/jobs/ingestion/", setup._example(spark=True)) in changes
    code = (clone / "data" / "jobs" / "ingestion" / "src" / "ingestion" / "entrypoints" / "run_ingestion.py").read_text(
        encoding="utf-8"
    )
    assert '"raw_positions"' in code and "raw_payments" not in code


def _scripted(answers):
    asked = []

    def ask(question, default, parse):
        asked.append(question)
        return parse(next((value for prefix, value in answers.items() if question.startswith(prefix)), default))

    return ask, asked


def test_default(clone):
    identity = {"Sorgente": "gpd", "Keyword": "kpi", "Descrizione": "KPI", "Owner": "@o/t"}
    ask, _ = _scripted({**identity, "Nome della output port": "kpi"})
    choices = setup.collect({}, clone, ask=ask)
    assert (choices.modules, choices.job, choices.quality_layer, choices.inputs) == (setup.MODULES, "kpi", "silver", ())
    assert choices.spark, "di default il primo job legge le input port con Spark"
    assert choices.outputs == (("kpi", "src/data/pagopa/gpd/dc-gpd-kpi.yaml"),)


def test_porte_una_alla_volta(clone, capsys):
    replies = iter(["s", "positions", "", "s", "transfers", "dc/transfers.yaml", "n", "kpi", "", "n"])
    asked = []

    def ask(question, default, parse):
        asked.append(question)
        return parse(next(replies) or default)

    answers = {key: value for key, value in ANSWERS.items() if key not in ("INPUTS", "OUTPUTS")}
    choices = setup.collect(answers, clone, ask=ask)
    assert choices.inputs == (
        ("positions", "src/data/pagopa/gpd/dc-gpd-positions.yaml"),
        ("transfers", "dc/transfers.yaml"),
    )
    assert choices.outputs == (("kpi", "src/data/pagopa/gpd/dc-gpd-kpi.yaml"),)
    assert asked[0] == "Aggiungere una input port? (s/n)"
    assert "Aggiungere una output port? (s/n)" not in asked, "serve almeno una output port: il nome si chiede subito"
    assert capsys.readouterr().out.strip().startswith("Porte:"), "il titoletto solo delle domande che fa"
    with pytest.raises(ValueError, match="c'è già"):
        setup._port_name(["kpi"])("kpi")


@pytest.mark.parametrize(("modules", "asked_layer"), [("data", False), ("quality", True)])
def test_dl_layer_solo_con_la_quality(clone, modules, asked_layer):
    ask, asked = _scripted({})
    answers = {key: value for key, value in ANSWERS.items() if key not in ("QUALITY_LAYER", "CONTRACTS_REF")}
    choices = setup.collect({**answers, "MODULES": modules}, clone, ask=ask)
    questions = [
        "Layer della quality (dlLayer), nel nome delle sue tabelle: <dlLayer>_dqf_gpd_results",
        "Branch dei contratti da cui la quality legge i check (es. main, dqf-update-pagopa-dc)",
    ]
    assert asked == (questions if asked_layer else [])
    assert choices.contracts_ref == ("main" if asked_layer else None)


def test_branch_dei_contratti_resta_una_stringa():
    text = (render.ROOT / "quality" / "config" / "test.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(setup._quality(text, "silver", "1.10"))["contracts"]["ref"] == "1.10"


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("DOMAIN", "GPD", "identificatore"),
        ("USE_CASE", "kpi_giornalieri", "trattini"),
        ("OWNER", "pagopa", "@"),
        ("MODULES", "dati", "moduli"),
        ("JOB", "json", "modulo Python"),
        ("SPARK", "forse", "s o n"),
        ("CONTRACTS_REF", "main..dev", "branch"),
        ("CONTRACTS_REF", "-main", "branch"),
        ("OUTPUTS", "", "almeno una"),
        ("OUTPUTS", "kpi,kpi", "ripetuti"),
    ],
)
def test_risposte_non_valide(key, value, error):
    with pytest.raises(ValueError, match=error):
        setup.collect({**ANSWERS, key: value}, render.ROOT, ask=_no_questions)


def test_yes_usa_i_default(clone):
    minimal = {key: ANSWERS[key] for key in ("DOMAIN", "USE_CASE", "DESCRIPTION", "OWNER", "OUTPUTS")}
    choices = setup.collect({**minimal, "YES": "1"}, clone, ask=_no_questions)
    assert (choices.modules, choices.job, choices.quality_layer, choices.inputs) == (setup.MODULES, "kpi", "silver", ())
    assert choices.spark and choices.contracts_ref == "main"
    for missing in ("OWNER", "OUTPUTS"):
        incomplete = {key: value for key, value in minimal.items() if key != missing}
        with pytest.raises(ValueError, match=f"manca {missing}"):
            setup.collect({**incomplete, "YES": "1"}, clone, ask=_no_questions)


def test_variabili_di_make():
    answers = setup.given(["DOMAIN=gpd", "DESCRIPTION=KPI dell'incasso"])
    assert answers == {"DOMAIN": "gpd", "DESCRIPTION": "KPI dell'incasso"}
    with pytest.raises(ValueError, match="NOME=VALORE"):
        setup.given(["DOMINIO=gpd"])


def _commit(root):
    identity = ["-c", "user.name=blueprint", "-c", "user.email=blueprint@example.com"]
    for args in (["init", "-q"], ["add", "-A"], [*identity, "commit", "-qm", "blueprint"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_senza_modifiche_non_committate(clone):
    _commit(clone)
    setup.check_clean(clone)
    (clone / "README.md").write_text("modificato\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non committate"):
        setup.check_clean(clone)


def test_si_annulla_per_rifarlo(clone):
    _commit(clone)
    setup.apply(setup.collect(ANSWERS, clone, ask=_no_questions), clone)
    egg_info = clone / "data" / "jobs" / "kpi" / "src" / "kpi.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("ignorato da git, come dopo pip install -e\n", encoding="utf-8")
    listed = setup.pending_text(setup.pending(clone)).splitlines()
    assert [line.split() for line in listed if "data/jobs/" in line] == [
        ["cancellato", "data/jobs/deduplication/"],
        ["cancellato", "data/jobs/ingestion/"],
        ["creato", "data/jobs/kpi/"],
    ]
    assert ["modificato", "data-product.yaml"] in [line.split() for line in listed]
    assert setup.undo(clone) == ["kpi"]
    assert setup.pending(clone) == []
    assert setup._jobs(clone) == ["deduplication", "ingestion"]
    assert "dp-demo-blueprint" in (clone / "data-product.yaml").read_text(encoding="utf-8")


def test_una_volta_sola(clone):
    choices = setup.collect(ANSWERS, clone, ask=_no_questions)
    setup.apply(choices, clone)
    with pytest.raises(ValueError, match="già inizializzato"):
        setup.apply(choices, clone)


def _titles(steps: str) -> list[str]:
    return [line.strip() for line in steps.splitlines() if line[:4].strip().rstrip(".").isdigit()]


@pytest.fixture
def cde_configured(monkeypatch):
    configured = [False]
    monkeypatch.setattr(setup.cde_setup, "configured", lambda: configured[0])
    return configured


def test_prossimi_passi(clone, cde_configured):
    before = setup.next_steps(clone)
    assert _titles(before)[0] == "1. [obbligatorio] Inizializza il data product" and "Comando: make setup" in before
    _commit(clone)
    setup.apply(setup.collect(ANSWERS, clone, ask=_no_questions), clone)
    steps = setup.next_steps(clone)
    titles = _titles(steps)
    assert [int(title.split(".")[0]) for title in titles] == list(range(1, len(titles) + 1))
    assert all("[obbligatorio]" in title or "[facoltativo]" in title for title in titles)
    required = [title.split("] ", 1)[1] for title in titles if "[obbligatorio]" in title]
    assert required == [
        "Rivedi e committa il setup",
        "Scrivi la logica dei job",
        "Completa DDL e schedule",
        "Controlla lint e test",
        "Configura l'accesso a CDE",
        "Deploya su test",
        "Rilascia in prod",
    ]
    assert titles[-1] == f"{len(titles)}. [obbligatorio] Rilascia in prod"
    numbered, anytime = steps.split("Quando servono, in qualsiasi momento:")
    added = ("- Aggiungi un job", "- Aggiungi una input o output port", "- Aggiungi una observability port")
    assert [title for title in added if title in numbered] == [] and all(title in anytime for title in added)
    assert "Comando: make new-port PORT=<nome>" in anytime
    assert "Comando: make new-observability-port TYPE=superset URL=<url>, o TYPE=sodacloud" in anytime
    assert "Comando: make cde-setup" in steps
    assert "Comando: make lint, poi make test" in steps and "ruff" in steps
    cde_configured[0] = True
    assert "make cde-setup" not in setup.next_steps(clone), "l'accesso a CDE già configurato non è più un passo"
    assert "A mano: data/jobs/kpi/src/kpi/entrypoints/run_kpi.py" in steps
    identity = ["-c", "user.name=blueprint", "-c", "user.email=blueprint@example.com"]
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", *identity, "commit", "-qm", "setup"], cwd=clone, check=True, capture_output=True)
    assert _titles(setup.next_steps(clone))[0] == "1. [obbligatorio] Scrivi la logica dei job"
