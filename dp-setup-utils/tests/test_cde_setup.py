from __future__ import annotations

import os
import subprocess
from pathlib import Path

import cde_setup
import pytest
import render

ENDPOINT = "https://abcd1234.cde-efgh5678.pagopa.a1b2-c3d4.cloudera.site/dex/api/v1"
VARIABLES = ("CDE_VCLUSTER_ENDPOINT", "CDE_ACCESS_KEY_ID", "CDE_ACCESS_KEY_SECRET", "CDE_CLI_DOWNLOAD_URL")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """La guida in una cartella temporanea, con la CLI già installata e senza variabili e credenziali della macchina."""
    monkeypatch.setattr(cde_setup, "ROOT", tmp_path)
    monkeypatch.setattr(cde_setup, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(cde_setup, "CLI", tmp_path / "bin-cde")
    monkeypatch.setattr(cde_setup, "CREDENTIALS", ())
    monkeypatch.delenv("CDE_CREDENTIALS_FILE", raising=False)
    for name in VARIABLES:
        # setenv prima di delenv: così monkeypatch toglie anche ciò che la guida scrive in os.environ.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    cde_setup.CLI.write_bytes(b"cli")
    return tmp_path


@pytest.fixture
def cde(monkeypatch):
    """CLI finta: parte solo se è installata, scarica con curl un file qualsiasi e fallisce sui nomi in missing."""
    calls: list[list[str]] = []
    missing: set[str] = set()

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "curl":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"cli")
        failed = cmd[-1] in missing or (cmd[-1] == "--version" and not cde_setup.CLI.exists())
        return subprocess.CompletedProcess(cmd, int(failed), "cde version 1.0.0\n", "errore finto\n")

    monkeypatch.setattr(cde_setup.subprocess, "run", run)
    monkeypatch.setattr(cde_setup.shutil, "which", lambda name: None)
    return calls, missing


def _answers(monkeypatch, answers: dict[str, list[str]]) -> list[str]:
    """Risposte alle domande che cominciano con ogni chiave, una per volta; poi l'input finisce."""
    asked: list[str] = []
    queues = {prefix: iter(values) for prefix, values in answers.items()}

    def answer(question, secret=False):
        asked.append(question)
        return next((next(queue, None) for prefix, queue in queues.items() if question.startswith(prefix)), None)

    monkeypatch.setattr(cde_setup, "_input", answer)
    return asked


def test_esempio_del_env():
    example = (render.ROOT / ".env.example").read_text(encoding="utf-8")
    for name in VARIABLES:
        assert f"# {name}=" in example, f".env.example: manca {name}, che make cde-setup scrive nel .env"


def test_scrive_il_env(home):
    example = "# Da compilare:\n# CDE_VCLUSTER_ENDPOINT=https://<vcluster>/dex/api/v1\n# LOG_LEVEL=INFO\n"
    (home / ".env.example").write_text(example, encoding="utf-8")
    cde_setup.save({"CDE_VCLUSTER_ENDPOINT": "https://vecchio/dex/api/v1"})
    cde_setup.save({"CDE_VCLUSTER_ENDPOINT": ENDPOINT, "CDE_ACCESS_KEY_ID": "id"})
    env = (home / ".env").read_text(encoding="utf-8")
    assert env == f"# Da compilare:\nCDE_VCLUSTER_ENDPOINT={ENDPOINT}\n# LOG_LEVEL=INFO\nCDE_ACCESS_KEY_ID=id\n"
    assert os.environ["CDE_VCLUSTER_ENDPOINT"] == ENDPOINT


@pytest.mark.parametrize(
    ("parse", "raw"),
    [
        (cde_setup._endpoint, "https://<vcluster>.cloudera.site/dex/api/v1"),
        (cde_setup._endpoint, "https://vcluster.cloudera.site/"),
        (cde_setup._url, "cde.example.com/cde"),
        (cde_setup._key, ""),
        (cde_setup._key, "<Private Key>"),
        (cde_setup._key, "chiave con spazi"),
    ],
)
def test_valori_rifiutati(parse, raw):
    with pytest.raises(ValueError) as error:
        parse(raw)
    if parse is cde_setup._key and raw:
        assert raw not in str(error.value), "una chiave non va mai stampata"


def test_da_zero_spiega_dove_trovare_tutto(home, cde, monkeypatch, capsys):
    calls, _ = cde
    cde_setup.CLI.unlink()
    _answers(monkeypatch, {})
    monkeypatch.setattr("sys.argv", ["cde_setup.py"])
    with pytest.raises(SystemExit, match="rilancia make cde-setup"):
        cde_setup.main()
    out = capsys.readouterr().out
    assert all(where in out for where in ("[1/3]", "CLI TOOL", "[2/3]", "JOBS API URL", "[3/3]", "Generate Access Key"))
    assert ["cde", "job", "list"] not in calls and not (home / ".env").exists()


def test_chiede_quello_che_manca_e_lo_scrive_nel_env(home, cde, monkeypatch, capsys):
    calls, _ = cde
    answers = {"Incolla il Jobs API URL": [ENDPOINT], "Incolla l'Access Key ID": ["id"], "Incolla la Private": ["k+/="]}
    _answers(monkeypatch, answers)
    monkeypatch.setattr("sys.argv", ["cde_setup.py", "test"])
    cde_setup.main()
    env = (home / ".env").read_text(encoding="utf-8").splitlines()
    assert {f"CDE_VCLUSTER_ENDPOINT={ENDPOINT}", "CDE_ACCESS_KEY_ID=id", "CDE_ACCESS_KEY_SECRET=k+/="} <= set(env)
    assert ["cde", "job", "list"] in calls
    out = capsys.readouterr().out
    assert "  OK test" in out and "k+/=" not in out


def test_gia_configurato_non_chiede_nulla_ma_mostra_i_passi(home, cde, monkeypatch, capsys):
    for name, value in zip(VARIABLES, (ENDPOINT, "id", "chiave")):
        monkeypatch.setenv(name, value)
    asked = _answers(monkeypatch, {})
    assert [cde_setup.cli(), cde_setup.endpoint(), cde_setup.access_key(), cde_setup.connection()] == [True] * 4
    assert asked == [] and not (home / ".env").exists()
    out = capsys.readouterr().out
    for title in ("[1/3] CLI cde: già fatto", "[2/3] Endpoint del vcluster: già fatto", "[3/3] Access key: già fatto"):
        assert title in out
    assert all(where in out for where in ("Cluster Details", "CLI TOOL", "JOBS API URL", "Generate Access Key"))


def test_configurato_senza_collegarsi(home, monkeypatch):
    monkeypatch.setattr(cde_setup.shutil, "which", lambda name: "/usr/local/bin/cde")
    assert not cde_setup.configured()
    for name, value in zip(VARIABLES, (ENDPOINT, "id", "chiave")):
        monkeypatch.setenv(name, value)
    assert cde_setup.configured()
    (home / "cde").write_bytes(b"scaricata")
    assert not cde_setup.configured(), "la CLI trascinata nel repo non è ancora installata"


def test_aspetta_la_cli_nella_cartella_del_repo(home, cde, monkeypatch, capsys):
    cde_setup.CLI.unlink()
    dropped = iter([False, True])

    def press_enter(question, secret=False):
        if next(dropped):
            (home / "cde").write_bytes(b"scaricata")
        return ""

    monkeypatch.setattr(cde_setup, "_input", press_enter)
    assert cde_setup.cli()
    assert "Non trovo il file cde" in capsys.readouterr().out
    assert cde_setup.CLI.read_bytes() == b"scaricata" and not (home / "cde").exists()


def test_scarica_la_cli_dall_url(home, cde, monkeypatch):
    calls, _ = cde
    cde_setup.CLI.unlink()
    _answers(monkeypatch, {"Premi invio": ["https://example.com/cde"]})
    assert cde_setup.cli()
    assert any(cmd[0] == "curl" and cmd[-1] == "https://example.com/cde" for cmd in calls)
    assert "CDE_CLI_DOWNLOAD_URL=https://example.com/cde\n" in (home / ".env").read_text(encoding="utf-8")


def test_se_il_vcluster_non_risponde_fa_reinserire_endpoint_e_chiave(home, cde, monkeypatch, capsys):
    for name, value in zip(VARIABLES, (ENDPOINT, "id", "sbagliata")):
        monkeypatch.setenv(name, value)

    def run(cmd, **kwargs):
        refused = cmd[1:] == ["job", "list"] and os.environ["CDE_ACCESS_KEY_SECRET"] != "giusta"
        return subprocess.CompletedProcess(cmd, int(refused), "cde version 1.0.0\n", "401 Unauthorized\n")

    monkeypatch.setattr(cde_setup.subprocess, "run", run)
    answers = {"Vuoi reinserire": ["s"], "Incolla il Jobs API URL": [ENDPOINT], "Incolla la Private": ["giusta"]}
    _answers(monkeypatch, {**answers, "Incolla l'Access Key ID": ["id"]})
    monkeypatch.setattr("sys.argv", ["cde_setup.py", "test"])
    cde_setup.main()
    out = capsys.readouterr().out
    assert "401 Unauthorized" in out and "DEUser" in out and "  OK test" in out
    assert "CDE_ACCESS_KEY_SECRET=giusta" in (home / ".env").read_text(encoding="utf-8").splitlines()


def test_prerequisiti(env, cde, monkeypatch):
    _, missing = cde
    ctx = render.context(env)
    ctx["env"]["credentials"] = ["github-token"]
    monkeypatch.setattr(cde_setup.render, "context", lambda _: ctx)
    missing.add("github-token")
    checks = {label: status for status, label, *_ in cde_setup.prerequisites(env)}
    assert checks["workload credential github-token"] == cde_setup.MISSING
    if "quality" in ctx:
        assert checks[f"job del dq-framework {ctx['quality']['dqJob']}"] == cde_setup.OK


def test_prerequisiti_dell_export(env, cde):
    export = render.context(env)["env"].get("export")
    if not export:
        pytest.skip("data product senza job export")
    _, missing = cde
    missing.add(export["credential"])
    checks = {label: status for status, label, *_ in cde_setup.prerequisites(env)}
    assert checks[f"workload credential {export['credential']}"] == cde_setup.MISSING, "dalla definizione del job"
    container = f"container {export['container']} nello storage account {export['account']}"
    assert checks[container] == cde_setup.CHECK, "il container sta su Azure: la CLI cde non lo vede"


def test_solo_ok_se_non_manca_nulla(monkeypatch, capsys):
    pool = (cde_setup.CHECK, "pool Airflow dq", "in Airflow")
    checks = {
        "test": [(cde_setup.OK, "job del dq-framework dq"), pool],
        "prod": [(cde_setup.MISSING, "workload credential github-token", "si crea su CDE"), pool],
    }
    monkeypatch.setattr(cde_setup, "prerequisites", checks.get)
    assert cde_setup.report(["test", "prod"]) == ["prod"]
    out = capsys.readouterr().out
    assert "  OK test\n" in out and "job del dq-framework" not in out
    assert "  prod: manca qualcosa" in out and "workload credential github-token" in out
    assert out.count("pool Airflow dq") == 1, "i controlli a mano una volta sola"


def test_python_env_creata_dal_deploy(env, cde, monkeypatch):
    if not render.jobs():
        pytest.skip("data product senza Modulo Dati")
    job = render.jobs()[0]
    monkeypatch.setattr(cde_setup.apply, "requirements", lambda name: Path("requirements.txt") if name == job else None)
    checks = {label: status for status, label, *_ in cde_setup.prerequisites(env)}
    assert checks[f"python-env del job {job}"] == cde_setup.OK
