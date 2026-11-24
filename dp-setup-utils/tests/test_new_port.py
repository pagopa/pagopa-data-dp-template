from __future__ import annotations

import shutil

import new_port
import pytest
import render
import setup
import yaml

COPY_IGNORE = shutil.ignore_patterns(
    ".git", "dist", "build", "__pycache__", "*.egg-info", ".pytest_cache", ".ruff_cache", ".venv"
)
NAME = "porta_di_prova"


@pytest.fixture
def clone(tmp_path):
    root = tmp_path / "dp"
    shutil.copytree(render.ROOT, root, ignore=COPY_IGNORE)
    return root


def _descriptor(root) -> dict:
    return yaml.safe_load((root / "data-product.yaml").read_text(encoding="utf-8"))


def test_output_port(clone):
    before = _descriptor(clone)
    changes = new_port.new_port(NAME, clone)
    after = _descriptor(clone)
    port = {"name": NAME, "dataContractPath": setup.default_contract(before["domain"], NAME)}
    assert after["outputPorts"] == [*before["outputPorts"], port]
    assert {**after, "outputPorts": None} == {**before, "outputPorts": None}
    created = [path for action, path, _ in changes if action == "creato"]
    if not (clone / "data").is_dir():
        assert created == []
        return
    migrations = [new_port.MIGRATION.match(path.name) for path in (clone / "data" / "ddl" / "tables").glob("*.sql")]
    numbers = sorted(int(match.group(1)) for match in migrations if match)
    assert created == [f"data/ddl/tables/V{numbers[-1]:03d}__create_{NAME}.sql"]
    assert numbers[-1] == (numbers[-2] if len(numbers) > 1 else 0) + 1
    assert (clone / created[0]).read_text(encoding="utf-8").startswith("-- TODO")


def test_input_port_con_contratto(clone):
    changes = new_port.new_port(NAME, clone, contract="src/data/pagopa/x/dc-x.yaml", input_port=True)
    assert _descriptor(clone)["inputPorts"][-1] == {"name": NAME, "dataContractPath": "src/data/pagopa/x/dc-x.yaml"}
    assert [action for action, _, _ in changes] == ["modificato"]


@pytest.mark.parametrize(
    ("name", "contract", "error"),
    [("Porta", None, "identificatore"), ("", None, "nome vuoto"), (NAME, "contratto.json", ".yaml")],
)
def test_valori_non_validi(clone, name, contract, error):
    with pytest.raises(ValueError, match=error):
        new_port.new_port(name, clone, contract=contract)


def test_porta_ripetuta(clone):
    new_port.new_port(NAME, clone)
    with pytest.raises(ValueError, match="c'è già"):
        new_port.new_port(NAME, clone)


SUPERSET = "https://superset.example.com/superset/dashboard/42/?standalone=1#kpi"
SODA = "https://cloud.soda.io/datasets/a1b2/checks"
EXISTING = {"name": "esistente", "type": "superset", "url": "https://superset.example.com/superset/dashboard/1/"}


@pytest.fixture
def observable(clone):
    # Le observability port del data product potrebbero già usare i nomi dei test, come "superset".
    dp = {**_descriptor(clone), "observabilityPorts": [EXISTING]}
    (clone / "data-product.yaml").write_text(setup.descriptor_text(dp), encoding="utf-8", newline="\n")
    return clone


def test_observability_port_superset(observable):
    before = _descriptor(observable)
    changes = new_port.new_observability_port("", "superset", observable, address=SUPERSET)
    after = _descriptor(observable)
    port = {"name": "superset", "type": "superset", "url": SUPERSET}
    assert after["observabilityPorts"] == [EXISTING, port]
    assert {**after, "observabilityPorts": None} == {**before, "observabilityPorts": None}
    assert [action for action, _, _ in changes] == ["modificato"]
    with pytest.raises(ValueError, match="c'è già"):
        new_port.new_observability_port("superset", "superset", observable, address=SUPERSET)


def test_observability_port_sodacloud(observable):
    sets = new_port.datasets(f"payments={SODA}, silver.transfers={SODA}?x=1")
    new_port.new_observability_port("soda", "sodacloud", observable, sets=sets)
    datasets = [{"name": "payments", "url": SODA}, {"name": "silver.transfers", "url": f"{SODA}?x=1"}]
    port = {"name": "soda", "type": "sodacloud", "datasets": datasets}
    assert _descriptor(observable)["observabilityPorts"] == [EXISTING, port]


@pytest.mark.parametrize(
    ("kind", "address", "sets", "error"),
    [
        ("grafana", SUPERSET, None, "superset o sodacloud"),
        ("superset", None, None, "https://"),
        ("superset", "superset.example.com/dashboard/42", None, "https://"),
        ("superset", "https://a b", None, "https://"),
        ("sodacloud", None, None, "almeno un dataset"),
        ("sodacloud", None, [("payments", "ftp://example.com")], "https://"),
        ("sodacloud", None, [("payments", SODA), ("payments", SODA)], "ripetuto"),
        ("sodacloud", None, [("1payments", SODA)], "nome della tabella"),
    ],
)
def test_observability_port_non_valida(observable, kind, address, sets, error):
    with pytest.raises(ValueError, match=error):
        new_port.new_observability_port("monitor", kind, observable, address=address, sets=sets)


def test_descrittore_riscritto_nel_formato_standard():
    text = (
        'name: dp-x-y\ndomain: x\nversion: 1.2.3\ndescription: "Descrizione: con i due punti"\n'
        'owner: "@org/team"\nstatus: active\n\n'
        "modules:\n  data: true\n  quality: false\n\n"
        "inputPorts: []\n\n"
        "outputPorts:\n  - name: a\n    dataContractPath: src/a.yaml\n\n"
        "observabilityPorts: []\n"
    )
    assert setup.descriptor_text(yaml.safe_load(text)) == text
    text = text.replace(
        "observabilityPorts: []\n",
        "observabilityPorts:\n"
        "  - name: superset\n    type: superset\n    url: https://superset.example.com/dashboard/42/\n"
        "  - name: soda\n    type: sodacloud\n    datasets:\n"
        "      - name: payments\n        url: https://cloud.soda.io/d/1\n"
        "      - name: transfers\n        url: https://cloud.soda.io/d/2\n",
    )
    assert setup.descriptor_text(yaml.safe_load(text)) == text
